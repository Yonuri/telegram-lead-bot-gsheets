"""Клавиатуры админ-панели."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.database.models import ALL_STATUSES, Order
from bot.keyboards.callbacks import AdminCB, AdminOrderCB, BroadcastCB
from bot.utils import clip


def admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_ADMIN_STATS, callback_data=AdminCB(action="stats"))
    builder.button(
        text=texts.BTN_ADMIN_ORDERS, callback_data=AdminCB(action="orders", page=1)
    )
    builder.button(text=texts.BTN_ADMIN_BROADCAST, callback_data=AdminCB(action="broadcast"))
    builder.button(text=texts.BTN_ADMIN_SHEET, callback_data=AdminCB(action="sheet"))
    builder.adjust(2, 2)
    return builder.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_ADMIN_BACK, callback_data=AdminCB(action="panel"))
    return builder.as_markup()


def orders_page_kb(
    orders: Sequence[Order], *, page: int, pages: int
) -> InlineKeyboardMarkup:
    """Пять заявок + открытие карточки + пагинация."""
    builder = InlineKeyboardBuilder()

    for order in orders:
        builder.row(
            InlineKeyboardButton(
                text=(
                    f"{texts.status_emoji(order.status)} №{order.id} · "
                    f"{clip(order.name, 16)} · {clip(texts.service_title(order.service), 20)}"
                ),
                callback_data=AdminOrderCB(
                    action="view", order_id=order.id, page=page
                ).pack(),
            )
        )

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(
            InlineKeyboardButton(
                text=texts.BTN_PAGE_PREV,
                callback_data=AdminCB(action="orders", page=page - 1).pack(),
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"· {page}/{max(pages, 1)} ·", callback_data="noop"
        )
    )
    if page < pages:
        nav.append(
            InlineKeyboardButton(
                text=texts.BTN_PAGE_NEXT,
                callback_data=AdminCB(action="orders", page=page + 1).pack(),
            )
        )
    builder.row(*nav)
    builder.row(
        InlineKeyboardButton(
            text=texts.BTN_ADMIN_BACK, callback_data=AdminCB(action="panel").pack()
        )
    )
    return builder.as_markup()


def order_card_kb(order: Order, *, page: int = 1) -> InlineKeyboardMarkup:
    """Карточка заявки: смена статуса на любой другой + возврат к списку."""
    builder = InlineKeyboardBuilder()
    buttons = [
        InlineKeyboardButton(
            text=texts.STATUS_META[status]["button"],
            callback_data=AdminOrderCB(
                action="status", order_id=order.id, status=status, page=page
            ).pack(),
        )
        for status in ALL_STATUSES
        if status != order.status
    ]
    builder.row(*buttons[:2])
    if buttons[2:]:
        builder.row(*buttons[2:])
    builder.row(
        InlineKeyboardButton(
            text=texts.BTN_ADMIN_TO_LIST,
            callback_data=AdminCB(action="orders", page=page).pack(),
        )
    )
    return builder.as_markup()


def new_order_kb(order_id: int) -> InlineKeyboardMarkup:
    """Быстрая смена статуса прямо из уведомления о заявке."""
    builder = InlineKeyboardBuilder()
    for status in ("in_progress", "done", "rejected"):
        builder.button(
            text=texts.STATUS_META[status]["button"],
            callback_data=AdminOrderCB(
                action="status", order_id=order_id, status=status, page=1
            ),
        )
    builder.adjust(1, 2)
    return builder.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_BROADCAST_SEND, callback_data=BroadcastCB(action="send"))
    builder.button(
        text=texts.BTN_BROADCAST_CANCEL, callback_data=BroadcastCB(action="cancel")
    )
    builder.adjust(1, 1)
    return builder.as_markup()
