"""Инициализация движка БД и фабрики сессий."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.database.models import Base

logger = logging.getLogger(__name__)


def _ensure_sqlite_dir(url: str) -> None:
    """Создаёт каталог для файла SQLite, если он ещё не существует."""
    if "///" not in url:
        return
    raw_path = url.split("///", 1)[1].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine(url: str) -> AsyncEngine:
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        _ensure_sqlite_dir(url)

    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"timeout": 30} if is_sqlite else {},
    )

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Создаёт таблицы при первом запуске (идемпотентно)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Схема базы данных готова")
