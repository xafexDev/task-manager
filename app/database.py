"""Настройка SQLAlchemy 2.0 (асинхронный engine + сессии)."""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Базовый класс всех моделей SQLAlchemy."""

    pass


# Асинхронный движок
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug and settings.app_env == "development",
    future=True,
)

# Фабрика сессий
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI: выдаёт асинхронную сессию БД.

    Использование::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Создаёт все таблицы (используется в тестах и при первичном запуске)."""
    # Импортируем модели, чтобы они были зарегистрированы в метаданных
    from app.models import (  # noqa: F401
        user, workspace, project, task, comment,
        attachment, notification, dependency,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
