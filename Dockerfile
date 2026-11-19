# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

WORKDIR /app

# tzdata нужен, чтобы корректно работали часовые пояса (Europe/Moscow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Каталог для SQLite: монтируется томом в docker-compose
RUN mkdir -p /app/data

# Запуск от непривилегированного пользователя
RUN useradd --create-home --uid 10001 botuser \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-u", "main.py"]
