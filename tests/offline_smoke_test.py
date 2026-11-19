"""Офлайн smoke-тест: роутинг, БД, FSM-сценарий, устойчивость к сбоям Google.

Никакой сети: бот подменяется FakeBot, Google-сервис — заглушкой.
Запуск:  python tests/offline_smoke_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Позволяем запускать из любой папки: корень проекта в sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

from bot.config import Settings  # noqa: E402
from bot.database import create_engine, create_sessionmaker, init_db, repo  # noqa: E402
from bot.handlers import get_routers  # noqa: E402
from bot.keyboards.callbacks import AdminCB, AdminOrderCB  # noqa: E402
from bot.middlewares import (  # noqa: E402
    DbSessionMiddleware,
    SettingsMiddleware,
    UserSyncMiddleware,
)
from bot.services.google_sheets import GoogleSheetsService, SheetsError  # noqa: E402
from bot.services.orders import change_order_status, submit_order  # noqa: E402

SENT: list[str] = []
FAILS: list[str] = []


class FakeBot(Bot):
    """Бот, который не ходит в Telegram, а запоминает исходящие методы."""

    async def __call__(self, method, request_timeout=None):
        SENT.append(type(method).__name__)
        return True


class BrokenSheets:
    """Google API «упал»: любая операция возвращает понятную ошибку."""

    enabled = True

    async def append_order(self, order):
        raise SheetsError("Нет доступа к таблице: выдайте роль «Редактор».")

    async def update_status(self, order, sheet_row=None):
        raise SheetsError("Google API не ответил вовремя (таймаут 30 с).")

    async def health_check(self):
        return False


def check(condition: bool, message: str) -> None:
    status = "OK  " if condition else "FAIL"
    print(f"  [{status}] {message}")
    if not condition:
        FAILS.append(message)


def make_env(settings: Settings):
    async def build():
        engine = create_engine(settings.database_url)
        sessionmaker = create_sessionmaker(engine)
        await init_db(engine)

        bot = FakeBot(token="123456:TEST")
        dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
        dp.update.outer_middleware(SettingsMiddleware(settings))
        dp.update.outer_middleware(DbSessionMiddleware(sessionmaker))
        dp.update.outer_middleware(UserSyncMiddleware())
        for router in get_routers():
            dp.include_router(router)
        dp["settings"] = settings
        dp["sheets"] = GoogleSheetsService(settings)
        return engine, sessionmaker, bot, dp

    return build()


async def main() -> None:
    tmp = tempfile.mkdtemp()
    # Тесты не должны зависеть от локального .env: иначе реальные
    # GOOGLE_SHEET_URL / credentials.json ломают ожидания «интеграция выключена».
    settings = Settings(
        _env_file=None,
        bot_token="123456:TEST",
        admin_ids="1,2",
        database_url=f"sqlite+aiosqlite:///{tmp}/test.db",
    )
    engine, sessionmaker, bot, dp = await make_env(settings)

    print("1. Диспетчер")
    used = sorted(dp.resolve_used_update_types())
    check(set(used) == {"message", "callback_query"}, f"типы апдейтов: {used}")

    now = 1_700_000_000
    admin = User(id=1, is_bot=False, first_name="Админ", username="admin")
    client = User(id=555, is_bot=False, first_name="Иван", username="ivan")
    chat_client = Chat(id=555, type="private", first_name="Иван")
    chat_admin = Chat(id=1, type="private", first_name="Админ")

    uid = 0

    def nid() -> int:
        nonlocal uid
        uid += 1
        return uid

    def msg(text, user=client, chat=chat_client, contact=None) -> Update:
        return Update(
            update_id=nid(),
            message=Message(
                message_id=nid(), date=now, chat=chat, from_user=user,
                text=text, contact=contact,
            ),
        )

    def cb(data: str, user=client, chat=chat_client) -> Update:
        return Update(
            update_id=nid(),
            callback_query=CallbackQuery(
                id=str(nid()),
                from_user=user,
                chat_instance="ci",
                data=data,
                message=Message(
                    message_id=777, date=now, chat=chat, from_user=user, text="menu"
                ),
            ),
        )

    async def feed(update: Update) -> list[str]:
        SENT.clear()
        await dp.feed_update(bot, update)
        return list(SENT)

    print("2. Клиентский сценарий: /start → заявка → мои заявки")
    check(await feed(msg("/start")) == ["SendMessage"], "/start отправляет меню")
    check("EditMessageText" in await feed(cb("menu:services")), "экран услуг")
    check("SendMessage" in await feed(cb("menu:new_order")), "старт FSM")
    check("EditMessageText" in await feed(cb("svc:bot")), "шаг 1: услуга выбрана")
    check("SendMessage" in await feed(cb("ord:use_profile_name")), "шаг 2: имя из профиля")
    check(len(await feed(msg("+7 (999) 123-45-67"))) == 2, "шаг 3: телефон принят")
    check(len(await feed(msg("Нужен бот для записи"))) == 1, "шаг 4: комментарий принят")
    sent = await feed(cb("ord:send"))
    check("SendMessage" in sent, "шаг 5: заявка отправлена")

    async with sessionmaker() as session:
        orders, total = await repo.get_user_orders(session, 555)
    check(total == 1, f"заявка в БД (всего {total})")
    check(
        orders[0].phone == "+79991234567",
        f"телефон нормализован: {orders[0].phone}",
    )
    check(orders[0].service == "Разработка бота", f"услуга: {orders[0].service}")
    check(orders[0].status == "new", f"статус при создании: {orders[0].status}")
    order_id = orders[0].id

    check("EditMessageText" in await feed(cb("menu:my_orders")), "«Мои заявки» отрисованы")

    print("2б. Кнопка «Отмена» работает на каждом шаге FSM")
    for step, presses in (
        ("услуга", []),
        ("имя", [cb("svc:site")]),
        ("телефон", [cb("svc:site"), cb("ord:use_profile_name")]),
        ("комментарий", [cb("svc:site"), cb("ord:use_profile_name"), msg("+79991234567")]),
        (
            "подтверждение",
            [
                cb("svc:site"),
                cb("ord:use_profile_name"),
                msg("+79991234567"),
                msg("Комментарий"),
            ],
        ),
    ):
        await feed(cb("menu:new_order"))
        for press in presses:
            await feed(press)
        sent = await feed(cb("ord:cancel"))
        check(
            "EditMessageText" in sent and "AnswerCallbackQuery" in sent,
            f"«Отмена» на шаге «{step}» срабатывает",
        )

    print("3. Админ-панель")
    check(await feed(msg("/admin", user=admin, chat=chat_admin)) == ["SendMessage"], "/admin")
    check(
        "EditMessageText" in await feed(cb(AdminCB(action="stats").pack(), admin, chat_admin)),
        "статистика",
    )
    check(
        "EditMessageText" in await feed(cb(AdminCB(action="orders", page=1).pack(), admin, chat_admin)),
        "список заявок",
    )
    check(
        "EditMessageText" in await feed(
            cb(AdminOrderCB(action="view", order_id=order_id, page=1).pack(), admin, chat_admin)
        ),
        "карточка заявки",
    )
    sent = await feed(
        cb(
            AdminOrderCB(action="status", order_id=order_id, status="done", page=1).pack(),
            admin,
            chat_admin,
        )
    )
    check("SendMessage" in sent, "смена статуса уведомила клиента")
    check(
        await feed(cb(AdminCB(action="sheet").pack(), admin, chat_admin))
        == ["AnswerCallbackQuery"],
        "без GOOGLE_SHEET_URL кнопка показывает предупреждение",
    )
    check(
        "EditMessageText" in await feed(cb(AdminCB(action="broadcast").pack(), admin, chat_admin)),
        "мастер рассылки открылся",
    )
    check("SendMessage" in await feed(msg("Тест рассылки", user=admin, chat=chat_admin)),
          "предпросмотр рассылки")

    print("4. Доступ: клиент не попадает в админку")
    check(
        await feed(cb(AdminCB(action="stats").pack(), client, chat_client)) == ["AnswerCallbackQuery"],
        "админский колбэк клиенту недоступен",
    )
    denied = await feed(msg("/admin", user=client, chat=chat_client))
    check(
        denied == ["SendMessage"],
        f"клиенту на /admin приходит отказ (не тишина): {denied}",
    )

    print("5. Сбой Google: заявка сохраняется, админ предупреждён")
    async with sessionmaker() as session:
        order = await submit_order(
            bot=bot,
            session=session,
            settings=settings,
            sheets=BrokenSheets(),  # type: ignore[arg-type]
            user_id=999,
            username="client2",
            service_code="site",
            name="Мария",
            phone="+79990001122",
            comment="Лендинг",
        )
        check(order.id > 0 and order.sheet_row is None, f"заявка №{order.id} в БД без строки таблицы")
        check(
            SENT.count("SendMessage") >= 2 * len(settings.admin_id_list),
            f"админам ушло уведомление и предупреждение ({SENT.count('SendMessage')})",
        )

        changed, sheet_error = await change_order_status(
            bot=bot,
            session=session,
            settings=settings,
            sheets=BrokenSheets(),  # type: ignore[arg-type]
            order=order,
            new_status="in_progress",
        )
        check(changed and sheet_error is not None, "статус изменён несмотря на сбой таблицы")
        fresh = await repo.get_order(session, order.id)
        check(fresh is not None and fresh.status == "in_progress", "статус в БД обновлён")

    print("6. Разбор ссылки на таблицу и конфига")
    check(
        settings.spreadsheet_id is None,
        "пустой GOOGLE_SHEET_URL не даёт ID таблицы",
    )
    configured = Settings(
        _env_file=None,
        bot_token="123456:TEST",
        admin_ids="1",
        google_sheet_url="https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890/edit#gid=42",
    )
    check(
        configured.spreadsheet_id == "1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        f"ID таблицы извлечён: {configured.spreadsheet_id}",
    )
    check(configured.worksheet_gid == 42, f"gid извлечён: {configured.worksheet_gid}")
    # Указываем заведомо несуществующий путь: иначе реальный credentials.json
    # в корне проекта сделает интеграцию «включённой» и проверка станет ложной.
    check(
        not Settings(
            _env_file=None,
            bot_token="123456:TEST",
            admin_ids="1",
            google_sheet_url="https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890/edit",
            google_credentials_path="__no_such_file__.json",
        ).sheets_enabled,
        "без credentials.json интеграция выключена",
    )
    check(
        Settings(_env_file=None, bot_token="1:TEST", admin_ids="[11, 22, 33]").admin_id_list == [11, 22, 33],
        "ADMIN_IDS в формате [11, 22, 33]",
    )

    print("7. Валидация")
    from bot.utils import normalize_phone, valid_name

    check(normalize_phone("8 999 123-45-67") == "+79991234567", "8XXXXXXXXXX → +7XXXXXXXXXX")
    check(normalize_phone("123") is None, "короткий номер отклонён")
    check(normalize_phone("abc") is None, "буквы отклонены")
    check(valid_name("И") is None, "слишком короткое имя отклонено")
    check(valid_name("Мария-Анна") == "Мария-Анна", "двойное имя принято")

    await bot.session.close()
    await engine.dispose()

    print()
    if FAILS:
        print(f"ПРОВАЛОВ: {len(FAILS)}")
        for item in FAILS:
            print(f"  - {item}")
        raise SystemExit(1)
    print("Все проверки пройдены ✅")


if __name__ == "__main__":
    asyncio.run(main())
