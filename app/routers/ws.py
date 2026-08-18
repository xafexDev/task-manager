"""WebSocket-роутер для реал-тайм обновлений проекта."""
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.core.ws_manager import ws_manager
from app.database import get_db, async_session_factory
from app.models import ProjectMember, User

router = APIRouter(tags=["WebSocket"])


@router.websocket(
    "/projects/{project_id}/ws",
    name="project_ws",
)
async def project_ws(websocket: WebSocket, project_id: UUID, token: str) -> None:
    """WebSocket-эндпоинт для комнаты проекта.

    Токен передаётся как ?token=... (WebSocket не поддерживает стандартный
    заголовок Authorization).
    """
    # Аутентификация
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except Exception:
        await websocket.close(code=4401, reason="Невалидный токен")
        return

    # Проверка доступа к проекту
    async with async_session_factory() as db:
        # Пользователь существует и активен?
        user = await db.get(User, user_id)
        if user is None or user.status != "active":
            await websocket.close(code=4403, reason="Пользователь не найден или деактивирован")
            return
        # Участник проекта?
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            await websocket.close(code=4403, reason="Нет доступа к проекту")
            return

    # Принимаем подключение
    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            # Сервер не ожидает входящих сообщений от клиента — только держим соединение.
            # В будущем можно добавить "ping" / "typing" события.
            data = await websocket.receive_text()
            # Игнорируем входящие (или можно логировать)
            _ = data
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)
