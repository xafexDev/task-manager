"""Схемы Workspace."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime


class WorkspaceMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: UUID
    user_id: UUID
    role: str
    created_at: datetime


class InviteRequest(BaseModel):
    """Приглашение пользователя в workspace по email."""
    email: EmailStr
    role: str = Field("member", pattern="^(admin|member|guest)$")


class UpdateMemberRole(BaseModel):
    role: str = Field(..., pattern="^(admin|member|guest)$")
