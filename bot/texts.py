"""Все тексты и подписи кнопок в одном месте.

Меняйте формулировки здесь — логика пользуется только этими константами.
Плейсхолдеры формата {name} подставляются через str.format(); HTML уже
экранируется в коде там, где данные приходят от пользователя.
"""

from __future__ import annotations

BRAND = "Студия «Вектор»"

# ================================== УСЛУГИ ==================================

# Ключ (код) уходит в callback_data и в БД — меняйте только текст.
SERVICES: dict[str, str] = {
    "bot": "🤖 Разработка бота",
    "site": "🌐 Сайт под ключ",
    "automation": "⚙️ Автоматизация / парсинг",
    "other": "💬 Другое",
}

SERVICE_TITLES: dict[str, str] = {
    "bot": "Разработка бота",
    "site": "Сайт под ключ",
    "automation": "Автоматизация / парсинг",
    "other": "Другое",
}


def service_title(code: str) -> str:
    """Название услуги по коду (для таблиц, карточек и уведомлений)."""
    return SERVICE_TITLES.get(code, code)


# ================================= СТАТУСЫ =================================

STATUS_META: dict[str, dict[str, str]] = {
    "new": {"title": "Новая", "emoji": "🆕", "button": "🆕 Новая"},
    "in_progress": {"title": "В работе", "emoji": "⏳", "button": "⏳ В работе"},
    "done": {"title": "Завершена", "emoji": "✅", "button": "✅ Завершена"},
    "rejected": {"title": "Отклонена", "emoji": "❌", "button": "❌ Отклонена"},
}


def status_title(code: str) -> str:
    return STATUS_META.get(code, {}).get("title", code)


def status_emoji(code: str) -> str:
    return STATUS_META.get(code, {}).get("emoji", "•")


def status_label(code: str) -> str:
    """«⏳ В работе» — для списков."""
    return f"{status_emoji(code)} {status_title(code)}"


# ============================== ПОДПИСИ КНОПОК ==============================

# --- клиент ---
BTN_NEW_ORDER = "🚀 Оставить заявку"
BTN_SERVICES = "💰 Услуги и цены"
BTN_MY_ORDERS = "📋 Мои заявки"
BTN_CONFIRM_ORDER = "🚀 Оформить заявку"
BTN_BACK_TO_MENU = "🏠 Главное меню"
BTN_CANCEL = "✖️ Отмена"
BTN_SHARE_CONTACT = "📞 Поделиться контактом"
BTN_SKIP = "⏭ Пропустить"
BTN_SEND = "✅ Отправить"
BTN_FILL_AGAIN = "🔄 Заполнить заново"
BTN_USE_PROFILE_NAME = "👤 {name}"
PHONE_PLACEHOLDER = "+7 999 123-45-67"

# --- админ ---
BTN_ADMIN_PANEL = "🛠 Админ-панель"
BTN_ADMIN_STATS = "📊 Статистика"
BTN_ADMIN_ORDERS = "🗂 Последние заявки"
BTN_ADMIN_BROADCAST = "📣 Рассылка"
BTN_ADMIN_SHEET = "🔗 Ссылка на таблицу"
BTN_ADMIN_BACK = "⬅️ Назад в админку"
BTN_ADMIN_TO_LIST = "⬅️ К списку заявок"
BTN_BROADCAST_SEND = "✅ Отправить всем"
BTN_BROADCAST_CANCEL = "✖️ Отменить"
BTN_PAGE_PREV = "⬅️"
BTN_PAGE_NEXT = "➡️"


# ============================== КЛИЕНТ: ТЕКСТЫ ==============================

START = (
    "👋 <b>Здравствуйте, {name}!</b>\n\n"
    f"Это бот {BRAND}. Делаем сайты, телеграм-ботов и автоматизацию процессов — "
    "от идеи до запуска.\n\n"
    "Оставьте заявку — обсудим задачу, сроки и стоимость."
)

MENU_PROMPT = "Выберите действие 👇"

SERVICES_TEXT = (
    "💰 <b>Услуги и цены</b>\n\n"
    "🤖 <b>Разработка Telegram-бота</b> — от 40 000 ₽\n"
    "Заявки, оплата, админ-панель, интеграции с CRM и Google Таблицами.\n\n"
    "🌐 <b>Сайт под ключ</b> — от 80 000 ₽\n"
    "Дизайн, вёрстка, домен и аналитика.\n\n"
    "⚙️ <b>Автоматизация и парсинг</b> — от 25 000 ₽\n"
    "Сбор данных, отчёты, синхронизация сервисов без ручной работы.\n\n"
    "💬 <b>Другое</b> — обсудим индивидуально.\n\n"
    "<i>Цены ориентировочные: итог зависит от задачи. "
    "Опишите её в заявке — расчёт бесплатно.</i>"
)

