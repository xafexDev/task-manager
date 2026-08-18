"""Pytest configuration: fixtures для тестов.

Использует in-memory SQLite + асинхронный движок.
Каждый тест получает чистую БД (таблицы создаются перед тестом, удаляются после).
"""
import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Принудительно используем SQLite in-memory для тестов
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-tests-only"
os.environ["APP_ENV"] = "test"

# Импортируем после установки переменных окружения
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    User, Workspace, WorkspaceMember,
    Project, ProjectMember, Section, Tag,
    Task, Subtask, TaskDependency,
    Comment, Attachment, Notification, TimeLog,
)


@pytest.fixture(scope="session")
def event_loop():
    """Один event loop на всю сессию тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Создаёт свежий in-memory движок для каждого теста."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Сессия БД с автоматическим откатом после теста."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент с подменённой зависимостью get_db на тестовую БД."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def db_direct(db_engine):
    """Прямой доступ к тестовой БД через сессию (для setup-операций в тестах).

    Используется, когда нужно изменить данные в обход HTTP API — например,
    выставить created_at для проверки курсорной пагинации в SQLite.
    """
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with session_factory() as session:
        yield session


# -------- Хелперы для создания тестовых сущностей --------

async def register_user(client: AsyncClient, email: str, password: str = "Password123!",
                        username: str | None = None, workspace_name: str | None = None) -> dict:
    """Регистрирует пользователя, возвращает словарь с токенами и ID."""
    username = username or email.split("@")[0]
    response = await client.post("/api/v1/auth/register", json={
        "email": email,
        "username": username,
        "password": password,
        "workspace_name": workspace_name or f"WS-{username}",
    })
    assert response.status_code == 201, f"Register failed: {response.text}"
    data = response.json()
    # Получаем ID пользователя через /me
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me_resp.status_code == 200
    data["user"] = me_resp.json()
    return data


async def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_project(client: AsyncClient, token: str, workspace_id: str,
                         name: str = "Test Project") -> dict:
    """Создаёт проект и возвращает его данные."""
    response = await client.post(
        "/api/v1/projects",
        json={"workspace_id": workspace_id, "name": name},
        headers=await auth_headers(token),
    )
    assert response.status_code == 201, f"Create project failed: {response.text}"
    return response.json()


async def create_section(client: AsyncClient, token: str, project_id: str,
                         name: str = "To Do", type_: str = "todo") -> dict:
    response = await client.post(
        f"/api/v1/projects/{project_id}/sections",
        json={"name": name, "type": type_},
        headers=await auth_headers(token),
    )
    assert response.status_code == 201, f"Create section failed: {response.text}"
    return response.json()


async def create_task(client: AsyncClient, token: str, section_id: str,
                      title: str = "Test Task", **kwargs) -> dict:
    project_id = kwargs.pop("project_id", None)
    if project_id is None:
        raise ValueError("project_id is required for create_task helper")
    payload = {"section_id": section_id, "title": title, **kwargs}
    response = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json=payload,
        headers=await auth_headers(token),
    )
    assert response.status_code == 201, f"Create task failed: {response.text}"
    return response.json()
