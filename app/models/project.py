"""Модели Project, ProjectMember, Section (колонка Канбана), Tag."""
import uuid
from datetime import datetime

from sqlalchemy import (
    String, Text, Boolean, Integer, ForeignKey, DateTime, func, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import UUIDType


class Project(Base):
    """Проект внутри workspace."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace = relationship("Workspace", back_populates="projects")
    members = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
    sections = relationship(
        "Section", back_populates="project", cascade="all, delete-orphan",
        order_by="Section.order",
    )
    tasks = relationship(
        "Task", back_populates="project", cascade="all, delete-orphan"
    )
    tags = relationship(
        "Tag", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project {self.name}>"


class ProjectMember(Base):
    """Связь User ↔ Project с проектной ролью."""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="editor", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_memberships")


class Section(Base):
    """Колонка Канбан-доски (Section/Board)."""

    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)

    project = relationship("Project", back_populates="sections")
    tasks = relationship(
        "Task", back_populates="section", cascade="all, delete-orphan",
        order_by="Task.order",
    )


class Tag(Base):
    """Метка/ярлык задачи в рамках проекта."""

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#6B7280", nullable=False)

    project = relationship("Project", back_populates="tags")
