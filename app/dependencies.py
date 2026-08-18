"""Общие зависимости FastAPI: аутентификация, RBAC, пагинация."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.rbac import (
    GlobalRole,
    ProjectRole,
    can_view_project,
    has_min_global_role,
    has_min_project_role,
)
from app.core.security import decode_access_token
from app.database import get_db
from app.models import Project, ProjectMember, User, WorkspaceMember

# OAuth2 схема для Swagger UI
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Извлекает текущего пользователя из JWT-токена."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthorizedError("Требуется Bearer-токен")
    token = creds.credentials
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except Exception as exc:  # noqa: BLE001
        raise UnauthorizedError(f"Невалидный или просроченный токен: {exc}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError("Пользователь не найден")
    if user.status != "active":
        raise UnauthorizedError("Пользователь деактивирован")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# -------- Пагинация --------

class PaginationParams:
    """Параметры пагинации: limit + offset."""
    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Размер страницы (1-100)"),
        offset: int = Query(0, ge=0, description="Смещение от начала списка"),
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[PaginationParams, Depends()]


# -------- Workspace RBAC --------

async def get_workspace_role(
    db: AsyncSession, user_id: UUID, workspace_id: UUID
) -> GlobalRole:
    """Возвращает глобальную роль пользователя в workspace.

    Бросает ForbiddenError, если пользователь не является участником.
    """
    result = await db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    role_str = result.scalar_one_or_none()
    if role_str is None:
        raise ForbiddenError("Вы не являетесь участником этого workspace")
    return GlobalRole(role_str)


def require_global_role(*allowed: GlobalRole):
    """Декоратор-фабрика зависимостей: требует одну из перечисленных глобальных ролей."""
    async def _dep(
        user: CurrentUser,
        workspace_id: UUID = Query(..., description="ID workspace"),
        db: AsyncSession = Depends(get_db),
    ) -> tuple[User, GlobalRole]:
        role = await get_workspace_role(db, user.id, workspace_id)
        if role not in set(allowed):
            raise ForbiddenError(f"Требуется одна из ролей: {', '.join(r.value for r in allowed)}")
        return user, role
    return _dep


# -------- Project RBAC --------

async def get_project_role(
    db: AsyncSession, user_id: UUID, project_id: UUID
) -> ProjectRole | None:
    """Возвращает проектную роль пользователя или None, если он не участник."""
    result = await db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    role_str = result.scalar_one_or_none()
    return ProjectRole(role_str) if role_str else None


async def load_project_or_404(
    db: AsyncSession, project_id: UUID
) -> Project:
    """Загружает проект или бросает 404."""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.is_archived.is_(False))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError("Проект не найден")
    return project


async def require_project_member(
    project_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[Project, ProjectRole]:
    """Проверяет, что пользователь — участник проекта (любая роль, включая viewer)."""
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role is None or not can_view_project(role):
        raise ForbiddenError("Нет доступа к этому проекту")
    return project, role


async def require_project_editor(
    project_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[Project, ProjectRole]:
    """Требует минимум роль editor (создание/редактирование задач)."""
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role is None or not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")
    return project, role


async def require_project_manager(
    project_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> tuple[Project, ProjectRole]:
    """Требует роль manager (управление участниками, удаление)."""
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role is None or role != ProjectRole.MANAGER:
        raise ForbiddenError("Требуется роль manager")
    return project, role
