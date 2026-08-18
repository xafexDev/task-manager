"""Сервис уведомлений: создания и упоминания @username."""
import json
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User

# Регулярка для @username (буквы/цифры/_-, 3-64 символа)
MENTION_RE = re.compile(r"@([A-Za-z0-9_\-.]{3,64})")


async def create_notification(
    db: AsyncSession,
    user_id: UUID,
    type_: str,
    title: str,
    body: str | None = None,
    payload: dict | None = None,
) -> Notification:
    """Создаёт уведомление для пользователя."""
    notif = Notification(
        user_id=user_id,
        type=type_,
        title=title,
        body=body,
        payload=json.dumps(payload, default=str) if payload else None,
    )
    db.add(notif)
    await db.flush()
    return notif


async def resolve_mentions(
    db: AsyncSession, text: str, exclude_user_id: UUID | None = None
) -> list[User]:
    """Находит всех упомянутых через @username пользователей в тексте.

    Args:
        db: сессия
        text: текст комментария/описания
        exclude_user_id: ID автора (чтобы не уведомлять самого себя)

    Returns:
        Список объектов User, которые упомянуты.
    """
    usernames = set(MENTION_RE.findall(text))
    if not usernames:
        return []
    result = await db.execute(select(User).where(User.username.in_(usernames)))
    users = list(result.scalars().all())
    if exclude_user_id is not None:
        users = [u for u in users if u.id != exclude_user_id]
    return users


async def notify_mentions(
    db: AsyncSession,
    text: str,
    actor: User,
    task_id: UUID,
    project_id: UUID,
    context: str = "comment",
) -> list[Notification]:
    """Создаёт уведомления для всех упомянутых пользователей."""
    mentioned = await resolve_mentions(db, text, exclude_user_id=actor.id)
    notifs: list[Notification] = []
    for u in mentioned:
        notif = await create_notification(
            db=db,
            user_id=u.id,
            type_="mention",
            title=f"{actor.username} упомянул вас в {context}",
            body=text[:200],
            payload={
                "task_id": str(task_id),
                "project_id": str(project_id),
                "actor_id": str(actor.id),
                "actor_username": actor.username,
                "context": context,
            },
        )
        notifs.append(notif)
    return notifs


async def notify_assignment(
    db: AsyncSession,
    assigner: User,
    assignee_id: UUID,
    task_id: UUID,
    project_id: UUID,
    task_title: str,
) -> Notification | None:
    """Уведомление о назначении на задачу (не отправляем, если назначает сам себе)."""
    if assigner.id == assignee_id:
        return None
    return await create_notification(
        db=db,
        user_id=assignee_id,
        type_="assignment",
        title=f"{assigner.username} назначил вас на задачу: {task_title}",
        body=None,
        payload={
            "task_id": str(task_id),
            "project_id": str(project_id),
            "actor_id": str(assigner.id),
            "actor_username": assigner.username,
        },
    )
