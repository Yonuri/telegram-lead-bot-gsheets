"""Клиентские хэндлеры: меню, услуги, FSM-заявка, «Мои заявки»."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.database import repo
from bot.keyboards import user as kb
from bot.keyboards.callbacks import MenuCB, OrderCB, ServiceCB
from bot.services.google_sheets import GoogleSheetsService
from bot.services.orders import submit_order
from bot.states.forms import OrderForm
from bot.utils import esc, fmt_dt, normalize_phone, safe_edit, valid_name

logger = logging.getLogger(__name__)

router = Router(name="user")
# Отдельный роутер: его подключаем последним, чтобы не перехватить чужие колбэки
fallback_router = Router(name="fallback")

COMMENT_LIMIT = 900
MY_ORDERS_LIMIT = 10


# -------------------------------- Главное меню --------------------------------

def _start_text(first_name: str | None) -> str:
    return (
        texts.START.format(name=esc(first_name or "друг"))
        + "\n\n"
        + texts.MENU_PROMPT
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        _start_text(message.from_user.first_name),
        reply_markup=kb.main_menu_kb(),
        disable_web_page_preview=True,
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        _start_text(message.from_user.first_name),
        reply_markup=kb.main_menu_kb(),
        disable_web_page_preview=True,
    )


@router.message(Command("admin"))
async def cmd_admin_denied(message: Message) -> None:
    """Сюда попадают только НЕ-админы: у админов команду забирает админский роутер."""
    await message.answer(texts.ADMIN_ONLY)


@router.callback_query(MenuCB.filter(F.action == "main"))
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(
        callback.message,
        _start_text(callback.from_user.first_name),
        kb.main_menu_kb(),
    )
    await callback.answer()


# ---------------------------------- Услуги ----------------------------------

@router.callback_query(MenuCB.filter(F.action == "services"))
async def cb_services(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, texts.SERVICES_TEXT, kb.services_kb())
    await callback.answer()


# -------------------------------- Мои заявки --------------------------------

@router.callback_query(MenuCB.filter(F.action == "my_orders"))
async def cb_my_orders(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    orders, total = await repo.get_user_orders(
        session, callback.from_user.id, limit=MY_ORDERS_LIMIT
    )

    if not orders:
        await safe_edit(callback.message, texts.MY_ORDERS_EMPTY, kb.back_to_menu_kb())
        await callback.answer()
        return

    body = texts.MY_ORDERS_HEADER + "".join(
        texts.MY_ORDERS_ITEM.format(
            order_id=order.id,
            service=esc(order.service),
            date=fmt_dt(order.created_at, settings.timezone),
            status=esc(texts.status_label(order.status)),
        )
        for order in orders
    )
    body += texts.MY_ORDERS_FOOTER.format(total=total, shown=len(orders))

    await safe_edit(callback.message, body, kb.back_to_menu_kb())
    await callback.answer()


# --------------------------- Отмена в любой момент ---------------------------
# Регистрируется ДО шагов FSM: иначе «запасные» обработчики шагов
# (например, ответ на чужую кнопку) перехватывали бы нажатие «Отмена».

@router.callback_query(OrderCB.filter(F.action == "cancel"))
async def cb_cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, texts.ORDER_FLOW_CANCELLED, kb.back_to_menu_kb())
    await callback.answer()


async def _cancel_flow(message: Message, state: FSMContext) -> None:
    """Сбрасывает сценарий. Вне сценария просто показывает меню."""
    was_in_flow = await state.get_state() is not None
    await state.clear()
    await message.answer(
        texts.ORDER_FLOW_CANCELLED if was_in_flow else texts.MENU_PROMPT,
        reply_markup=kb.REMOVE_KEYBOARD,
    )
    await message.answer(texts.MENU_PROMPT, reply_markup=kb.main_menu_kb())


# ------------------------------ FSM: заявка ------------------------------

async def _ask_service(target: Message) -> None:
    await target.answer(texts.ORDER_START)
    await target.answer(texts.ASK_SERVICE, reply_markup=kb.services_choice_kb())


@router.callback_query(MenuCB.filter(F.action == "new_order"))
async def cb_new_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(OrderForm.service)
    await _ask_service(callback.message)
    await callback.answer()


@router.message(Command("order", "new"))
async def cmd_new_order(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(OrderForm.service)
    await _ask_service(message)


# --- Шаг 1: категория услуги ---

@router.callback_query(StateFilter(OrderForm.service), ServiceCB.filter())
async def step_service(
    callback: CallbackQuery, callback_data: ServiceCB, state: FSMContext
) -> None:
    if callback_data.code not in texts.SERVICES:
        await callback.answer(texts.INVALID_SERVICE, show_alert=True)
        return

    await state.update_data(service=callback_data.code)
    await state.set_state(OrderForm.name)
    await safe_edit(
        callback.message,
        texts.ASK_NAME,
        kb.name_step_kb(callback.from_user.first_name),
    )
    await callback.answer()


@router.callback_query(StateFilter(OrderForm.service))
async def step_service_wrong_button(callback: CallbackQuery) -> None:
    await callback.answer(texts.INVALID_SERVICE, show_alert=True)


# --- Шаг 2: имя ---

async def _accept_name(target: Message, state: FSMContext, name: str, edit: bool = False) -> None:
    await state.update_data(name=name)
    await state.set_state(OrderForm.phone)
    if edit:
        await safe_edit(target, f"👤 Имя: <b>{esc(name)}</b>")
        await target.answer(texts.ASK_PHONE, reply_markup=kb.phone_step_kb())
    else:
        await target.answer(texts.ASK_PHONE, reply_markup=kb.phone_step_kb())


@router.callback_query(StateFilter(OrderForm.name), OrderCB.filter(F.action == "use_profile_name"))
async def step_name_from_profile(callback: CallbackQuery, state: FSMContext) -> None:
    name = valid_name(callback.from_user.first_name)
    if not name:
        await callback.answer(texts.INVALID_NAME, show_alert=True)
        return
    await _accept_name(callback.message, state, name, edit=True)
    await callback.answer()


@router.message(StateFilter(OrderForm.name), F.text)
async def step_name(message: Message, state: FSMContext) -> None:
    if message.text.strip() == texts.BTN_CANCEL:
        await _cancel_flow(message, state)
        return

    name = valid_name(message.text)
    if not name:
        await message.answer(texts.INVALID_NAME)
        return
    await _accept_name(message, state, name)


# --- Шаг 3: телефон ---

async def _accept_phone(target: Message, state: FSMContext, raw_phone: str) -> bool:
    phone = normalize_phone(raw_phone)
    if not phone:
        await target.answer(texts.INVALID_PHONE, reply_markup=kb.phone_step_kb())
        return False
    await state.update_data(phone=phone)
    await state.set_state(OrderForm.comment)
    # Сначала убираем Reply-клавиатуру, затем показываем шаг с inline-кнопками
    await target.answer(texts.PHONE_ACCEPTED, reply_markup=kb.REMOVE_KEYBOARD)
    await target.answer(texts.ASK_COMMENT, reply_markup=kb.comment_step_kb())
    return True


@router.message(StateFilter(OrderForm.phone), F.contact)
async def step_phone_contact(message: Message, state: FSMContext) -> None:
    contact = message.contact
    # Разрешаем только собственный контакт отправителя
    if contact is None or contact.user_id not in (None, message.from_user.id):
        await message.answer(texts.INVALID_PHONE, reply_markup=kb.phone_step_kb())
        return
    await _accept_phone(message, state, contact.phone_number or "")


@router.message(StateFilter(OrderForm.phone), F.text)
async def step_phone_text(message: Message, state: FSMContext) -> None:
    if message.text.strip() == texts.BTN_CANCEL:
        await _cancel_flow(message, state)
        return
    await _accept_phone(message, state, message.text)


# --- Шаг 4: комментарий ---

async def _show_confirmation(target: Message, state: FSMContext, *, edit: bool) -> None:
    data = await state.get_data()
    await state.set_state(OrderForm.confirm)

    text = texts.CONFIRM_TEXT.format(
        service=esc(texts.SERVICES.get(data["service"], data["service"])),
        name=esc(data.get("name", "")),
        phone=esc(data.get("phone", "")),
        comment=esc(data.get("comment") or texts.EMPTY_COMMENT),
    )
    if edit:
        await safe_edit(target, text, kb.confirm_kb())
    else:
        await target.answer(text, reply_markup=kb.confirm_kb())


@router.callback_query(StateFilter(OrderForm.comment), OrderCB.filter(F.action == "skip_comment"))
async def step_comment_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(comment="")
    await _show_confirmation(callback.message, state, edit=True)
    await callback.answer()


@router.message(StateFilter(OrderForm.comment), F.text)
async def step_comment(message: Message, state: FSMContext) -> None:
    if message.text.strip() == texts.BTN_CANCEL:
        await _cancel_flow(message, state)
        return

    text = message.text.strip()
    if len(text) > COMMENT_LIMIT:
        await message.answer(texts.COMMENT_TOO_LONG.format(limit=COMMENT_LIMIT))
        return

    await state.update_data(comment=text)
    await _show_confirmation(message, state, edit=False)


# --- Шаг 5: подтверждение и отправка ---

@router.callback_query(StateFilter(OrderForm.confirm), OrderCB.filter(F.action == "send"))
async def step_send(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    bot: Bot,
    sheets: GoogleSheetsService,
) -> None:
    data = await state.get_data()

    if data.get("submitted"):
        await callback.answer("ℹ️ Заявка уже отправлена.", show_alert=False)
        return

    missing = [key for key in ("service", "name", "phone") if not data.get(key)]
    if missing:
        await callback.answer(texts.ERROR_GENERIC, show_alert=True)
        await state.clear()
        return

    # Замок от повторного нажатия до конца обработки
    await state.update_data(submitted=True)
    await callback.answer("⏳ Отправляю заявку…")

    user = callback.from_user
    order = await submit_order(
        bot=bot,
        session=session,
        settings=settings,
        sheets=sheets,
        user_id=user.id,
        username=user.username,
        service_code=data["service"],
        name=data["name"],
        phone=data["phone"],
        comment=data.get("comment", ""),
    )

    await state.clear()
    await safe_edit(
        callback.message,
        texts.ORDER_SAVED.format(order_id=order.id),
        kb.after_order_kb(),
    )


@router.callback_query(StateFilter(OrderForm.confirm), OrderCB.filter(F.action == "restart"))
async def step_restart(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(OrderForm.service)
    await safe_edit(callback.message, texts.ORDER_FLOW_RESTART)
    await callback.message.answer(texts.ASK_SERVICE, reply_markup=kb.services_choice_kb())
    await callback.answer()


@router.callback_query(OrderForm.confirm)
async def step_confirm_unknown(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Прерывает любой сценарий и возвращает в меню."""
    await _cancel_flow(message, state)


# -----------------– Запасные обработчики (отдельный роутер) ------------------
# Регистрируется ПОСЛЕДНИМ: срабатывает только там, где конкретный хэндлер
# ничего не нашёл.

@fallback_router.message(StateFilter(default_state), F.text)
async def echo_unknown(message: Message) -> None:
    if (message.text or "").strip().startswith("/"):
        return
    await message.answer(texts.UNKNOWN_COMMAND, reply_markup=kb.main_menu_kb())


@fallback_router.callback_query(StateFilter(default_state))
async def unknown_callback(callback: CallbackQuery) -> None:
    """Гасим «часики» на устаревших инлайн-кнопках."""
    await callback.answer("Кнопка устарела. Откройте /start", show_alert=False)
