"""Модель ActivityLog — история изменений задачи (audit log).

Каждое значимое действие с задачей (создание, обновление полей, перемещение,
смена исполнителя, добавление комментария/вложения/лога времени и т.д.)
записывается как отдельная строка в этой таблице.

Это позволяет:
- Показывать пользователю историю изменений задачи (timeline)
- Решать споры «кто и когда изменил X»
- Соответствовать требованиям аудита критичных операций
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import UUIDType


class ActivityLog(Base):
    """Запись в истории изменений задачи."""

    __tablename__ = "activity_logs"
    __table_args__ = (
        # Составной индекс для быстрого получения истории задачи по created_at
        # (нам нужен порядок "сначала новые" — индекс на (task_id, created_at DESC))
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Тип действия: task.created, task.updated, task.moved, task.deleted,
    #               task.assigned, task.unassigned, task.completed,
    #               subtask.created, subtask.updated,
    #               comment.created, attachment.created, timelog.created,
    #               dependency.created, dependency.deleted
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Человекочитаемое описание: "Изменил заголовок с 'X' на 'Y'"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-строка с детальным контекстом (field, old_value, new_value, ...)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    task = relationship("Task")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<ActivityLog #{self.id} task={self.task_id} action={self.action}>"
