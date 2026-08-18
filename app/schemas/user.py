"""Схемы пользователя и общие типы."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=64)


class UserRead(BaseModel):
    """Публичные данные пользователя."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    username: str
    avatar_url: str | None = None
    status: str = "active"
    created_at: datetime


class UserUpdate(BaseModel):
    """Обновление профиля."""
    username: str | None = Field(None, min_length=3, max_length=64)
    avatar_url: str | None = Field(None, max_length=512)


class PaginatedMeta(BaseModel):
    """Метаданные пагинации."""
    total: int
    limit: int
    offset: int
    has_next: bool


class PaginatedResponse(BaseModel):
    """Обёртка для пагинированных списков."""
    items: list
    meta: PaginatedMeta
