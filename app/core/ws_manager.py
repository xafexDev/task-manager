"""Менеджер WebSocket-подключений для реал-тайм обновлений.

Каждый проект имеет свою "комнату" — набор активных подключений.
При любом CRUD-действии с задачей сервер рассылает событие всем клиентам комнаты.
"""
import json
import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger("app.ws")


class ConnectionManager:
    """Менеджер активных WebSocket-подключений, сгруппированных по project_id."""

    def __init__(self) -> None:
        # project_id -> set[WebSocket]
        self._rooms: dict[UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: UUID, websocket: WebSocket) -> None:
        """Принимает подключение и добавляет его в комнату проекта."""
        await websocket.accept()
        self._rooms[project_id].add(websocket)
        logger.info(
            f"WS connected to project {project_id}, "
            f"total in room: {len(self._rooms[project_id])}"
        )

    def disconnect(self, project_id: UUID, websocket: WebSocket) -> None:
        """Удаляет подключение из комнаты."""
        if project_id in self._rooms:
            self._rooms[project_id].discard(websocket)
            if not self._rooms[project_id]:
                del self._rooms[project_id]
        logger.info(f"WS disconnected from project {project_id}")

    async def broadcast(self, project_id: UUID, event_type: str, payload: Any) -> None:
        """Рассылает JSON-событие всем клиентам в комнате проекта.

        Args:
            project_id: ID проекта (комнаты)
            event_type: тип события (например, "task.created", "task.moved")
            payload: данные события (любой JSON-сериализуемый объект)
        """
        message = json.dumps(
            {"event": event_type, "project_id": str(project_id), "data": payload},
            default=str,
            ensure_ascii=False,
        )
        room = self._rooms.get(project_id, set()).copy()
        dead: list[WebSocket] = []
        for ws in room:
            try:
                await ws.send_text(message)
            except Exception as exc:
                logger.warning(f"WS send failed, removing: {exc}")
                dead.append(ws)
        for ws in dead:
            self._rooms.get(project_id, set()).discard(ws)

    def room_size(self, project_id: UUID) -> int:
        """Количество активных подключений в комнате."""
        return len(self._rooms.get(project_id, set()))


# Глобальный синглтон менеджера
ws_manager = ConnectionManager()
