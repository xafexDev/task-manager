"""Модели Task, Subtask, Tag↔Task (M2M), TaskDependency."""
import uuid
from datetime import datetime

from sqlalchemy import (
    String, Text, Boolean, Integer, DateTime, ForeignKey, func, Table, Column,
    UniqueConstraint, select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import UUIDType

# M2M: Task <-> Tag
task_tags = Table(
    "task_tags",
    Base.metadata,
    Column("task_id", UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUIDType, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Task(Base):
    """Задача на Канбан-доске."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="tasks")
    section = relationship("Section", back_populates="tasks")
    assignee = relationship("User", foreign_keys=[assignee_id], lazy="selectin")
    reporter = relationship("User", foreign_keys=[reporter_id], lazy="selectin")
    tags = relationship("Tag", secondary=task_tags, lazy="selectin")
    subtasks = relationship(
        "Subtask", back_populates="task", cascade="all, delete-orphan",
        order_by="Subtask.id",
    )
    comments = relationship(
        "Comment", back_populates="task", cascade="all, delete-orphan",
        order_by="Comment.created_at",
    )
    attachments = relationship(
        "Attachment", back_populates="task", cascade="all, delete-orphan"
    )

    # Связи зависимостей
    blocking = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.predecessor_task_id",
        back_populates="predecessor",
        cascade="all, delete-orphan",
    )
    blocked_by = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.successor_task_id",
        back_populates="successor",
        cascade="all, delete-orphan",
    )


class Subtask(Base):
    """Подзадача."""

    __tablename__ = "subtasks"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task = relationship("Task", back_populates="subtasks")


class TaskDependency(Base):
    """Связь между задачами: predecessor блокирует successor.

    predecessor_task_id — задача, которая блокирует (предшественник)
    successor_task_id   — задача, которая заблокирована (преемник)
    """

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            name="uq_task_dependency",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    predecessor_task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    successor_task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    predecessor = relationship(
        "Task", foreign_keys=[predecessor_task_id], back_populates="blocking"
    )
    successor = relationship(
        "Task", foreign_keys=[successor_task_id], back_populates="blocked_by"
    )
