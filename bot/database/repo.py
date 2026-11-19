"""Все запросы к базе данных в одном месте."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ALL_STATUSES, STATUS_NEW, Order, User
from bot.utils import local_day_start_utc, utcnow


# --------------------------------- Пользователи ---------------------------------

async def get_or_create_user(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None,
    full_name: str | None,
) -> User:
    """Возвращает пользователя, создавая запись при первом обращении."""
    user = await session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            username=username,
            full_name=full_name or "",
        )
        session.add(user)
    else:
        user.username = username
        user.full_name = full_name or user.full_name
        user.is_blocked = False
        user.last_seen_at = utcnow()
    await session.commit()
    await session.refresh(user)
    return user


async def mark_user_blocked(session: AsyncSession, user_id: int, blocked: bool = True) -> None:
    """Помечает пользователя как заблокировавшего бота (или снимает пометку)."""
    await session.execute(
        update(User).where(User.id == user_id).values(is_blocked=blocked)
    )
    await session.commit()


async def count_users(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(User)) or 0)


async def get_broadcast_recipients(session: AsyncSession) -> list[int]:
    """ID всех пользователей, которым ещё можно писать."""
    result = await session.scalars(
        select(User.id).where(User.is_blocked.is_(False)).order_by(User.id)
    )
    return list(result.all())


# ----------------------------------- Заявки -----------------------------------

async def create_order(
    session: AsyncSession,
    *,
    user_id: int,
    username: str | None,
    service: str,
    name: str,
    phone: str,
    comment: str = "",
) -> Order:
    order = Order(
        user_id=user_id,
        username=username,
        service=service,
        name=name,
        phone=phone,
        comment=comment,
        status=STATUS_NEW,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_order(session: AsyncSession, order_id: int) -> Order | None:
    return await session.get(Order, order_id)


async def get_user_orders(
    session: AsyncSession, user_id: int, limit: int = 10
) -> tuple[list[Order], int]:
    """Последние заявки клиента и их общее количество."""
    total = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.user_id == user_id)
        )
        or 0
    )
    result = await session.scalars(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    )
    return list(result.all()), total


async def get_orders_page(
    session: AsyncSession, *, page: int, per_page: int = 5
) -> tuple[list[Order], int, int]:
    """Заявки для админки: (список, текущая страница, всего страниц)."""
    total = int(await session.scalar(select(func.count()).select_from(Order)) or 0)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), pages)
    result = await session.scalars(
        select(Order)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.all()), page, pages


async def set_order_status(session: AsyncSession, order: Order, status: str) -> Order:
    order.status = status
    order.updated_at = utcnow()
    await session.commit()
    await session.refresh(order)
    return order


async def set_order_sheet_row(
    session: AsyncSession, order: Order, row_number: int | None
) -> None:
    order.sheet_row = row_number
    await session.commit()


# --------------------------------- Статистика ---------------------------------

@dataclass(slots=True)
class Stats:
    users_total: int = 0
    orders_total: int = 0
    orders_today: int = 0
    orders_week: int = 0
    by_status: dict[str, int] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "Stats":
        return cls(by_status={status: 0 for status in ALL_STATUSES})


async def get_stats(session: AsyncSession, tz: str) -> Stats:
    users_total = await count_users(session)
    orders_total = int(await session.scalar(select(func.count()).select_from(Order)) or 0)

    today_start = local_day_start_utc(tz)
    week_start = local_day_start_utc(tz, days_ago=6)

    orders_today = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.created_at >= today_start)
        )
        or 0
    )
    orders_week = int(
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.created_at >= week_start)
        )
        or 0
    )

    rows = await session.execute(select(Order.status, func.count()).group_by(Order.status))
    by_status = {status: 0 for status in ALL_STATUSES}
    for status, count in rows.all():
        by_status[str(status)] = int(count)

    return Stats(
        users_total=users_total,
        orders_total=orders_total,
        orders_today=orders_today,
        orders_week=orders_week,
        by_status=by_status,
    )
