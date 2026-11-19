"""Фильтр «только для администраторов»."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.config import Settings


class IsAdmin(BaseFilter):
    """Пропускает событие, если его отправитель есть в ADMIN_IDS."""

    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in settings.admin_id_list)
