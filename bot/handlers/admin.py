"""Админ-панель: статистика, заявки, смена статуса, рассылка."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.text_decorations import html_decoration
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import texts
from bot.config import Settings
from bot.database import repo
from bot.database.models import ALL_STATUSES
from bot.filters import IsAdmin
from bot.keyboards import admin as admin_kb
from bot.keyboards.callbacks import AdminCB, AdminOrderCB, BroadcastCB
from bot.services.google_sheets import GoogleSheetsService
from bot.services.orders import change_order_status
from bot.states.forms import BroadcastForm
from bot.utils import esc, fmt_dt, safe_edit

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

# Лимиты Telegram: длиннее — API отклонит сообщение у всех получателей
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


# ---------------------------------- Вход ----------------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.ADMIN_PANEL, reply_markup=admin_kb.admin_panel_kb())


@router.callback_query(AdminCB.filter(F.action == "panel"))
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, texts.ADMIN_PANEL, admin_kb.admin_panel_kb())
    await callback.answer()


# -------------------------------- Статистика --------------------------------

@router.callback_query(AdminCB.filter(F.action == "stats"))
async def cb_stats(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    sheets: GoogleSheetsService,
) -> None:
    stats = await repo.get_stats(session, settings.timezone)

    status_lines = "\n".join(
        f"{texts.status_label(status)}: <b>{stats.by_status.get(status, 0)}</b>"
        for status in ALL_STATUSES
    )

    if not sheets.enabled:
        sheets_status = texts.ADMIN_STATS_SHEETS_OFF
    else:
        sheets_status = (
            texts.ADMIN_STATS_SHEETS_ON
            if await sheets.health_check()
            else texts.ADMIN_STATS_SHEETS_DOWN
        )

    text = texts.ADMIN_STATS.format(
        users_total=stats.users_total,
        orders_total=stats.orders_total,
        orders_today=stats.orders_today,
        orders_week=stats.orders_week,
        status_lines=status_lines,
        sheets_status=sheets_status,
    )
    await safe_edit(callback.message, text, admin_kb.admin_back_kb())
    await callback.answer()


# ----------------------------- Список заявок -----------------------------

def _orders_list_text(orders, page: int, pages: int, settings: Settings) -> str:
    """Текст страницы списка заявок."""
    lines = [
        f"{texts.status_emoji(order.status)} <b>№{order.id}</b> · "
        f"{esc(order.name)} · {esc(order.service)}\n"
        f"    📞 {esc(order.phone)} · 🗓 {fmt_dt(order.created_at, settings.timezone)}"
        for order in orders
    ]
    return texts.ADMIN_ORDERS_HEADER.format(page=page, pages=pages) + "\n".join(lines)


@router.callback_query(AdminCB.filter(F.action == "orders"))
async def cb_orders(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    settings: Settings,
) -> None:
    orders, page, pages = await repo.get_orders_page(
        session, page=callback_data.page, per_page=settings.orders_per_page
    )

    if not orders:
        await safe_edit(callback.message, texts.ADMIN_ORDERS_EMPTY, admin_kb.admin_back_kb())
        await callback.answer()
        return

    await safe_edit(
        callback.message,
        _orders_list_text(orders, page, pages, settings),
        admin_kb.orders_page_kb(orders, page=page, pages=pages),
    )
    await callback.answer()


@router.callback_query(AdminOrderCB.filter(F.action == "view"))
async def cb_order_view(
    callback: CallbackQuery,
    callback_data: AdminOrderCB,
    session: AsyncSession,
    settings: Settings,
) -> None:
    order = await repo.get_order(session, callback_data.order_id)
    if order is None:
        await callback.answer(texts.ADMIN_ORDER_NOT_FOUND, show_alert=True)
        return

    text = _order_card_text(order, settings)
    await safe_edit(
        callback.message,
        text,
        admin_kb.order_card_kb(order, page=max(callback_data.page, 1)),
    )
    await callback.answer()


# ----------------------------- Смена статуса -----------------------------

@router.callback_query(AdminOrderCB.filter(F.action == "status"))
async def cb_order_set_status(
    callback: CallbackQuery,
    callback_data: AdminOrderCB,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    bot: Bot,
    sheets: GoogleSheetsService,
) -> None:
    if callback_data.status not in ALL_STATUSES:
        await callback.answer("Неизвестный статус.", show_alert=True)
        return

    order = await repo.get_order(session, callback_data.order_id)
    if order is None:
        await callback.answer(texts.ADMIN_ORDER_NOT_FOUND, show_alert=True)
        return

    changed, sheet_error = await change_order_status(
        bot=bot,
        session=session,
        settings=settings,
        sheets=sheets,
        order=order,
        new_status=callback_data.status,
    )

    if not changed:
        await callback.answer(
            texts.ADMIN_STATUS_SAME.format(
                order_id=order.id, status=texts.status_title(order.status)
            ),
            show_alert=True,
        )
        return

    await callback.answer(
        texts.ADMIN_STATUS_UPDATED.format(
            order_id=order.id, status=texts.status_title(order.status)
        )
    )

    # Предупреждение о сбое синхронизации — отдельным сообщением
    if sheet_error:
        await bot.send_message(
            callback.from_user.id,
            texts.ADMIN_SHEET_SYNC_FAILED.format(
                order_id=order.id, error=esc(sheet_error)
            ),
        )

    # Обновляем карточку на месте — админ сразу видит новый статус
    await safe_edit(
        callback.message,
        _order_card_text(order, settings),
        admin_kb.order_card_kb(order, page=callback_data.page),
    )


def _order_card_text(order, settings: Settings) -> str:
    return texts.ADMIN_ORDER_CARD.format(
        order_id=order.id,
        service=esc(order.service),
        name=esc(order.name),
        phone=esc(order.phone),
        comment=esc(order.comment or texts.EMPTY_COMMENT),
        username=f"@{esc(order.username)}" if order.username else "—",
        user_id=order.user_id,
        created_at=fmt_dt(order.created_at, settings.timezone),
        updated_at=fmt_dt(order.updated_at, settings.timezone),
        status=esc(texts.status_label(order.status)),
    )


# --------------------------------- Рассылка ---------------------------------

@router.callback_query(AdminCB.filter(F.action == "broadcast"))
async def cb_broadcast_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    recipients = await repo.get_broadcast_recipients(session)
    if not recipients:
        await callback.answer(texts.BROADCAST_EMPTY, show_alert=True)
        return

    await state.clear()
    await state.set_state(BroadcastForm.content)
    await state.update_data(recipients_count=len(recipients))
    await safe_edit(callback.message, texts.BROADCAST_ASK, admin_kb.admin_back_kb())
    await callback.answer()


@router.message(StateFilter(BroadcastForm.content))
async def broadcast_content(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if message.text and message.text.startswith("/"):
        await state.clear()
        await message.answer("Рассылка отменена.")
        return

    # Фото с подписью или просто текст
    if message.photo:
        photo_id = message.photo[-1].file_id
        # Подпись размечаем по caption_entities: message.html_text сюда тоже
        # сгодился бы (он падает на caption), но так намерение видно явно.
        content = (
            html_decoration.unparse(message.caption, message.caption_entities or [])
            if message.caption
            else ""
        )
        if len(content) > CAPTION_LIMIT:
            await message.answer(texts.BROADCAST_TOO_LONG.format(limit=CAPTION_LIMIT))
            return
        payload = {"kind": "photo", "photo_id": photo_id, "text": content}
        preview = content.strip() or "🖼 <i>Фото без подписи</i>"
    elif message.text:
        if len(message.html_text) > TEXT_LIMIT:
            await message.answer(texts.BROADCAST_TOO_LONG.format(limit=TEXT_LIMIT))
            return
        payload = {"kind": "text", "text": message.html_text}
        preview = message.html_text
    else:
        await message.answer(texts.BROADCAST_INVALID_CONTENT)
        return

    recipients = await repo.get_broadcast_recipients(session)
    await state.set_state(BroadcastForm.confirm)
    await state.update_data(payload=payload, recipients=recipients)

    await message.answer(
        texts.BROADCAST_PREVIEW.format(total=len(recipients), content=preview),
        reply_markup=admin_kb.broadcast_confirm_kb(),
    )


@router.callback_query(StateFilter(BroadcastForm.confirm), BroadcastCB.filter(F.action == "cancel"))
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, texts.BROADCAST_CANCELLED, admin_kb.admin_back_kb())
    await callback.answer()


# Активные рассылки — держим ссылки до завершения: иначе сборщик мусора
# может «убить» задачу посреди рассылки.
_BROADCAST_TASKS: set[asyncio.Task] = set()


@router.callback_query(StateFilter(BroadcastForm.confirm), BroadcastCB.filter(F.action == "send"))
async def broadcast_send(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    bot: Bot,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    data = await state.get_data()
    payload = data.get("payload") or {}
    recipients: list[int] = data.get("recipients") or []

    if not recipients:
        await state.clear()
        await callback.answer(texts.BROADCAST_EMPTY, show_alert=True)
        return

    await state.clear()
    await safe_edit(
        callback.message, texts.BROADCAST_STARTED.format(total=len(recipients))
    )
    await callback.answer()

    task = asyncio.create_task(
        _run_broadcast(
            bot=bot,
            chat_id=callback.from_user.id,
            payload=payload,
            recipients=recipients,
            delay=settings.broadcast_delay,
            sessionmaker=sessionmaker,
        )
    )
    _BROADCAST_TASKS.add(task)
    task.add_done_callback(_BROADCAST_TASKS.discard)


async def _run_broadcast(
    *,
    bot: Bot,
    chat_id: int,
    payload: dict,
    recipients: list[int],
    delay: float,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Рассылка в фоне: не тормозит обработку других апдейтов."""
    ok = blocked = failed = 0

    for user_id in recipients:
        try:
            if payload.get("kind") == "photo":
                await bot.send_photo(
                    user_id,
                    payload["photo_id"],
                    caption=payload.get("text") or None,
                )
            else:
                await bot.send_message(
                    user_id, payload.get("text", ""), disable_web_page_preview=True
                )
            ok += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                if payload.get("kind") == "photo":
                    await bot.send_photo(
                        user_id, payload["photo_id"], caption=payload.get("text") or None
                    )
                else:
                    await bot.send_message(user_id, payload.get("text", ""))
                ok += 1
            except TelegramAPIError:
                failed += 1
        except TelegramForbiddenError:
            blocked += 1
            # Помечаем, чтобы не тратить на него запросы в следующих рассылках
            if sessionmaker is not None:
                try:
                    async with sessionmaker() as session:
                        await repo.mark_user_blocked(session, user_id)
                except Exception:  # noqa: BLE001 — пометка не должна ронять рассылку
                    logger.warning(
                        "Не удалось пометить %s как заблокировавшего", user_id
                    )
            # Запоминаем, чтобы не тратить запросы на него в следующих рассылках
            if sessionmaker is not None:
                try:
                    async with sessionmaker() as session:
                        await repo.mark_user_blocked(session, user_id)
                except Exception:  # noqa: BLE001 — пометка не должна ломать рассылку
                    logger.warning("Не удалось пометить %s как заблокировавшего", user_id)
        except TelegramAPIError as exc:
            failed += 1
            logger.warning("Рассылка: ошибка для %s — %s", user_id, exc)

        if delay:
            await asyncio.sleep(delay)

    try:
        await bot.send_message(
            chat_id,
            texts.BROADCAST_RESULT.format(ok=ok, blocked=blocked, failed=failed),
        )
    except TelegramAPIError:
        logger.exception("Не удалось отправить отчёт о рассылке")


# --------------------------- Ссылка на таблицу ---------------------------

@router.callback_query(AdminCB.filter(F.action == "sheet"))
async def cb_sheet_link(callback: CallbackQuery, settings: Settings) -> None:
    url = _spreadsheet_url(settings)
    if not url:
        await callback.answer(texts.SHEET_NOT_CONFIGURED, show_alert=True)
        return

    await callback.message.answer(
        texts.SHEET_LINK_TEXT.format(url=url),
        disable_web_page_preview=False,
    )
    await callback.answer()


def _spreadsheet_url(settings: Settings) -> str:
    sheet_id = settings.spreadsheet_id
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""


# ---------------------------- Служебные кнопки ----------------------------

@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
