"""Точка входа: запуск Telegram-бота приёма заявок."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, ErrorEvent
from pydantic import ValidationError

from bot import texts
from bot.config import Settings, get_settings
from bot.database import create_engine, create_sessionmaker, init_db
from bot.handlers import get_routers
from bot.middlewares import DbSessionMiddleware, SettingsMiddleware, UserSyncMiddleware
from bot.services.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


def setup_logging(level: int) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Приглушаем болтливые библиотеки
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def setup_commands(bot: Bot, settings: Settings) -> None:
    """Настраивает меню команд: отдельное для админов."""
    user_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="menu", description="Открыть меню"),
        BotCommand(command="order", description="Оставить заявку"),
        BotCommand(command="cancel", description="Отменить заполнение"),
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    admin_commands = user_commands + [
        BotCommand(command="admin", description="Админ-панель"),
    ]
    for admin_id in settings.admin_id_list:
        try:
            await bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception:  # noqa: BLE001 — админ мог не начать диалог
            logger.warning(
                "Не удалось выставить команды для админа %s (не начал диалог?)",
                admin_id,
            )


async def on_error(event: ErrorEvent) -> None:
    """Последний рубеж: пользователь получает ответ, ошибка — в лог.

    Без этого хэндлера любое исключение (например, падение Google API
    в неожиданном месте) оставляло клиента без ответа и с «часиками».
    """
    logger.exception(
        "Необработанная ошибка при апдейте %s",
        event.update.update_id,
        exc_info=event.exception,
    )

    # Для нажатия кнопки главное — погасить «часики». Делаем это до всего
    # остального: у недоступного сообщения (inaccessible message) поля
    # message может не быть вовсе.
    callback = event.update.callback_query
    if callback is not None:
        try:
            await callback.answer(texts.ERROR_GENERIC)
            return
        except TelegramAPIError:
            logger.debug("Не удалось ответить на callback", exc_info=True)

    message = event.update.message or (callback.message if callback else None)
    if message is None:
        return

    try:
        await message.answer(texts.ERROR_GENERIC)
    except TelegramAPIError:
        logger.debug("Не удалось сообщить пользователю об ошибке", exc_info=True)


async def run_bot(bot: Bot, dispatcher: Dispatcher, sheets: GoogleSheetsService) -> None:
    """Запускает long polling с корректной остановкой по сигналу."""
    if sheets.enabled:
        healthy = await sheets.health_check()
        if healthy:
            logger.info("Google Таблицы подключены: %s", sheets.url)
        else:
            logger.warning(
                "Google Таблицы настроены, но недоступны. "
                "Заявки будут сохраняться в БД, синхронизация — с ошибкой."
            )
    else:
        logger.warning(
            "Google Таблицы не настроены (GOOGLE_SHEET_URL / GOOGLE_CREDENTIALS_PATH). "
            "Работаем без синхронизации."
        )

    await dispatcher.start_polling(
        bot,
        allowed_updates=dispatcher.resolve_used_update_types(),
        handle_signals=True,
    )


async def main() -> None:
    try:
        settings = get_settings()
    except ValidationError as exc:
        # Чаще всего это забытый .env: без понятного текста пользователь
        # увидит длинный трейсбек pydantic вместо подсказки.
        raise SystemExit(
            "Не удалось прочитать конфигурацию.\n"
            "Проверьте, что рядом с main.py лежит .env (образец — .env.example) "
            "и в нём заполнен BOT_TOKEN.\n\n"
            f"Детали: {exc}"
        ) from exc

    setup_logging(settings.log_level_int())

    if not settings.admin_id_list:
        logger.warning("ADMIN_IDS пуст: заявки будут копиться без уведомлений админам.")

    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)
    await init_db(engine)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())

    sheets = GoogleSheetsService(settings)

    # Middleware: порядок регистрации — от внешнего к внутреннему
    dispatcher.update.outer_middleware(SettingsMiddleware(settings))
    dispatcher.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    dispatcher.update.outer_middleware(UserSyncMiddleware())

    for router in get_routers():
        dispatcher.include_router(router)

    dispatcher.errors.register(on_error)

    # Зависимости, доступные в хэндлерах как аргументы
    dispatcher["settings"] = settings
    dispatcher["sheets"] = sheets

    # Всё, что создаёт сетевые ресурсы, оборачиваем в try/finally:
    # при неверном токене setup_commands падает, и без finally остаётся
    # незакрытая сессия aiohttp («Unclosed client session»).
    try:
        await setup_commands(bot, settings)
        logger.info("Бот запускается…")
        await run_bot(bot, dispatcher, sheets)
    except TelegramUnauthorizedError as exc:
        raise SystemExit(
            "Telegram отклонил BOT_TOKEN (Unauthorized).\n"
            "Проверьте токен в .env: он должен быть вида 123456789:AAH... "
            "и получен от @BotFather. Если токен перевыпускали, вставьте новый."
        ) from exc
    finally:
        await bot.session.close()
        await engine.dispose()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем (Ctrl+C)")
    except SystemExit as exc:
        # SystemExit проглатывается asyncio.run(), поэтому текст ошибки
        # (например, про незаполненный .env) печатаем здесь.
        if exc.code not in (0, None):
            print(f"\n{exc.code}", file=sys.stderr)
            sys.exit(1)
