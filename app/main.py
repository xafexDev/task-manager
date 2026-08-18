"""Точка входа FastAPI приложения Task Manager API."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.exceptions import AppException
from app.core.logging_config import setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.routers import (
    auth,
    notifications,
    projects,
    tasks,
    workspaces,
    ws as ws_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения: настройка логирования при запуске."""
    setup_logging(debug=settings.app_debug)
    # Убедимся, что директория для загрузок существует
    os.makedirs(settings.upload_dir, exist_ok=True)
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "## RESTful API системы управления проектами и задачами (Task Manager)\n\n"
        "**Стек:** Python 3.11+, FastAPI, SQLAlchemy 2.0, PostgreSQL/SQLite, Redis (опц.), WebSockets\n\n"
        "### Возможности\n"
        "- Регистрация и аутентификация (JWT access + refresh)\n"
        "- Workspace + Project с ролевой моделью RBAC\n"
        "- Канбан-доска с drag-and-drop (автоматический пересчёт order)\n"
        "- Подзадачи, теги, зависимости между задачами (с защитой от циклов)\n"
        "- Комментарии с упоминаниями @username\n"
        "- Вложения файлов (локальное хранилище или S3-совместимое)\n"
        "- Логирование времени ('1h 30m', '45m')\n"
        "- Уведомления (mention, assignment)\n"
        "- Реал-тайм обновления через WebSocket\n"
        "- Пагинация, фильтрация, глобальный поиск\n"
        "- Rate limiting (опционально через Redis)\n"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# -------- Middleware --------

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting (если включён)
if settings.rate_limit_enabled:
    app.add_middleware(RateLimitMiddleware)


# -------- Статика для загруженных файлов --------
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


# -------- Роутеры --------
api_v1_prefix = "/api/v1"
app.include_router(auth.router, prefix=api_v1_prefix)
app.include_router(workspaces.router, prefix=api_v1_prefix)
app.include_router(projects.router, prefix=api_v1_prefix)
app.include_router(tasks.router, prefix=api_v1_prefix)
app.include_router(notifications.router, prefix=api_v1_prefix)
app.include_router(ws_router.router, prefix=api_v1_prefix)


# -------- Health check --------

@app.get("/health", tags=["System"], summary="Проверка работоспособности")
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "version": "1.0.0"}


@app.get("/", tags=["System"], summary="Корневой эндпоинт")
async def root() -> dict:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
