"""Схемы Project, Section, Tag."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    workspace_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    icon: str | None = Field(None, max_length=32)
    color: str | None = Field(None, max_length=16)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    icon: str | None = None
    color: str | None = None
    is_archived: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_archived: bool
    created_at: datetime


class ProjectMemberAdd(BaseModel):
    user_id: UUID
    role: str = Field("editor", pattern="^(manager|editor|viewer)$")


class ProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: UUID
    user_id: UUID
    role: str
    created_at: datetime


class SectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field("todo", pattern="^(todo|done)$")


class SectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    order: int | None = Field(None, ge=0)


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    order: int
    type: str


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field("#6B7280", max_length=16)


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    color: str


class TagBrief(BaseModel):
    """Краткая форма тега для встраивания в карточку задачи."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    color: str
