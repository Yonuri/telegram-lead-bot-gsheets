"""Настройки приложения из .env (pydantic-settings) и разбор ссылок Google."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SPREADSHEET_KEY_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})")
_GID_RE = re.compile(r"[#&?]gid=(\d+)")


class Settings(BaseSettings):
    """Конфигурация бота. Все значения читаются из окружения или файла .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Telegram ----
    bot_token: str
    # Список ID администраторов через запятую: "123456789,987654321"
    admin_ids: str = ""

    # ---- Google Sheets ----
    google_sheet_url: str = ""
    google_credentials_path: str = "credentials.json"
    # Необязательно: JSON-ключ сервисного аккаунта одной строкой (удобно в Docker)
    google_credentials_json: str = ""
    # Необязательно: имя листа. Если пусто — берётся лист по gid из ссылки
    # либо первый лист таблицы.
    google_worksheet_name: str = ""

    # ---- Прочее ----
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    timezone: str = "Europe/Moscow"
    log_level: str = "INFO"
    orders_per_page: int = 5
    broadcast_delay: float = 0.05

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _clean_admin_ids(cls, value: object) -> str:
        """Поддерживаем форматы «123,456», «123 456» и «[123, 456]»."""
        if value is None:
            return ""
        text = str(value).strip()
        return text.strip("[]").replace(";", ",")

    @field_validator("bot_token", mode="before")
    @classmethod
    def _strip_token(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("orders_per_page")
    @classmethod
    def _clamp_page_size(cls, value: int) -> int:
        return max(1, min(int(value), 20))

    @field_validator("broadcast_delay")
    @classmethod
    def _clamp_delay(cls, value: float) -> float:
        return max(0.0, min(float(value), 2.0))

    # ------------------------------ вычисляемые ------------------------------

    @property
    def admin_id_list(self) -> list[int]:
        ids: list[int] = []
        for chunk in re.split(r"[,\s]+", self.admin_ids):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                value = int(chunk)
            except ValueError:
                continue
            if value not in ids:
                ids.append(value)
        return ids

    @property
    def credentials_path(self) -> Path:
        return Path(self.google_credentials_path).expanduser()

    @property
    def spreadsheet_id(self) -> str | None:
        """ID таблицы из ссылки GOOGLE_SHEET_URL (или сам ID, если он передан как есть)."""
        url = (self.google_sheet_url or "").strip()
        if not url:
            return None
        match = _SPREADSHEET_KEY_RE.search(url)
        if match:
            return match.group(1)
        if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", url):
            return url
        return None

    @property
    def worksheet_gid(self) -> int | None:
        match = _GID_RE.search(self.google_sheet_url or "")
        return int(match.group(1)) if match else None

    @property
    def sheets_enabled(self) -> bool:
        has_credentials = (
            bool(self.google_credentials_json.strip()) or self.credentials_path.is_file()
        )
        return bool(self.spreadsheet_id) and has_credentials

    def log_level_int(self) -> int:
        import logging

        level = {"CRITICAL": 50, "ERROR": 40, "WARNING": 30, "INFO": 20, "DEBUG": 10}
        return level.get(self.log_level.upper(), logging.INFO)

    def credentials_info(self) -> dict | None:
        """Содержимое JSON-ключа сервисного аккаунта."""
        import json

        if self.google_credentials_json.strip():
            try:
                return json.loads(self.google_credentials_json)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "GOOGLE_CREDENTIALS_JSON содержит некорректный JSON"
                ) from exc

        path = self.credentials_path
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Не удалось прочитать {path}: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Единый экземпляр настроек на процесс."""
    return Settings()  # type: ignore[call-arg]
