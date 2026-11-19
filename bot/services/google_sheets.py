"""Синхронизация заявок с Google Таблицами.

gspread работает синхронно, поэтому все сетевые вызовы уходят в пул потоков
через asyncio.to_thread — event loop бота не блокируется.

Сервис не выпускает наружу «сырых» исключений Google: любая проблема
превращается в SheetsError с понятным администратору текстом. Заявка к этому
моменту уже сохранена в БД, поэтому данные клиента не теряются.
"""

from __future__ import annotations

import asyncio
import logging
import time

from google.oauth2.service_account import Credentials
from gspread import Client, Spreadsheet, Worksheet
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

from bot.config import Settings
from bot.database.models import Order
from bot.texts import status_title
from bot.utils import fmt_dt

logger = logging.getLogger(__name__)

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
)

HEADERS = [
    "ID заявки",
    "Дата и время",
    "Telegram ID",
    "Username",
    "Имя",
    "Телефон",
    "Услуга",
    "Комментарий",
    "Статус",
]

STATUS_COLUMN_INDEX = len(HEADERS)  # 9 -> колонка I
REQUEST_TIMEOUT = 30.0
# Сколько секунд считать результат health_check актуальным
HEALTH_TTL = 60.0


class SheetsError(RuntimeError):
    """Ошибка синхронизации, пригодная для показа администратору."""


