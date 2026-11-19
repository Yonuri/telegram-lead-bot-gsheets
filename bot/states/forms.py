"""Состояния FSM."""

from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    """Пошаговый сбор заявки."""

    service = State()
    name = State()
    phone = State()
    comment = State()
    confirm = State()


class BroadcastForm(StatesGroup):
    """Мастер рассылки."""

    content = State()
    confirm = State()
