"""Модели SQLAlchemy: пользователи и заявки."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot.utils import utcnow


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


# Ключи статусов заявки (хранятся в БД и в callback_data)
STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_REJECTED = "rejected"

ALL_STATUSES: tuple[str, ...] = (
    STATUS_NEW,
    STATUS_IN_PROGRESS,
    STATUS_DONE,
    STATUS_REJECTED,
)


class User(Base):
    """Клиент бота."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), default="")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    orders: Mapped[list["Order"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        # Заявки пользователя в коде не читаются; явная ошибка лучше
        # «тихой» ленивой подгрузки в async-контексте.
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} username={self.username!r}>"


class Order(Base):
    """Заявка клиента."""

    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Дублируем username на момент заявки: профиль клиента мог измениться
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_NEW, nullable=False, index=True
    )
    # Номер строки в Google Таблице, чтобы менять статус точечно
    sheet_row: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="orders", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order id={self.id} status={self.status!r}>"