# --- FSM заявки ---

ORDER_START = "🚀 <b>Оформление заявки</b>\n\nОтветьте на 4 коротких вопроса — это займёт минуту."

ASK_SERVICE = "1️⃣ <b>Какая услуга вас интересует?</b>\nВыберите вариант на клавиатуре."
ASK_NAME = (
    "2️⃣ <b>Как к вам обращаться?</b>\n\n"
    "Напишите имя сообщением или нажмите кнопку, чтобы взять его из профиля."
)
ASK_PHONE = (
    "3️⃣ <b>Телефон для связи</b>\n\n"
    "Нажмите «Поделиться контактом» или отправьте номер текстом.\n"
    "Например: <code>+7 999 123-45-67</code>"
)
ASK_COMMENT = (
    "4️⃣ <b>Опишите задачу</b>\n\n"
    "Пары предложений достаточно. Если добавить нечего — нажмите «Пропустить»."
)

INVALID_SERVICE = "Пожалуйста, выберите услугу кнопкой из списка."
PHONE_ACCEPTED = "✅ Телефон сохранён."
INVALID_NAME = (
    "Такое имя принять не получится 🙃\n"
    "Напишите его текстом: от 2 до 64 символов."
)
INVALID_PHONE = (
    "Не похоже на номер телефона 🤔\n"
    "Должно быть минимум 10 цифр. Можно отправить контакт кнопкой."
)
COMMENT_TOO_LONG = "Слишком длинный текст — максимум {limit} символов. Сократите, пожалуйста."
EMPTY_COMMENT = "—"

CONFIRM_TEXT = (
    "🔍 <b>Проверьте заявку</b>\n\n"
    "🧩 Услуга: <b>{service}</b>\n"
    "👤 Имя: {name}\n"
    "📞 Телефон: {phone}\n"
    "💬 Комментарий: {comment}\n\n"
    "Всё верно?"
)

ORDER_SAVED = (
    "🎉 <b>Заявка №{order_id} отправлена!</b>\n\n"
    "Мы свяжемся с вами по указанному номеру. "
    "Статус всегда можно посмотреть в «Мои заявки»."
)

ORDER_FLOW_CANCELLED = "Хорошо, отменили. Возвращаемся в меню."
ORDER_FLOW_RESTART = "Начнём заново."

# --- мои заявки ---

MY_ORDERS_EMPTY = (
    "📭 <b>У вас пока нет заявок.</b>\n\n"
    "Оставьте первую — она появится здесь со статусом."
)
MY_ORDERS_HEADER = "📋 <b>Ваши заявки</b>\n\n"
MY_ORDERS_ITEM = (
    "<b>№{order_id}</b> · {service}\n"
    "🗓 {date}\n"
    "Статус: {status}\n\n"
)
MY_ORDERS_FOOTER = "<i>Всего заявок: {total}. Показаны последние {shown}.</i>"

USER_STATUS_CHANGED = (
    "🔔 <b>Статус заявки №{order_id} обновлён</b>\n\n"
    "🧩 {service}\n"
    "Новый статус: <b>{status}</b>"
)

# ============================== АДМИН: ТЕКСТЫ ==============================

ADMIN_ONLY = "⛔️ Команда доступна только администраторам."
ADMIN_ONLY_PRIVATE = "Админ-панель работает только в личных сообщениях."

ADMIN_PANEL = "🛠 <b>Админ-панель</b>\n\nЗаявки, статистика и рассылка — всё здесь."

ADMIN_STATS = (
    "📊 <b>Статистика</b>\n\n"
    "👥 Пользователей: <b>{users_total}</b>\n"
    "📥 Заявок всего: <b>{orders_total}</b>\n"
    "📅 Сегодня: <b>{orders_today}</b>\n"
    "🗓 За 7 дней: <b>{orders_week}</b>\n\n"
    "<b>По статусам:</b>\n"
    "{status_lines}\n\n"
    "🔄 Google Таблицы: {sheets_status}"
)
ADMIN_STATS_SHEETS_ON = "работают"
ADMIN_STATS_SHEETS_OFF = "не настроены"
ADMIN_STATS_SHEETS_DOWN = "⚠️ настроены, но недоступны"

