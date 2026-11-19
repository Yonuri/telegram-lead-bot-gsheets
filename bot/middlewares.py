"""Middleware: сессия БД, конфиг, регистрация пользователя."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.database import repo

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД на время обработки апдейта и кладёт её в data."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.sessionmaker() as session:
            data["session"] = session
            # Фабрика нужна фоновым задачам (рассылка): сессия апдейта
            # закрывается сразу после ответа, а задача живёт дольше.
            data["sessionmaker"] = self.sessionmaker
            try:
                return await handler(event, data)
            except Exception:
                await session.rollback()
                raise


class UserSyncMiddleware(BaseMiddleware):
    """Создаёт/обновляет запись пользователя при каждом обращении к боту."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        if tg_user is not None and session is not None and not tg_user.is_bot:
            try:
                data["user"] = await repo.get_or_create_user(
                    session,
                    user_id=tg_user.id,
                    username=tg_user.username,
                    full_name=tg_user.full_name,
                )
            except Exception:  # noqa: BLE001 — не роняем апдейт из-за статистики
                logger.exception("Не удалось сохранить пользователя %s", tg_user.id)
                await session.rollback()
        return await handler(event, data)


class SettingsMiddleware(BaseMiddleware):
    """Кладёт настройки в data, чтобы фильтры и хэндлеры не импортировали их напрямую."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["settings"] = self.settings
        return await handler(event, data)
