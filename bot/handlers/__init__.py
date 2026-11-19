"""Хэндлеры: клиентские и админские."""

from aiogram import Router

from bot.handlers.admin import router as admin_router
from bot.handlers.user import fallback_router
from bot.handlers.user import router as user_router


def get_routers() -> tuple[Router, ...]:
    """Порядок регистрации важен: админка → клиент → запасной.

    Запасной роутер идёт последним, поэтому он ловит только те события,
    которые не забрал ни один конкретный хэндлер (например, нажатие
    устаревшей инлайн-кнопки) — и гасит «часики» у клиента.
    """
    return (admin_router, user_router, fallback_router)


__all__ = ["admin_router", "fallback_router", "get_routers", "user_router"]