class GoogleSheetsService:
    """Асинхронная обёртка над gspread с ленивой инициализацией и кэшем листа."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._worksheet: Worksheet | None = None
        self._lock = asyncio.Lock()
        # Кэш результата health_check: экран статистики открывают часто,
        # а каждый сетевой вызов держит общий лок и задерживает запись заявок.
        self._health_ok: bool | None = None
        self._health_at: float = 0.0

    # ------------------------------- публичное -------------------------------

    @property
    def enabled(self) -> bool:
        """Настроена ли интеграция (ссылка на таблицу + ключ сервисного аккаунта)."""
        return self._settings.sheets_enabled

    @property
    def url(self) -> str:
        sheet_id = self._settings.spreadsheet_id
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""

    async def append_order(self, order: Order) -> int:
        """Добавляет строку заявки. Возвращает номер строки (0 — если не удалось определить)."""
        self._ensure_enabled()
        try:
            return await self._run(self._append_sync, order)
        except SheetsError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Не удалось добавить заявку №%s в таблицу", order.id)
            raise SheetsError(humanize_error(exc)) from exc

    async def update_status(self, order: Order, sheet_row: int | None = None) -> None:
        """Обновляет статус в соответствующей строке таблицы."""
        self._ensure_enabled()
        try:
            await self._run(self._update_status_sync, order, sheet_row)
        except SheetsError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Не удалось обновить статус заявки №%s", order.id)
            raise SheetsError(humanize_error(exc)) from exc

    async def health_check(self, *, force: bool = False) -> bool:
        """Проверка доступа к таблице (для экрана статистики).

        Результат кэшируется на HEALTH_TTL секунд: экран статистики можно
        открывать сколько угодно раз, а реальный запрос к Google уйдёт
        не чаще, чем раз в HEALTH_TTL.
        """
        if not self.enabled:
            return False

        now = time.monotonic()
        if not force and self._health_ok is not None and now - self._health_at < HEALTH_TTL:
            return self._health_ok

        try:
            await self._run(self._worksheet_sync)
            self._health_ok = True
        except SheetsError as exc:
            # Известная проблема конфигурации: полный трейсбек тут только шумит
            logger.warning("Google Таблица недоступна: %s", exc)
            self._health_ok = False
        except Exception:  # noqa: BLE001
            logger.warning("Проверка доступа к Google Таблице не прошла", exc_info=True)
            self._health_ok = False

        self._health_at = time.monotonic()
        return self._health_ok

    async def reset(self) -> None:
        """Сбрасывает закэшированный лист и результат health_check."""
        self._worksheet = None
        self._health_ok = None
        self._health_at = 0.0

    # ------------------------------ внутреннее ------------------------------

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise SheetsError(
                "Google Таблица не настроена: проверьте GOOGLE_SHEET_URL, "
                "GOOGLE_CREDENTIALS_PATH в .env и доступ сервисного аккаунта к таблице."
            )

    async def _run(self, func, *args):
        """Выполняет блокирующую операцию в отдельном потоке под общим локом."""
        async with self._lock:
            return await asyncio.wait_for(
                asyncio.to_thread(func, *args), timeout=REQUEST_TIMEOUT
            )

    def _worksheet_sync(self) -> Worksheet:
        if self._worksheet is not None:
            return self._worksheet

        sheet_id = self._settings.spreadsheet_id
        if not sheet_id:
            raise SheetsError(
                "Не удалось извлечь ID таблицы из GOOGLE_SHEET_URL. "
                "Нужна ссылка вида https://docs.google.com/spreadsheets/d/<ID>/edit"
            )

        credentials = self._load_credentials()
        try:
            client = Client(auth=credentials)
            spreadsheet = client.open_by_key(sheet_id)
        except SpreadsheetNotFound as exc:
            raise SheetsError(
                "Таблица не найдена. Проверьте, что сервисному аккаунту выдан "
                "доступ «Редактор» к этой таблице."
            ) from exc

        worksheet = self._pick_worksheet(spreadsheet)
        self._ensure_header(worksheet)
        self._worksheet = worksheet
        logger.info("Google Sheets: используется лист «%s»", worksheet.title)
        return worksheet

    def _load_credentials(self) -> Credentials:
        try:
            info = self._settings.credentials_info()
        except ValueError as exc:
            raise SheetsError(str(exc)) from exc
        if not info:
            raise SheetsError(
                "Файл ключей сервисного аккаунта не найден "
                f"({self._settings.google_credentials_path}). Скачайте JSON в Google Cloud "
                "и положите его рядом с ботом."
            )
        try:
            return Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as exc:  # noqa: BLE001
            raise SheetsError(
                f"Не удалось прочитать ключ сервисного аккаунта: {exc}"
            ) from exc

    def _pick_worksheet(self, spreadsheet: Spreadsheet) -> Worksheet:
        """Лист выбирается по имени из настроек → по gid из ссылки → иначе первый."""
        name = (self._settings.google_worksheet_name or "").strip()
        if name:
            try:
                return spreadsheet.worksheet(name)
            except WorksheetNotFound:
                logger.warning("Лист «%s» не найден — беру лист по умолчанию", name)

        gid = self._settings.worksheet_gid
        if gid is not None:
            try:
                worksheet = spreadsheet.get_worksheet_by_id(gid)
                if worksheet is not None:
                    return worksheet
                logger.warning("Лист с gid=%s не найден — беру первый лист", gid)
            except Exception:  # noqa: BLE001
                logger.warning("Не удалось открыть лист gid=%s", gid, exc_info=True)

        return spreadsheet.sheet1

    def _ensure_header(self, worksheet: Worksheet) -> None:
        """Создаёт шапку, если лист пуст; иначе проверяет, что писать можно."""
        try:
            first_row = worksheet.row_values(1)
        except APIError as exc:
            raise SheetsError(humanize_error(exc)) from exc

        if [cell.strip() for cell in first_row[: len(HEADERS)]] == HEADERS:
            return

        if any(cell.strip() for cell in first_row):
            logger.warning(
                "В первой строке листа «%s» нестандартные заголовки — данные пишу ниже",
                worksheet.title,
            )
            return

        worksheet.update([HEADERS], "A1:I1")
        logger.info("Google Sheets: создана строка заголовков")
        try:
            worksheet.format(
                "A1:I1",
                {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.93, "green": 0.95, "blue": 1.0},
                },
            )
            worksheet.freeze(rows=1)
        except Exception:  # noqa: BLE001 — оформление не критично
            logger.debug("Не удалось оформить шапку", exc_info=True)

    def _append_sync(self, order: Order) -> int:
        worksheet = self._worksheet_sync()
        result = worksheet.append_row(
            self._build_row(order),
            value_input_option="USER_ENTERED",
            insert_data_option="INSERT_ROWS",
        )
        # Ответ вида {'updates': {'updatedRange': "'Лист'!A42:I42", ...}}
        updated_range = ""
        if isinstance(result, dict):
            updated_range = (result.get("updates") or {}).get("updatedRange") or ""
        if "!" in updated_range:
            start_cell = updated_range.split("!", 1)[1].split(":", 1)[0]
            digits = "".join(ch for ch in start_cell if ch.isdigit())
            if digits:
                return int(digits)
        return 0

    def _update_status_sync(self, order: Order, sheet_row: int | None) -> None:
        worksheet = self._worksheet_sync()
        row = sheet_row or self._find_row_by_order_id(worksheet, order.id)

        # Номер строки мог устареть: пользователь мог отсортировать лист
        # или удалить строки, и тогда статус записался бы в ЧУЖУЮ заявку.
        # Поэтому сверяем ID в целевой строке и при расхождении ищем заново.
        if row and not self._row_belongs_to(worksheet, row, order.id):
            logger.warning(
                "Заявка №%s больше не в строке %s (лист изменился) — ищу заново",
                order.id,
                row,
            )
            row = self._find_row_by_order_id(worksheet, order.id)

        if not row:
            logger.warning(
                "Заявка №%s не найдена в таблице — дописываю строку заново", order.id
            )
            self._append_sync(order)
            return

        cell = f"{column_letter(STATUS_COLUMN_INDEX)}{row}"
        worksheet.update(
            [[status_title(order.status)]], cell, value_input_option="USER_ENTERED"
        )

    def _row_belongs_to(self, worksheet: Worksheet, row: int, order_id: int) -> bool:
        """Проверяет, что в строке `row` колонки A лежит ID этой заявки."""
        try:
            values = worksheet.row_values(row)
        except APIError as exc:
            raise SheetsError(humanize_error(exc)) from exc
        if not values:
            return False
        return str(values[0]).strip() == str(order_id)

    def _find_row_by_order_id(self, worksheet: Worksheet, order_id: int) -> int | None:
        try:
            column = worksheet.col_values(1)
        except APIError as exc:
            raise SheetsError(humanize_error(exc)) from exc
        target = str(order_id)
        for index, value in enumerate(column, start=1):
            if str(value).strip() == target:
                return index
        return None

    def _build_row(self, order: Order) -> list[str]:
        return [
            str(order.id),
            fmt_dt(order.created_at, self._settings.timezone, "%d.%m.%Y %H:%M:%S"),
            str(order.user_id),
            f"@{order.username}" if order.username else "",
            order.name,
            order.phone,
            order.service,
            order.comment or "",
            status_title(order.status),
        ]


def column_letter(index: int) -> str:
    """1 -> A, 9 -> I, 27 -> AA."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def humanize_error(exc: BaseException) -> str:
    """Короткое и понятное администратору описание ошибки Google API."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "Google API не ответил вовремя (таймаут 30 с)."

    text = (str(exc) or exc.__class__.__name__).strip()
    lowered = text.lower()

    if "403" in text or "permission" in lowered or "forbidden" in lowered:
        return "Нет доступа к таблице: выдайте сервисному аккаунту роль «Редактор»."
    if "404" in text or "not found" in lowered:
        return "Таблица или лист не найдены: проверьте GOOGLE_SHEET_URL."
    if "429" in text or "quota" in lowered:
        return "Превышен лимит запросов Google API — повторите позже."
    if "api has not been used" in lowered or "disabled" in lowered:
        return "В проекте Google Cloud не включены Google Sheets API и Google Drive API."
    if "invalid_grant" in lowered or "credentials" in lowered:
        return "Проблема с ключом сервисного аккаунта (credentials.json)."
    return text[:300]
