"""Схемы Comment, Attachment, Notification."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserRead


class CommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    user: UserRead
    text: str
    created_at: datetime
    updated_at: datetime


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    uploader_id: UUID
    filename: str
    file_url: str
    file_size: int
    mime_type: str
    created_at: datetime


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    type: str
    title: str
    body: str | None = None
    payload: str | None = None
    is_read: bool
    created_at: datetime


class ActivityLogRead(BaseModel):
    """Запись истории изменений задачи (audit log)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: UUID
    user_id: UUID | None = None
    action: str
    description: str | None = None
    payload: str | None = None
    created_at: datetime


class ActivityLogBrief(BaseModel):
    """Краткая форма для встраивания в карточку задачи (без payload)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    description: str | None = None
    user_id: UUID | None = None
    created_at: datetime
