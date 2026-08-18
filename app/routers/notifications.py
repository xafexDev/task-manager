"""Роутер уведомлений (с курсорной пагинацией)."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, update, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cursor import (
    CursorParams, CursorPage, CursorMeta,
    decode_cursor, encode_cursor,
    parse_cursor_time_str, parse_cursor_id,
)
from app.database import get_db
from app.dependencies import CurrentUser
from app.models import Notification
from app.schemas.common import NotificationRead

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get(
    "",
    summary="Список уведомлений текущего пользователя (курсорная пагинация)",
    description=(
        "Возвращает уведомления в обратном хронологическом порядке "
        "(сначала новые). Используется курсорная пагинация: передайте "
        "`cursor` из `meta.next_cursor` для получения следующей страницы. "
        "Query-параметр `unread_only=true` фильтрует только непрочитанные."
    ),
)
async def list_notifications(
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
    unread_only: bool = False,
) -> dict:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))

    # Курсор: (created_at, id)
    cursor_time = parse_cursor_time_str(cursor_params.cursor, "created_at")
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_time and cursor_id_str:
        stmt = stmt.where(
            or_(
                Notification.created_at < cursor_time,
                and_(
                    Notification.created_at == cursor_time,
                    Notification.id < cursor_id_str,
                ),
            )
        )

    stmt = stmt.order_by(
        desc(Notification.created_at), desc(Notification.id)
    ).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    has_next = len(items) > cursor_params.limit
    if has_next:
        items = items[: cursor_params.limit]

    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor({
            "created_at": last.created_at.isoformat() if last.created_at else None,
            "id": str(last.id),
        })

    items_dicts = [NotificationRead.model_validate(n).model_dump(mode="json") for n in items]
    return CursorPage(
        items=items_dicts,
        meta=CursorMeta(
            limit=cursor_params.limit,
            has_next=has_next,
            has_prev=bool(cursor_params.cursor),
            next_cursor=next_cursor,
            prev_cursor=None,
        ),
    ).to_dict()


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Отметить уведомление как прочитанное",
)
async def mark_as_read(
    notification_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    notif = await db.get(Notification, notification_id)
    if notif is None or notif.user_id != user.id:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Уведомление не найдено")
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return NotificationRead.model_validate(notif)


@router.post(
    "/read-all",
    status_code=status.HTTP_200_OK,
    summary="Отметить все уведомления как прочитанные",
)
async def mark_all_as_read(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return {"message": "Все уведомления отмечены как прочитанные"}
