"""Клавиатуры клиентской части."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts
from bot.keyboards.callbacks import MenuCB, OrderCB, ServiceCB

# Убирает Reply-клавиатуру после ввода телефона
REMOVE_KEYBOARD = ReplyKeyboardRemove()


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_NEW_ORDER, callback_data=MenuCB(action="new_order"))
    builder.button(text=texts.BTN_SERVICES, callback_data=MenuCB(action="services"))
    builder.button(text=texts.BTN_MY_ORDERS, callback_data=MenuCB(action="my_orders"))
    builder.adjust(1, 2)
    return builder.as_markup()


def services_kb() -> InlineKeyboardMarkup:
    """Экран «Услуги и цены»."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CONFIRM_ORDER, callback_data=MenuCB(action="new_order"))
    builder.button(text=texts.BTN_BACK_TO_MENU, callback_data=MenuCB(action="main"))
    builder.adjust(1, 1)
    return builder.as_markup()


def services_choice_kb() -> InlineKeyboardMarkup:
    """Шаг 1 FSM: категория услуги."""
    builder = InlineKeyboardBuilder()
    for code, title in texts.SERVICES.items():
        builder.button(text=title, callback_data=ServiceCB(code=code))
    builder.button(text=texts.BTN_CANCEL, callback_data=OrderCB(action="cancel"))
    builder.adjust(1, 1, 1, 1, 1)
    return builder.as_markup()


def name_step_kb(profile_name: str | None) -> InlineKeyboardMarkup:
    """Шаг 2 FSM: подставить имя из профиля + отмена."""
    builder = InlineKeyboardBuilder()
    name = (profile_name or "").strip()
    if name:
        builder.button(
            text=texts.BTN_USE_PROFILE_NAME.format(name=name[:32]),
            callback_data=OrderCB(action="use_profile_name"),
        )
    builder.button(text=texts.BTN_CANCEL, callback_data=OrderCB(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


def phone_step_kb() -> ReplyKeyboardMarkup:
    """Шаг 3 FSM: Reply-кнопка «Поделиться контактом»."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_SHARE_CONTACT, request_contact=True)],
            [KeyboardButton(text=texts.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=texts.PHONE_PLACEHOLDER,
    )


def comment_step_kb() -> InlineKeyboardMarkup:
    """Шаг 4 FSM: пропустить комментарий + отмена."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_SKIP, callback_data=OrderCB(action="skip_comment"))
    builder.button(text=texts.BTN_CANCEL, callback_data=OrderCB(action="cancel"))
    builder.adjust(2)
    return builder.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    """Шаг 5 FSM: отправка / заполнить заново."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_SEND, callback_data=OrderCB(action="send"))
    builder.button(text=texts.BTN_FILL_AGAIN, callback_data=OrderCB(action="restart"))
    builder.button(text=texts.BTN_CANCEL, callback_data=OrderCB(action="cancel"))
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_BACK_TO_MENU, callback_data=MenuCB(action="main"))
    return builder.as_markup()


def after_order_kb() -> InlineKeyboardMarkup:
    """Готово: посмотреть заявки или в меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_MY_ORDERS, callback_data=MenuCB(action="my_orders"))
    builder.button(text=texts.BTN_BACK_TO_MENU, callback_data=MenuCB(action="main"))
    builder.adjust(2)
    return builder.as_markup()
