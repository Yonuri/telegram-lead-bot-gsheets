"""Бизнес-логика заявок: сохранение, синхронизация с таблицей, уведомления.

Вынесено из хэндлеров, потому что используется и клиентским сценарием,
и админкой (смена статуса).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.database import repo
from bot.database.models import Order
from bot.keyboards import admin as admin_kb
from bot.services.google_sheets import GoogleSheetsService, SheetsError
from bot.utils import esc, fmt_dt

logger = logging.getLogger(__name__)


# ------------------------------- Уведомления -------------------------------

async def _notify_admins(
    bot: Bot,
    settings: Settings,
    text: str,
    reply_markup=None,
) -> None:
    """Рассылает уведомление всем администраторам, игнорируя недоступных."""
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(
                admin_id, text, reply_markup=reply_markup, disable_web_page_preview=True
            )
        except TelegramForbiddenError:
            logger.warning("Админ %s не начал диалог с ботом", admin_id)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.send_message(admin_id, text, reply_markup=reply_markup)
            except TelegramAPIError:
                logger.exception("Повторная отправка админу %s не удалась", admin_id)
        except TelegramAPIError:
            logger.exception("Не удалось отправить уведомление админу %s", admin_id)


def _format_admin_order_notification(order: Order, settings: Settings, sheet_note: str) -> str:
    return texts.ADMIN_NEW_ORDER.format(
        order_id=order.id,
        service=esc(order.service),
        name=esc(order.name),
        phone=esc(order.phone),
        comment=esc(order.comment or texts.EMPTY_COMMENT),
        username=f"@{esc(order.username)}" if order.username else "—",
        user_id=order.user_id,
        created_at=fmt_dt(order.created_at, settings.timezone),
    ) + f"\n\n📊 Синхронизация: {sheet_note}"


# ------------------------------ Создание заявки ------------------------------

async def submit_order(
    *,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
    sheets: GoogleSheetsService,
    user_id: int,
    username: str | None,
    service_code: str,
    name: str,
    phone: str,
    comment: str,
) -> Order:
    """Сохраняет заявку в БД, пишет в таблицу и уведомляет админов.

    Заявка сохраняется первой и независимо от Google: если API недоступен,
    админ получит предупреждение, а данные останутся в базе.
    """
    # Страховка от FOREIGN KEY: пользователь обычно уже создан middleware,
    # но сервис не должен зависеть от порядка вызова.
    await repo.get_or_create_user(
        session, user_id=user_id, username=username, full_name=None
    )

    order = await repo.create_order(
        session,
        user_id=user_id,
        username=username,
        service=texts.service_title(service_code),
        name=name,
        phone=phone,
        comment=comment,
    )

    sheet_error: SheetsError | None = None
    sheet_row: int | None = None

    if sheets.enabled:
        try:
            sheet_row = await sheets.append_order(order) or None
            if sheet_row:
                await repo.set_order_sheet_row(session, order, sheet_row)
        except SheetsError as exc:
            sheet_error = exc
            logger.warning("Заявка №%s не синхронизирована: %s", order.id, exc)
    else:
        logger.info("Google Таблицы не настроены — заявка №%s только в БД", order.id)

    if sheet_error is not None:
        sheet_note = f"⚠️ не удалось ({sheet_error})"
    elif not sheets.enabled:
        sheet_note = "отключена (нет настройки)"
    else:
        sheet_note = texts.SHEET_ROW_OK.format(row=sheet_row or "?")

    await _notify_admins(
        bot,
        settings,
        _format_admin_order_notification(order, settings, sheet_note),
        reply_markup=admin_kb.new_order_kb(order.id),
    )

    if sheet_error is not None:
        await _notify_admins(
            bot,
            settings,
            texts.ADMIN_ORDER_SHEET_FAILED.format(
                order_id=order.id, error=esc(str(sheet_error))
            ),
        )

    return order


# ------------------------------- Смена статуса -------------------------------

async def change_order_status(
    *,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
    sheets: GoogleSheetsService,
    order: Order,
    new_status: str,
) -> tuple[bool, str | None]:
    """Меняет статус в БД, таблице и уведомляет клиента.

    Возвращает (успех, текст_ошибки_синхронизации). Статус в БД меняется
    всегда, даже если таблица недоступна.
    """
    if order.status == new_status:
        return False, None

    await repo.set_order_status(session, order, new_status)

    sheet_error: str | None = None
    if sheets.enabled:
        try:
            await sheets.update_status(order, order.sheet_row)
        except SheetsError as exc:
            sheet_error = str(exc)
            logger.warning("Статус заявки №%s не обновлён в таблице: %s", order.id, exc)

    # Уведомление клиенту — не критично для результата операции
    try:
        await bot.send_message(
            order.user_id,
            texts.USER_STATUS_CHANGED.format(
                order_id=order.id,
                service=esc(order.service),
                status=esc(texts.status_label(new_status)),
            ),
            disable_web_page_preview=True,
        )
    except TelegramForbiddenError:
        await repo.mark_user_blocked(session, order.user_id)
        logger.info("Клиент %s заблокировал бота", order.user_id)
    except TelegramAPIError:
        logger.warning("Не удалось уведомить клиента %s", order.user_id, exc_info=True)

    return True, sheet_error