ADMIN_ORDERS_EMPTY = "🗂 Заявок пока нет."
ADMIN_ORDERS_HEADER = "🗂 <b>Последние заявки</b>\nСтраница {page} из {pages}\n\n"

ADMIN_ORDER_CARD = (
    "📄 <b>Заявка №{order_id}</b>\n\n"
    "🧩 Услуга: <b>{service}</b>\n"
    "👤 Имя: {name}\n"
    "📞 Телефон: <code>{phone}</code>\n"
    "💬 Комментарий: {comment}\n\n"
    "👤 {username}\n"
    "🆔 <code>{user_id}</code>\n"
    "🗓 Создана: {created_at}\n"
    "🔄 Обновлена: {updated_at}\n\n"
    "Статус: <b>{status}</b>"
)

ADMIN_ORDER_NOT_FOUND = "Заявка не найдена — возможно, её удалили."
ADMIN_STATUS_UPDATED = "Статус заявки №{order_id}: <b>{status}</b>"
ADMIN_STATUS_SAME = "Заявка №{order_id} уже в статусе «{status}»."

ADMIN_SHEET_SYNC_FAILED = (
    "⚠️ <b>Google Таблица не обновилась</b>\n"
    "Статус заявки №{order_id} сохранён в БД, но строку в таблице обновить не удалось.\n\n"
    "<code>{error}</code>"
)
ADMIN_ORDER_SHEET_FAILED = (
    "⚠️ <b>Заявка №{order_id} не попала в Google Таблицу</b>\n\n"
    "Заявка сохранена в БД и не потеряется, но синхронизация не прошла. "
    "Проверьте доступ сервисного аккаунта.\n\n"
    "<code>{error}</code>"
)

ADMIN_NEW_ORDER = (
    "🔔 <b>Новая заявка №{order_id}</b>\n\n"
    "🧩 Услуга: <b>{service}</b>\n"
    "👤 Имя: {name}\n"
    "📞 Телефон: <code>{phone}</code>\n"
    "💬 Комментарий: {comment}\n\n"
    "👤 {username}\n"
    "🆔 <code>{user_id}</code>\n"
    "🗓 {created_at}"
)

SHEET_ROW_OK = "строка {row}"
SHEET_ROW_MISSING = "не добавлена"

# --- рассылка ---

BROADCAST_ASK = (
    "📣 <b>Рассылка</b>\n\n"
    "Отправьте текст сообщения или фото с подписью. "
    "Поддерживается HTML-разметка Telegram.\n\n"
    "Перед отправкой покажу предпросмотр и спрошу подтверждение."
)
BROADCAST_INVALID_CONTENT = "Нужен текст или фото с подписью. Попробуйте ещё раз."
BROADCAST_TOO_LONG = "Слишком длинное сообщение: Telegram принимает до {limit} символов."
BROADCAST_EMPTY = "В базе нет пользователей для рассылки."
BROADCAST_PREVIEW = (
    "👀 <b>Предпросмотр рассылки</b>\n"
    "Получателей: <b>{total}</b>\n\n"
    "──────────────\n{content}\n──────────────\n\n"
    "Отправляем?"
)
BROADCAST_STARTED = "🚀 Рассылка запущена. Пришлю отчёт, когда закончу."
BROADCAST_RESULT = (
    "📣 <b>Рассылка завершена</b>\n\n"
    "✅ Доставлено: <b>{ok}</b>\n"
    "🚫 Заблокировали бота: <b>{blocked}</b>\n"
    "⚠️ Прочие ошибки: <b>{failed}</b>"
)
BROADCAST_CANCELLED = "Рассылка отменена."

SHEET_LINK_TEXT = "📊 <b>Google Таблица с заявками:</b>\n{url}"
SHEET_NOT_CONFIGURED = (
    "🔗 Google Таблица не настроена.\n\n"
    "Укажите <code>GOOGLE_SHEET_URL</code> и <code>GOOGLE_CREDENTIALS_PATH</code> "
    "в <code>.env</code> и перезапустите бота."
)

# ================================== ОБЩИЕ ==================================

ERROR_GENERIC = "😔 Что-то пошло не так. Попробуйте ещё раз чуть позже."
UNKNOWN_COMMAND = "Не понял команду 🤷‍♂️ Откройте меню командой /start"
RATE_LIMITED = "⏳ Слишком часто. Подождите пару секунд."
