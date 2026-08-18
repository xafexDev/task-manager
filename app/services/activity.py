"""Сервис записи истории изменений задачи (Activity Log / audit log).

Каждая функция-хелпер создаёт запись в activity_logs с описанием действия.
Записи создаются в той же сессии БД, что и основная операция, поэтому
откатываются вместе с ней при ошибке.
"""
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog


async def log_activity(
    db: AsyncSession,
    *,
    task_id: UUID,
    user_id: UUID | None,
    action: str,
    description: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ActivityLog:
    """Создаёт запись в истории задачи.

    Args:
        db: асинхронная сессия
        task_id: ID задачи
        user_id: ID пользователя, выполнившего действие (None для системных)
        action: тип действия (например, "task.updated", "comment.created")
        description: человекочитаемое описание
        payload: словарь с детальным контекстом (field/old/new и т.д.)
    """
    entry = ActivityLog(
        task_id=task_id,
        user_id=user_id,
        action=action,
        description=description,
        payload=json.dumps(payload, default=str, ensure_ascii=False) if payload else None,
    )
    db.add(entry)
    await db.flush()
    return entry


# -------- Специализированные хелперы --------

async def log_task_created(
    db: AsyncSession, task_id: UUID, user_id: UUID, task_title: str
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="task.created",
        description=f"Создал задачу «{task_title}»",
        payload={"title": task_title},
    )


async def log_task_updated_field(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
    field: str,
    old_value: Any,
    new_value: Any,
) -> ActivityLog:
    """Запись об изменении одного поля задачи."""
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="task.updated",
        description=f"Изменил поле «{field}»: {old_value!r} → {new_value!r}",
        payload={"field": field, "old": old_value, "new": new_value},
    )


async def log_task_moved(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
    from_section_id: UUID,
    to_section_id: UUID,
    from_order: int,
    to_order: int,
) -> ActivityLog:
    """Запись о перемещении задачи между/внутри колонок."""
    if from_section_id == to_section_id:
        description = f"Переместил задачу внутри колонки: позиция {from_order} → {to_order}"
    else:
        description = (
            f"Переместил задачу из колонки {from_section_id} "
            f"(поз. {from_order}) в колонку {to_section_id} (поз. {to_order})"
        )
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="task.moved",
        description=description,
        payload={
            "from_section_id": str(from_section_id),
            "to_section_id": str(to_section_id),
            "from_order": from_order,
            "to_order": to_order,
        },
    )


async def log_task_assigned(
    db: AsyncSession, task_id: UUID, user_id: UUID, assignee_id: UUID, assignee_username: str
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="task.assigned",
        description=f"Назначил исполнителя: {assignee_username}",
        payload={"assignee_id": str(assignee_id), "assignee_username": assignee_username},
    )


async def log_task_unassigned(
    db: AsyncSession, task_id: UUID, user_id: UUID, prev_assignee_id: UUID
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="task.unassigned",
        description="Снял исполнителя с задачи",
        payload={"previous_assignee_id": str(prev_assignee_id)},
    )


async def log_task_completed(
    db: AsyncSession, task_id: UUID, user_id: UUID, completed: bool
) -> ActivityLog:
    action = "task.completed" if completed else "task.reopened"
    description = "Отметил задачу как выполненную" if completed else "Переоткрыл задачу"
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action=action,
        description=description,
        payload={"is_completed": completed},
    )


async def log_task_deleted(
    db: AsyncSession, task_id: UUID, user_id: UUID, task_title: str
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="task.deleted",
        description=f"Удалил задачу «{task_title}»",
        payload={"title": task_title},
    )


async def log_subtask_created(
    db: AsyncSession, task_id: UUID, user_id: UUID, subtask_title: str
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="subtask.created",
        description=f"Добавил подзадачу «{subtask_title}»",
        payload={"subtask_title": subtask_title},
    )


async def log_subtask_updated(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
    subtask_id: UUID,
    changes: dict[str, Any],
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="subtask.updated",
        description=f"Обновил подзадачу {subtask_id}",
        payload={"subtask_id": str(subtask_id), "changes": changes},
    )


async def log_comment_created(
    db: AsyncSession, task_id: UUID, user_id: UUID, comment_id: UUID, text_preview: str
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="comment.created",
        description=f"Добавил комментарий: {text_preview[:80]}",
        payload={"comment_id": str(comment_id)},
    )


async def log_attachment_created(
    db: AsyncSession, task_id: UUID, user_id: UUID, attachment_id: UUID, filename: str
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="attachment.created",
        description=f"Загрузил файл: {filename}",
        payload={"attachment_id": str(attachment_id), "filename": filename},
    )


async def log_timelog_created(
    db: AsyncSession, task_id: UUID, user_id: UUID, timelog_id: UUID, spent_seconds: int
) -> ActivityLog:
    """Запись о логировании времени."""
    hours = spent_seconds // 3600
    minutes = (spent_seconds % 3600) // 60
    if hours:
        duration_str = f"{hours}ч {minutes}мин"
    else:
        duration_str = f"{minutes}мин"
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="timelog.created",
        description=f"Залогировал время: {duration_str}",
        payload={
            "timelog_id": str(timelog_id),
            "spent_seconds": spent_seconds,
        },
    )


async def log_dependency_created(
    db: AsyncSession,
    task_id: UUID,
    user_id: UUID,
    predecessor_id: UUID,
    successor_id: UUID,
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="dependency.created",
        description=f"Создал зависимость: задача {predecessor_id} блокирует {successor_id}",
        payload={
            "predecessor_task_id": str(predecessor_id),
            "successor_task_id": str(successor_id),
        },
    )


async def log_dependency_deleted(
    db: AsyncSession, task_id: UUID, user_id: UUID, dep_id: int
) -> ActivityLog:
    return await log_activity(
        db,
        task_id=task_id,
        user_id=user_id,
        action="dependency.deleted",
        description=f"Удалил зависимость #{dep_id}",
        payload={"dependency_id": dep_id},
    )
