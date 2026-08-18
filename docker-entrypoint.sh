#!/bin/sh
# Точка входа для Docker-контейнера.
# Ждёт доступности БД, применяет миграции, запускает uvicorn.

set -e

echo "[entrypoint] Запуск Task Manager API..."

# Применяем миграции с retry (до 5 попыток с задержкой 5 секунд).
# Это нужно, т.к. PostgreSQL может быть ещё не готов принимать соединения
# сразу после прохождения healthcheck.
MAX_ATTEMPTS=5
ATTEMPT=0
until alembic upgrade head; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        echo "[entrypoint] ОШИБКА: не удалось применить миграции после $MAX_ATTEMPTS попыток"
        exit 1
    fi
    echo "[entrypoint] Попытка $ATTEMPT/$MAX_ATTEMPTS не удалась. Повтор через 5 секунд..."
    sleep 5
done

echo "[entrypoint] Миграции применены успешно. Запускаем uvicorn..."

# Стартуем uvicorn с reload для dev-режима (через APP_DEBUG=true).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
