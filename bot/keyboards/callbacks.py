"""Колбэк-фабрики для инлайн-кнопок."""

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="menu"):
    """Главное меню клиента."""

    action: str  # main | services | my_orders | new_order


class ServiceCB(CallbackData, prefix="svc"):
    """Выбор услуги на шаге FSM."""

    code: str


class OrderCB(CallbackData, prefix="ord"):
    """Кнопки внутри сценария заявки."""

    action: str  # use_profile_name | skip_comment | send | restart | cancel


class AdminCB(CallbackData, prefix="adm"):
    """Разделы админ-панели."""

    action: str  # panel | stats | orders | broadcast | sheet | noop
    page: int = 1


class AdminOrderCB(CallbackData, prefix="ao"):
    """Действия с заявкой в админке."""

    action: str  # view | status
    order_id: int = 0
    status: str = ""
    page: int = 1


class BroadcastCB(CallbackData, prefix="bcast"):
    """Подтверждение рассылки."""

    action: str  # send | cancel
