"""Мелкие утилиты: даты, телефоны, текст, безопасное редактирование сообщений."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"\D")
_PHONE_ALLOWED_RE = re.compile(r"^\+?[\d\s()\-]+$")
_NAME_FORBIDDEN_RE = re.compile(r"[<>{}\[\]/\\|@#$%^*_=+~`\"]")

_TZ_CACHE: dict[str, ZoneInfo] = {}
# Последний рубеж: если в системе нет базы часовых поясов, держим фиксированный UTC
_FIXED_UTC = timezone.utc


def _has_tzdata() -> bool:
    try:
        ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


_UTC_FALLBACK: tzinfo = ZoneInfo("UTC") if _has_tzdata() else _FIXED_UTC


# ------------------------------- Часовой пояс -------------------------------

def get_tz(name: str | tzinfo) -> tzinfo:
    """Часовой пояс по имени. Никогда не падает: при проблемах отдаёт UTC."""
    if not isinstance(name, str):
        return name
    cached = _TZ_CACHE.get(name)
    if cached is not None:
        return cached
    try:
        zone: tzinfo = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        logger.warning(
            "Часовой пояс %r недоступен (на Windows нужен пакет tzdata) — используется UTC",
            name,
        )
        zone = _UTC_FALLBACK
    _TZ_CACHE[name] = zone  # type: ignore[assignment]
    return zone


def utcnow() -> datetime:
    """Текущее время UTC без tzinfo — в таком виде оно хранится в SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(value: datetime, tz: str | tzinfo) -> datetime:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(get_tz(tz))


def fmt_dt(
    value: datetime | None, tz: str | ZoneInfo, fmt: str = "%d.%m.%Y %H:%M"
) -> str:
    if value is None:
        return "—"
    return to_local(value, tz).strftime(fmt)


def local_day_start_utc(tz: str | ZoneInfo, days_ago: int = 0) -> datetime:
    """Начало локальных суток (со сдвигом на N дней) в naive-UTC.

    days_ago=-1 даёт начало завтрашних суток — удобно как верхняя граница «сегодня».
    """
    zone = get_tz(tz)
    start_local = (datetime.now(zone) - timedelta(days=days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start_local.astimezone(timezone.utc).replace(tzinfo=None)


# --------------------------------- Телефон ---------------------------------

def normalize_phone(raw: str | None) -> str | None:
    """'+7 (999) 123-45-67' -> '+79991234567'. None — номер не прошёл валидацию."""
    if not raw:
        return None
    text = raw.strip()
    if not _PHONE_ALLOWED_RE.match(text):
        return None
    digits = _DIGITS_RE.sub("", text)
    if not 10 <= len(digits) <= 15:
        return None
    if len(digits) == 11 and digits.startswith("8"):  # 8XXXXXXXXXX -> +7XXXXXXXXXX
        digits = "7" + digits[1:]
    return "+" + digits


def is_valid_phone(raw: str | None) -> bool:
    return normalize_phone(raw) is not None


def format_phone(raw: str | None) -> str:
    """Человекочитаемый номер: '+79991234567' -> '+7 999 123-45-67'."""
    if not raw:
        return "—"
    digits = _DIGITS_RE.sub("", raw)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        d = digits[1:]
        return f"+7 {d[0:3]} {d[3:6]}-{d[6:8]}-{d[8:10]}"
    if len(digits) == 10:
        return f"{digits[0:3]} {digits[3:6]}-{digits[6:8]}-{digits[8:10]}"
    return raw


# ---------------------------------- Текст ----------------------------------

def esc(value: object) -> str:
    """Экранирование под parse_mode=HTML."""
    return html.escape(str(value if value is not None else ""), quote=False)


def clip(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def valid_name(raw: str | None) -> str | None:
    """Проверка и нормализация имени: 2–64 символа, без служебных знаков."""
    if not raw:
        return None
    name = re.sub(r"\s+", " ", raw).strip()
    if not 2 <= len(name) <= 64:
        return None
    if _NAME_FORBIDDEN_RE.search(name):
        return None
    if not re.search(r"[^\W\d_]", name, re.UNICODE):  # должна быть хотя бы одна буква
        return None
    return name


def plural_ru(number: int, one: str, few: str, many: str) -> str:
    """Склонение: 1 заявка / 2 заявки / 5 заявок."""
    n = abs(int(number)) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def safe_username(username: str | None) -> str:
    return f"@{username}" if username else "—"


# -------------------------------- Telegram --------------------------------

async def safe_edit(message: Message, text: str, reply_markup=None) -> None:
    """Редактирует сообщение, не падая на «message is not modified» и фото-сообщениях."""
    try:
        await message.edit_text(
            text, reply_markup=reply_markup, disable_web_page_preview=True
        )
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if "message is not modified" in error:
            return
        # Фото/видео-сообщение отредактировать нельзя — отправляем новое
        await message.answer(text, reply_markup=reply_markup)
