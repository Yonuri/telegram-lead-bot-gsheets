"""Тест слоя Google Sheets на фейковом gspread (без сети).

Проверяем: шапка, append строки, номер строки из ответа, точечное обновление
статуса, поиск строки по ID и восстановление удалённой строки.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:TEST")

from bot.config import Settings  # noqa: E402
from bot.database.models import Order  # noqa: E402
from bot.services import google_sheets as gs  # noqa: E402

FAILS: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"  [{'OK  ' if condition else 'FAIL'}] {message}")
    if not condition:
        FAILS.append(message)


class FakeWorksheet:
    def __init__(self) -> None:
        self.id = 0
        self.title = "Sheet1"
        self.rows: list[list[str]] = []
        self.updates: list[tuple[list[list[str]], str]] = []
        self.formatted: list[str] = []
        self.frozen = 0

    def row_values(self, row: int):
        if 0 <= row - 1 < len(self.rows):
            return list(self.rows[row - 1])
        return []

    def col_values(self, col: int):
        return [r[col - 1] for r in self.rows if len(r) >= col]

    def update(self, values, cell: str, value_input_option=None):
        self.updates.append((values, cell))
        if cell == "A1:I1":
            if self.rows:
                self.rows[0] = list(values[0])
            else:
                self.rows.append(list(values[0]))
        else:
            import re

            match = re.match(r"^([A-Z]+)(\d+)$", cell)
            if match:
                row_idx = int(match.group(2)) - 1
                while len(self.rows) <= row_idx:
                    self.rows.append([""] * 9)
                self.rows[row_idx][8] = values[0][0]

    def append_row(self, row, value_input_option=None, insert_data_option=None):
        self.rows.append(list(row))
        number = len(self.rows)
        return {"updates": {"updatedRange": f"'{self.title}'!A{number}:I{number}"}}

    def format(self, cell_range, fmt):
        self.formatted.append(cell_range)

    def freeze(self, rows: int = 0):
        self.frozen = rows


class FakeSpreadsheet:
    def __init__(self) -> None:
        self._ws = FakeWorksheet()
        self.sheet1 = self._ws

    def worksheet(self, name):
        raise gs.WorksheetNotFound(name)

    def get_worksheet_by_id(self, gid):
        return self._ws


def make_order(**kw) -> Order:
    base = dict(
        id=17,
        user_id=555,
        username="ivan",
        name="Иван",
        phone="+79991234567",
        service="Разработка бота",
        comment="Нужен бот",
        status="new",
        sheet_row=None,
        created_at=datetime(2025, 2, 5, 11, 30, 0),
        updated_at=datetime(2025, 2, 5, 11, 30, 0),
    )
    base.update(kw)
    return Order(**base)


async def main() -> None:
    # _env_file=None: тест не должен подхватывать реальный .env проекта
    settings = Settings(
        _env_file=None,
        bot_token="123456:TEST",
        google_sheet_url="https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890/edit",
        google_credentials_json='{"type":"service_account"}',
    )
    service = gs.GoogleSheetsService(settings)
    sheet = FakeSpreadsheet()

    with patch.object(gs, "Client") as client_cls, patch.object(
        gs.Credentials, "from_service_account_info", return_value=object()
    ):
        client_cls.return_value.open_by_key.return_value = sheet

        print("1. Первая запись создаёт шапку и строку")
        order = make_order()
        row = await service.append_order(order)
        check(row == 2, f"номер строки из ответа API: {row}")
        check(sheet._ws.rows[0] == gs.HEADERS, "шапка создана")
        check("A1:I1" in sheet._ws.formatted, "шапка отформатирована")
        check(sheet._ws.frozen == 1, "первая строка закреплена")

        data_row = sheet._ws.rows[1]
        check(data_row[0] == "17", f"ID заявки: {data_row[0]}")
        check(data_row[2] == "555", f"Telegram ID: {data_row[2]}")
        check(data_row[3] == "@ivan", f"Username: {data_row[3]}")
        check(data_row[5] == "+79991234567", f"Телефон: {data_row[5]}")
        check(data_row[8] == "Новая", f"Статус: {data_row[8]}")
        check(len(data_row) == 9, f"колонок в строке: {len(data_row)}")
        check(data_row[1].endswith("14:30:00"), f"дата в локальном времени: {data_row[1]}")

        print("2. Смена статуса обновляет конкретную ячейку")
        order.status = "in_progress"
        await service.update_status(order, sheet_row=2)
        values, cell = sheet._ws.updates[-1]
        check(cell == "I2", f"адрес ячейки: {cell}")
        check(values == [["В работе"]], f"значение: {values}")

        print("3. Без известного номера строка ищется по ID")
        order.status = "done"
        await service.update_status(order, sheet_row=None)
        values, cell = sheet._ws.updates[-1]
        check(cell == "I2" and values == [["Завершена"]], "статус найден по ID и обновлён")

        print("4. Удалённая строка восстанавливается")
        sheet._ws.rows = [gs.HEADERS]  # кто-то вручную очистил таблицу
        sheet._ws.updates.clear()
        await service.update_status(order, sheet_row=None)
        check(len(sheet._ws.rows) == 2, "строка дописана заново")
        check(sheet._ws.rows[1][0] == "17", "восстановлена нужная заявка")

        print("5. Повторный вызов не пересоздаёт шапку")
        sheet._ws.updates.clear()
        await service.append_order(make_order(id=18, name="Мария"))
        check(
            not any(cell == "A1:I1" for _, cell in sheet._ws.updates),
            "шапка не дублируется",
        )
        check(len(sheet._ws.rows) == 3, f"строк в листе: {len(sheet._ws.rows)}")

        print("5б. Устаревший номер строки не портит чужую заявку")
        # Пользователь отсортировал лист вручную: заявки поменялись местами
        sheet._ws.rows = [gs.HEADERS, list(sheet._ws.rows[2]), list(sheet._ws.rows[1])]
        stale = make_order(id=17, status="done")
        # В БД у заявки 17 записан sheet_row=2, но там теперь заявка 18
        await service.update_status(stale, sheet_row=2)
        by_id = {row[0]: row[8] for row in sheet._ws.rows[1:]}
        check(by_id["17"] == "Завершена", f"статус заявки 17 обновлён: {by_id['17']}")
        check(by_id["18"] == "Новая", f"заявка 18 не тронута: {by_id['18']}")
        check(len(sheet._ws.rows) == 3, "дубль строки не создан")

    print("6. Расшифровка ошибок Google")
    check("Редактор" in gs.humanize_error(Exception("403 PERMISSION_DENIED")), "403 → про права")
    check("не найдены" in gs.humanize_error(Exception("404 Not Found")), "404 → не найдена")
    check("лимит" in gs.humanize_error(Exception("429 quota exceeded")), "429 → квота")
    check(
        "таймаут" in gs.humanize_error(asyncio.TimeoutError()), "timeout → таймаут"
    )
    check(gs.column_letter(9) == "I" and gs.column_letter(27) == "AA", "колонки A..AA")

    print("7. Без настроек сервис честно сообщает об этом")
    bare = gs.GoogleSheetsService(Settings(_env_file=None, bot_token="1:TEST"))
    check(not bare.enabled, "интеграция выключена")
    try:
        await bare.append_order(make_order())
        check(False, "должно было упасть")
    except gs.SheetsError as exc:
        check("не настроена" in str(exc), f"понятная ошибка: {exc}")

    print("8. health_check кэшируется и не бьёт в Google каждый раз")
    with patch.object(gs, "Client") as client_cls, patch.object(
        gs.Credentials, "from_service_account_info", return_value=object()
    ):
        sheet = FakeSpreadsheet()
        client_cls.return_value.open_by_key.return_value = sheet
        healthy = gs.GoogleSheetsService(settings)

        check(await healthy.health_check(), "первая проверка — таблица доступна")
        calls_after_first = client_cls.call_count
        for _ in range(5):
            await healthy.health_check()
        check(
            client_cls.call_count == calls_after_first,
            f"повторные вызовы берутся из кэша (клиентов создано: {client_cls.call_count})",
        )
        await healthy.reset()
        await healthy.health_check()
        check(client_cls.call_count > calls_after_first, "после reset() — реальный запрос")

    print()
    if FAILS:
        print(f"ПРОВАЛОВ: {len(FAILS)}")
        raise SystemExit(1)
    print("Google Sheets слой работает корректно ✅")


if __name__ == "__main__":
    asyncio.run(main())
