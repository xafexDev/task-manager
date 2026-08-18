"""Роутер Project: создание, список, детали, участники, секции, теги."""
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import GlobalRole, ProjectRole, can_create_project, has_min_project_role
from app.core.cursor import (
    CursorParams, CursorPage, CursorMeta,
    decode_cursor, encode_cursor,
    parse_cursor_time_str, parse_cursor_id,
)
from app.database import get_db
from app.dependencies import (
    CurrentUser,
    PaginationDep,
    get_project_role,
    get_workspace_role,
    load_project_or_404,
)
from app.models import (
    Project, ProjectMember, Section, Tag, WorkspaceMember,
)
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectRead,
    ProjectUpdate,
    SectionCreate,
    SectionRead,
    SectionUpdate,
    TagCreate,
    TagRead,
)
from app.schemas.user import PaginatedMeta

router = APIRouter(prefix="/projects", tags=["Projects"])


# ============================================================
# Вспомогательные зависимости (определены ПЕРВЫМИ, до использования)
# ============================================================

async def _get_project_with_role(
    project_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> tuple[Project, ProjectRole]:
    """Загружает проект и проверяет, что пользователь — участник (любая роль)."""
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role is None:
        raise ForbiddenError("Нет доступа к этому проекту")
    return project, role


async def _require_editor_dep(
    project_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> tuple[Project, ProjectRole]:
    """Требует минимум роль editor (создание/редактирование задач)."""
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role is None or not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")
    return project, role


async def _require_manager_dep(
    project_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> tuple[Project, ProjectRole]:
    """Требует роль manager для операций над проектом."""
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role != ProjectRole.MANAGER:
        raise ForbiddenError("Требуется роль manager")
    return project, role


# ============================================================
# Проекты
# ============================================================

@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создание проекта",
    description=(
        "Создаёт новый проект в указанном workspace. Текущий пользователь "
        "становится manager проекта. Требуется глобальная роль admin или owner. "
        "Guest и Member не могут создавать проекты."
    ),
)
async def create_project(
    payload: ProjectCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    ws_role = await get_workspace_role(db, user.id, payload.workspace_id)
    if not can_create_project(ws_role):
        raise ForbiddenError(
            "Создавать проекты могут только admin или owner workspace. "
            "Роль Guest/Member не может создавать проекты."
        )

    project = Project(
        workspace_id=payload.workspace_id,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        color=payload.color,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=ProjectRole.MANAGER.value,
    ))
    await db.commit()
    await db.refresh(project)
    return ProjectRead.model_validate(project)


@router.get(
    "",
    summary="Список доступных проектов",
    description=(
        "Возвращает проекты, в которых текущий пользователь является участником. "
        "Гости видят только явно доступные им проекты."
    ),
)
async def list_projects(
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Список доступных проектов (курсорная пагинация, сортировка created_at DESC)."""
    from sqlalchemy import or_, and_, desc
    from datetime import datetime

    stmt = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectMember.user_id == user.id,
            Project.is_archived.is_(False),
        )
    )

    # Курсор: (created_at, id)
    cursor_time = parse_cursor_time_str(cursor_params.cursor, "created_at")
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_time and cursor_id_str:
        stmt = stmt.where(
            or_(
                Project.created_at < cursor_time,
                and_(Project.created_at == cursor_time, Project.id < cursor_id_str),
            )
        )

    stmt = stmt.order_by(desc(Project.created_at), desc(Project.id)).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    projects = list(result.scalars().unique().all())

    has_next = len(projects) > cursor_params.limit
    if has_next:
        projects = projects[: cursor_params.limit]

    next_cursor = None
    if has_next and projects:
        last = projects[-1]
        next_cursor = encode_cursor({
            "created_at": last.created_at.isoformat() if last.created_at else None,
            "id": str(last.id),
        })

    items = [ProjectRead.model_validate(p).model_dump(mode="json") for p in projects]
    return CursorPage(
        items=items,
        meta=CursorMeta(
            limit=cursor_params.limit,
            has_next=has_next,
            has_prev=bool(cursor_params.cursor),
            next_cursor=next_cursor,
            prev_cursor=None,
        ),
    ).to_dict()


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Детали проекта",
)
async def get_project(
    project_role: tuple[Project, ProjectRole] = Depends(_get_project_with_role),
) -> ProjectRead:
    project, _ = project_role
    return ProjectRead.model_validate(project)


@router.put(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Обновление настроек проекта (manager)",
)
async def update_project(
    payload: ProjectUpdate,
    project_role: tuple[Project, ProjectRole] = Depends(_require_manager_dep),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    project, _ = project_role
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return ProjectRead.model_validate(project)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавление участника в проект (manager)",
    description=(
        "Только manager может добавлять участников. Пользователь должен быть "
        "участником workspace."
    ),
)
async def add_project_member(
    payload: ProjectMemberAdd,
    project_role: tuple[Project, ProjectRole] = Depends(_require_manager_dep),
    db: AsyncSession = Depends(get_db),
) -> ProjectMemberRead:
    project, _ = project_role
    # Проверка, что целевой пользователь — участник workspace
    ws_membership = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == project.workspace_id,
            WorkspaceMember.user_id == payload.user_id,
        )
    )
    if ws_membership.scalar_one_or_none() is None:
        raise ForbiddenError(
            "Пользователь должен быть участником workspace, чтобы быть добавленным в проект"
        )
    # Проверка, что он ещё не участник проекта
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == payload.user_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("Пользователь уже является участником проекта")

    member = ProjectMember(
        project_id=project.id,
        user_id=payload.user_id,
        role=payload.role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return ProjectMemberRead.model_validate(member)


# ============================================================
# Секции (колонки Канбана)
# ============================================================

@router.post(
    "/{project_id}/sections",
    response_model=SectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создание колонки (Section)",
)
async def create_section(
    payload: SectionCreate,
    project_role: tuple[Project, ProjectRole] = Depends(_require_editor_dep),
    db: AsyncSession = Depends(get_db),
) -> SectionRead:
    project, _ = project_role
    max_order_q = await db.execute(
        select(func.max(Section.order)).where(Section.project_id == project.id)
    )
    max_order = max_order_q.scalar() or 0
    section = Section(
        project_id=project.id,
        name=payload.name,
        type=payload.type,
        order=max_order + 1,
    )
    db.add(section)
    await db.commit()
    await db.refresh(section)
    return SectionRead.model_validate(section)


@router.put(
    "/{project_id}/sections/{section_id}",
    response_model=SectionRead,
    summary="Переименование/смена порядка колонки",
)
async def update_section(
    section_id: UUID,
    payload: SectionUpdate,
    project_role: tuple[Project, ProjectRole] = Depends(_require_editor_dep),
    db: AsyncSession = Depends(get_db),
) -> SectionRead:
    project, _ = project_role
    section = await db.get(Section, section_id)
    if section is None or section.project_id != project.id:
        raise NotFoundError("Колонка не найдена")
    if payload.name is not None:
        section.name = payload.name
    if payload.order is not None:
        section.order = payload.order
    await db.commit()
    await db.refresh(section)
    return SectionRead.model_validate(section)


@router.get(
    "/{project_id}/sections",
    response_model=list[SectionRead],
    summary="Список секций проекта",
)
async def list_sections(
    project_role: tuple[Project, ProjectRole] = Depends(_get_project_with_role),
    db: AsyncSession = Depends(get_db),
) -> list[SectionRead]:
    project, _ = project_role
    result = await db.execute(
        select(Section).where(Section.project_id == project.id).order_by(Section.order)
    )
    return [SectionRead.model_validate(s) for s in result.scalars().all()]


# ============================================================
# Теги
# ============================================================

@router.post(
    "/{project_id}/tags",
    response_model=TagRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создание тега в проекте",
)
async def create_tag(
    payload: TagCreate,
    project_role: tuple[Project, ProjectRole] = Depends(_require_editor_dep),
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    project, _ = project_role
    tag = Tag(project_id=project.id, name=payload.name, color=payload.color)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return TagRead.model_validate(tag)


@router.get(
    "/{project_id}/tags",
    response_model=list[TagRead],
    summary="Список тегов проекта",
)
async def list_tags(
    project_role: tuple[Project, ProjectRole] = Depends(_get_project_with_role),
    db: AsyncSession = Depends(get_db),
) -> list[TagRead]:
    project, _ = project_role
    result = await db.execute(
        select(Tag).where(Tag.project_id == project.id).order_by(Tag.name)
    )
    return [TagRead.model_validate(t) for t in result.scalars().all()]
