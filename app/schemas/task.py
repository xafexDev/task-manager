"""Схемы Task, Subtask, Dependency, TimeLog."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserRead


class TaskCreate(BaseModel):
    section_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    assignee_id: UUID | None = None
    priority: str = Field("medium", pattern="^(low|medium|high|urgent)$")
    due_date: datetime | None = None
    tag_ids: list[UUID] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=10000)
    assignee_id: UUID | None = None
    priority: str | None = Field(None, pattern="^(low|medium|high|urgent)$")
    due_date: datetime | None = None
    is_completed: bool | None = None
    tag_ids: list[UUID] | None = None


class TaskMove(BaseModel):
    """Перемещение задачи (drag-and-drop)."""
    section_id: UUID | None = Field(None, description="Новая колонка (если меняется)")
    order: int = Field(..., ge=0, description="Новая позиция внутри колонки")


class SubtaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)


class SubtaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    title: str
    is_completed: bool
    created_at: datetime


class SubtaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    is_completed: bool | None = None


class DependencyCreate(BaseModel):
    """Создание связи: predecessor блокирует successor.

    Указывается на эндпоинте /tasks/{successor_id}/dependencies,
    где successor_id — задача, которая БУДЕТ заблокирована.
    В теле передаётся predecessor_task_id — задача, которая БЛОКИРУЕТ.
    """
    predecessor_task_id: UUID


class DependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    predecessor_task_id: UUID
    successor_task_id: UUID
    created_at: datetime


class TimeLogCreate(BaseModel):
    """Логирование времени.

    Принимает либо `spent_seconds` (целое), либо строку `spent_time` ("1h 30m", "45m").
    """
    spent_seconds: int | None = Field(None, ge=0)
    spent_time: str | None = Field(None, description="Например: '1h 30m', '45m', '2h'")
    description: str | None = Field(None, max_length=1000)


class TimeLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    user_id: UUID
    spent_seconds: int
    description: str | None = None
    logged_at: datetime


class TaskRead(BaseModel):
    """Карточка задачи с предзагрузкой связанных данных."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    section_id: UUID
    title: str
    description: str | None = None
    assignee: UserRead | None = None
    reporter: UserRead | None = None
    priority: str
    due_date: datetime | None = None
    order: int
    is_completed: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    tags: list["TagBrief"] = Field(default_factory=list)
    subtasks: list[SubtaskRead] = Field(default_factory=list)


class TaskBrief(BaseModel):
    """Краткая карточка для списков."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    priority: str
    order: int
    is_completed: bool
    section_id: UUID
    assignee_id: UUID | None = None
    due_date: datetime | None = None


class TaskMoveResponse(BaseModel):
    """Ответ на перемещение задачи: обновлённая задача + изменённые порядки."""
    task: TaskBrief
    affected_orders: dict[str, list[TaskBrief]] = Field(
        default_factory=dict,
        description="section_id -> список задач с обновлёнными order",
    )


from app.schemas.project import TagBrief  # noqa: E402

TaskRead.model_rebuild()
