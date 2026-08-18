"""Роутер Workspace: создание, информация, приглашение, роли участников."""
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import GlobalRole, can_manage_workspace
from app.database import get_db
from app.dependencies import CurrentUser, PaginationDep
from app.models import User, Workspace, WorkspaceMember
from app.schemas.user import PaginatedMeta
from app.schemas.workspace import (
    InviteRequest,
    UpdateMemberRole,
    WorkspaceCreate,
    WorkspaceMemberRead,
    WorkspaceRead,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.get(
    "",
    summary="Список workspaces текущего пользователя",
    description="Возвращает все workspaces, где пользователь является участником.",
)
async def list_user_workspaces(
    user: CurrentUser,
    pagination: PaginationDep,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Получить список всех workspaces текущего пользователя."""
    # Получаем все членства пользователя
    memberships_q = await db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.desc())
    )
    memberships = memberships_q.scalars().all()
    
    # Получаем workspace ID
    workspace_ids = [m.workspace_id for m in memberships]
    
    if not workspace_ids:
        return {
            "items": [],
            "meta": PaginatedMeta(
                total=0,
                limit=pagination.limit,
                offset=pagination.offset,
                has_next=False,
            ).model_dump(),
        }
    
    # Получаем workspaces
    workspaces_q = await db.execute(
        select(Workspace)
        .where(Workspace.id.in_(workspace_ids))
        .order_by(Workspace.created_at.desc())
    )
    workspaces = workspaces_q.scalars().all()
    
    total = len(workspaces)
    page = workspaces[pagination.offset : pagination.offset + pagination.limit]
    
    return {
        "items": [WorkspaceRead.model_validate(ws) for ws in page],
        "meta": PaginatedMeta(
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
            has_next=pagination.offset + pagination.limit < total,
        ).model_dump(),
    }


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создание workspace",
    description="Создаёт новый workspace. Текущий пользователь становится owner.",
)
async def create_workspace(
    payload: WorkspaceCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceRead:
    ws = Workspace(name=payload.name, owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=GlobalRole.OWNER.value))
    await db.commit()
    await db.refresh(ws)
    return WorkspaceRead.model_validate(ws)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceRead,
    summary="Информация о workspace",
)
async def get_workspace(
    workspace_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceRead:
    ws = await db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("Workspace не найден")
    # Проверка участия
    membership = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise ForbiddenError("Вы не участник этого workspace")
    return WorkspaceRead.model_validate(ws)


@router.get(
    "/{workspace_id}/members",
    summary="Список участников workspace",
)
async def list_workspace_members(
    workspace_id: UUID,
    user: CurrentUser,
    pagination: PaginationDep,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Проверка участия текущего пользователя
    membership = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise ForbiddenError("Вы не участник этого workspace")

    total_q = await db.execute(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    )
    all_members = total_q.scalars().all()
    total = len(all_members)
    page = all_members[pagination.offset : pagination.offset + pagination.limit]
    return {
        "items": [WorkspaceMemberRead.model_validate(m) for m in page],
        "meta": PaginatedMeta(
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
            has_next=pagination.offset + pagination.limit < total,
        ).model_dump(),
    }


@router.post(
    "/{workspace_id}/invite",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Приглашение пользователя по email",
    description=(
        "Добавляет пользователя в workspace по email. Текущий пользователь "
        "должен иметь роль owner или admin."
    ),
)
async def invite_user(
    workspace_id: UUID,
    payload: InviteRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceMemberRead:
    ws = await db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("Workspace не найден")

    # Проверка прав приглашающего
    inviter_membership = await db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    inviter_role_str = inviter_membership.scalar_one_or_none()
    if inviter_role_str is None:
        raise ForbiddenError("Вы не участник этого workspace")
    if not can_manage_workspace(GlobalRole(inviter_role_str)):
        raise ForbiddenError("Требуется роль admin или owner для приглашения")

    # Поиск пользователя по email
    target = await db.execute(select(User).where(User.email == payload.email))
    target_user = target.scalar_one_or_none()
    if target_user is None:
        raise NotFoundError(f"Пользователь с email {payload.email} не найден")

    # Проверка, что он ещё не участник
    existing = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("Пользователь уже является участником workspace")

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=payload.role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return WorkspaceMemberRead.model_validate(member)


@router.put(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberRead,
    summary="Изменение роли участника workspace",
)
async def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRole,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceMemberRead:
    # Проверка прав текущего пользователя
    actor_membership = await db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    actor_role_str = actor_membership.scalar_one_or_none()
    if actor_role_str is None:
        raise ForbiddenError("Вы не участник этого workspace")
    if not can_manage_workspace(GlobalRole(actor_role_str)):
        raise ForbiddenError("Требуется роль admin или owner")

    # Целевой участник
    target = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = target.scalar_one_or_none()
    if member is None:
        raise NotFoundError("Участник не найден")
    if member.role == GlobalRole.OWNER.value:
        raise ForbiddenError("Нельзя изменить роль владельца workspace")
    member.role = payload.role
    await db.commit()
    await db.refresh(member)
    return WorkspaceMemberRead.model_validate(member)
