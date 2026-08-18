"""Ролевая модель доступа (RBAC).

Глобальные роли (в рамках Workspace):
- owner  — полный доступ, биллинг, удаление организации
- admin  — управление пользователями, создание проектов
- member — базовый доступ
- guest  — доступ только к явно приглашённым проектам

Проектные роли (в рамках Project):
- manager — редактирование настроек проекта, участники, статусы
- editor  — создание/редактирование задач, комментарии, файлы
- viewer  — только просмотр
"""
from enum import Enum
from typing import Iterable


class GlobalRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class ProjectRole(str, Enum):
    MANAGER = "manager"
    EDITOR = "editor"
    VIEWER = "viewer"


# Иерархия глобальных ролей: индекс = уровень прав
_GLOBAL_ROLE_LEVEL: dict[GlobalRole, int] = {
    GlobalRole.GUEST: 0,
    GlobalRole.MEMBER: 1,
    GlobalRole.ADMIN: 2,
    GlobalRole.OWNER: 3,
}

_PROJECT_ROLE_LEVEL: dict[ProjectRole, int] = {
    ProjectRole.VIEWER: 0,
    ProjectRole.EDITOR: 1,
    ProjectRole.MANAGER: 2,
}


def has_global_role(user_role: GlobalRole, required: Iterable[GlobalRole]) -> bool:
    """Проверяет, что глобальная роль пользователя входит в список разрешённых."""
    return user_role in set(required)


def has_min_global_role(user_role: GlobalRole, min_role: GlobalRole) -> bool:
    """Проверяет, что глобальная роль пользователя >= требуемой."""
    return _GLOBAL_ROLE_LEVEL[user_role] >= _GLOBAL_ROLE_LEVEL[min_role]


def has_min_project_role(user_role: ProjectRole, min_role: ProjectRole) -> bool:
    """Проверяет, что проектная роль пользователя >= требуемой."""
    return _PROJECT_ROLE_LEVEL[user_role] >= _PROJECT_ROLE_LEVEL[min_role]


def can_create_project(user_global_role: GlobalRole) -> bool:
    """Создавать проекты могут owner/admin (не member/guest)."""
    return has_min_global_role(user_global_role, GlobalRole.ADMIN)


def can_manage_workspace(user_global_role: GlobalRole) -> bool:
    """Управлять настройками workspace могут owner/admin."""
    return has_min_global_role(user_global_role, GlobalRole.ADMIN)


def can_manage_project_members(project_role: ProjectRole) -> bool:
    """Управлять участниками проекта может только manager."""
    return project_role == ProjectRole.MANAGER


def can_edit_task(project_role: ProjectRole) -> bool:
    """Создавать/редактировать задачи могут manager/editor."""
    return has_min_project_role(project_role, ProjectRole.EDITOR)


def can_delete_task(project_role: ProjectRole) -> bool:
    """Удалять задачи может только manager."""
    return project_role == ProjectRole.MANAGER


def can_view_project(project_role: ProjectRole | None) -> bool:
    """Просмотр проекта доступен всем участникам (включая viewer)."""
    return project_role is not None
