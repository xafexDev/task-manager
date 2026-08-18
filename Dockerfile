FROM python:3.11-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходники
COPY . .

# Создаём директорию для загрузок
RUN mkdir -p /app/uploads

# Переменные окружения по умолчанию
# ВАЖНО: задаём DATABASE_URL по умолчанию, иначе может подхватиться
# переменная из внешнего окружения (например, SQLite URL в нестандартном формате).
# В продакшене переопределите через docker-compose или -e DATABASE_URL=...
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    DATABASE_URL=sqlite+aiosqlite:///./taskmanager.db \
    JWT_SECRET_KEY=change-me-in-production-please-use-openssl-rand-hex-32 \
    CORS_ORIGINS=* \
    RATE_LIMIT_ENABLED=false

EXPOSE 8000

# Скрипт запуска: ждём БД, применяем миграции, стартуем uvicorn.
# Retry-логика нужна, т.к. между healthcheck postgres и реальной готовностью
# принимать соединения может быть небольшая задержка.
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
CMD ["/docker-entrypoint.sh"]
