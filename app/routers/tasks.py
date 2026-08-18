"""Роутер Task: создание, список, детали, обновление, перемещение,
подзадачи, зависимости, комментарии, вложения, логи времени, история (activity log)."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, status, UploadFile, File
from sqlalchemy import select, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import ProjectRole, has_min_project_role
from app.core.ws_manager import ws_manager
from app.core.cursor import (
    CursorParams, CursorPage, CursorMeta,
    decode_cursor, encode_cursor, build_cursor_from_row,
    parse_cursor_time_str, parse_cursor_id,
)
from app.database import get_db
from app.dependencies import CurrentUser, PaginationDep
from app.models import (
    ActivityLog, Attachment, Comment, Project, ProjectMember, Subtask, Tag, Task, TaskDependency, TimeLog, User,
)
from app.routers.projects import _get_project_with_role, _require_editor_dep, _require_manager_dep
from app.schemas.common import (
    ActivityLogBrief, ActivityLogRead, AttachmentRead, CommentCreate, CommentRead, NotificationRead,
)
from app.schemas.project import TagBrief
from app.schemas.task import (
    DependencyCreate,
    DependencyRead,
    SubtaskCreate,
    SubtaskRead,
    SubtaskUpdate,
    TaskBrief,
    TaskCreate,
    TaskMove,
    TaskMoveResponse,
    TaskRead,
    TaskUpdate,
    TimeLogCreate,
    TimeLogRead,
)
from app.schemas.user import PaginatedMeta, UserRead
from app.services.activity import (
    log_attachment_created,
    log_comment_created,
    log_dependency_created,
    log_dependency_deleted,
    log_subtask_created,
    log_subtask_updated,
    log_task_assigned,
    log_task_completed,
    log_task_created,
    log_task_deleted,
    log_task_moved,
    log_task_unassigned,
    log_task_updated_field,
    log_timelog_created,
)
from app.services.dependencies import assert_no_cycle
from app.services.notification import (
    notify_assignment,
    notify_mentions,
)
from app.services.reorder import move_task as reorder_move_task
from app.services.storage import save_upload
from app.services.timelog import resolve_spent_seconds

router = APIRouter(tags=["Tasks"])


# -------- Создание задачи --------

@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создание задачи",
)
async def create_task(
    project_id: UUID,
    payload: TaskCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    project, role = await _get_project_with_role_with_db(project_id, user, db)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")

    # Проверка, что section принадлежит проекту
    from app.models import Section
    section = await db.get(Section, payload.section_id)
    if section is None or section.project_id != project_id:
        raise NotFoundError("Колонка не найдена в этом проекте")

    # Order = max + 1 в колонке
    from sqlalchemy import func
    max_order_q = await db.execute(
        select(func.max(Task.order)).where(Task.section_id == payload.section_id)
    )
    new_order = (max_order_q.scalar() or 0) + 1

    # Загружаем теги (если указаны)
    tags: list[Tag] = []
    if payload.tag_ids:
        result = await db.execute(select(Tag).where(Tag.id.in_(payload.tag_ids), Tag.project_id == project_id))
        tags = list(result.scalars().all())

    task = Task(
        project_id=project_id,
        section_id=payload.section_id,
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        reporter_id=user.id,
        priority=payload.priority,
        due_date=payload.due_date,
        order=new_order,
        tags=tags,
    )
    db.add(task)
    await db.flush()

    # Activity log: задача создана
    await log_task_created(db, task_id=task.id, user_id=user.id, task_title=task.title)

    # Уведомление о назначении
    if payload.assignee_id:
        await notify_assignment(
            db=db,
            assigner=user,
            assignee_id=payload.assignee_id,
            task_id=task.id,
            project_id=project_id,
            task_title=task.title,
        )
    # Уведомление об упоминании в описании
    if payload.description:
        await notify_mentions(
            db=db,
            text=payload.description,
            actor=user,
            task_id=task.id,
            project_id=project_id,
            context="описании задачи",
        )

    await db.commit()
    # Перезагружаем с предзагрузкой всех связей для TaskRead
    task = await _load_task_or_404(db, task.id)

    # WS broadcast
    await ws_manager.broadcast(project_id, "task.created", TaskBrief.model_validate(task).model_dump(mode="json"))

    return TaskRead.model_validate(task)


async def _get_project_with_role_with_db(
    project_id: UUID, user: CurrentUser, db: AsyncSession
) -> tuple[Project, ProjectRole]:
    """Внутренняя версия зависимости с явной передачей db."""
    from app.dependencies import load_project_or_404, get_project_role
    project = await load_project_or_404(db, project_id)
    role = await get_project_role(db, user.id, project_id)
    if role is None:
        raise ForbiddenError("Нет доступа к этому проекту")
    return project, role


# -------- Список задач проекта --------

@router.get(
    "/projects/{project_id}/tasks",
    summary="Список задач проекта (с фильтрацией и пагинацией)",
    description=(
        "Поддерживаемые query-параметры фильтрации: "
        "`section_id`, `assignee_id`, `priority`, `tag_id`, `is_completed`, "
        "`due_filter` (overdue/today/week)."
    ),
)
async def list_tasks(
    project_id: UUID,
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
    section_id: UUID | None = None,
    assignee_id: UUID | None = None,
    priority: str | None = None,
    tag_id: UUID | None = None,
    is_completed: bool | None = None,
    due_filter: str | None = None,
) -> dict:
    """Список задач проекта с фильтрацией и курсорной пагинацией.

    Сортировка: created_at DESC, id DESC (сначала новые).
    Курсор: base64(JSON({"created_at": ISO, "id": UUID})).
    """
    await _get_project_with_role_with_db(project_id, user, db)

    stmt = (
        select(Task)
        .where(Task.project_id == project_id)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.reporter),
            selectinload(Task.tags),
        )
    )

    if section_id:
        stmt = stmt.where(Task.section_id == section_id)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if is_completed is not None:
        stmt = stmt.where(Task.is_completed == is_completed)
    if tag_id:
        stmt = stmt.join(Task.tags).where(Tag.id == tag_id)
    if due_filter:
        now = datetime.now(timezone.utc)
        if due_filter == "overdue":
            stmt = stmt.where(Task.due_date < now, Task.is_completed.is_(False))
        elif due_filter == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(hour=23, minute=59, second=59)
            stmt = stmt.where(Task.due_date.between(start, end))
        elif due_filter == "week":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(day=start.day + 7)
            stmt = stmt.where(Task.due_date.between(start, end))

    # Курсор: фильтр по паре (created_at, id).
    # Сортировка: created_at DESC, id DESC → берём записи строго "меньше" курсора.
    cursor_time = parse_cursor_time_str(cursor_params.cursor, "created_at")
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_time and cursor_id_str:
        stmt = stmt.where(
            or_(
                Task.created_at < cursor_time,
                and_(
                    Task.created_at == cursor_time,
                    Task.id < cursor_id_str,
                ),
            )
        )

    stmt = stmt.order_by(desc(Task.created_at), desc(Task.id)).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    tasks = list(result.scalars().unique().all())

    has_next = len(tasks) > cursor_params.limit
    if has_next:
        tasks = tasks[: cursor_params.limit]

    next_cursor = None
    if has_next and tasks:
        last = tasks[-1]
        next_cursor = encode_cursor({
            "created_at": last.created_at.isoformat() if last.created_at else None,
            "id": str(last.id),
        })

    items = [TaskBrief.model_validate(t).model_dump(mode="json") for t in tasks]
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


# -------- Глобальный поиск --------

@router.get(
    "/tasks/search",
    summary="Глобальный поиск задач по title и description",
)
async def search_tasks(
    q: str,
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Глобальный поиск задач по title/description с курсорной пагинацией."""
    pattern = f"%{q}%"
    stmt = (
        select(Task)
        .join(ProjectMember, ProjectMember.project_id == Task.project_id)
        .where(
            ProjectMember.user_id == user.id,
            or_(Task.title.ilike(pattern), Task.description.ilike(pattern)),
        )
        .options(selectinload(Task.assignee), selectinload(Task.tags))
    )

    # Курсорная пагинация: сортировка по updated_at DESC, id DESC
    cursor_time = parse_cursor_time_str(cursor_params.cursor, "updated_at")
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_time and cursor_id_str:
        stmt = stmt.where(
            or_(
                Task.updated_at < cursor_time,
                and_(Task.updated_at == cursor_time, Task.id < cursor_id_str),
            )
        )

    stmt = stmt.order_by(desc(Task.updated_at), desc(Task.id)).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    tasks = list(result.scalars().unique().all())

    has_next = len(tasks) > cursor_params.limit
    if has_next:
        tasks = tasks[: cursor_params.limit]

    next_cursor = None
    if has_next and tasks:
        last = tasks[-1]
        next_cursor = encode_cursor({
            "updated_at": last.updated_at.isoformat() if last.updated_at else None,
            "id": str(last.id),
        })

    items = [TaskBrief.model_validate(t).model_dump(mode="json") for t in tasks]
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


# -------- Детали задачи --------

@router.get(
    "/tasks/{task_id}",
    response_model=TaskRead,
    summary="Детали задачи (включая подзадачи, теги)",
)
async def get_task(
    task_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    task = await _load_task_or_404(db, task_id)
    await _assert_task_access(db, task, user)
    return TaskRead.model_validate(task)


async def _load_task_or_404(db: AsyncSession, task_id: UUID) -> Task:
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.reporter),
            selectinload(Task.tags),
            selectinload(Task.subtasks),
        )
        .where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError("Задача не найдена")
    return task


async def _assert_task_access(db: AsyncSession, task: Task, user: CurrentUser) -> ProjectRole:
    """Проверяет, что пользователь — участник проекта задачи. Возвращает роль."""
    result = await db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == task.project_id,
            ProjectMember.user_id == user.id,
        )
    )
    role_str = result.scalar_one_or_none()
    if role_str is None:
        raise ForbiddenError("Нет доступа к этой задаче")
    return ProjectRole(role_str)


# -------- Обновление задачи --------

@router.put(
    "/tasks/{task_id}",
    response_model=TaskRead,
    summary="Обновление задачи (title, description, assignee, priority, ...)",
)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskRead:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")

    # Запоминаем старые значения для audit log
    old_title = task.title
    old_description = task.description
    old_priority = task.priority
    old_due_date = task.due_date
    old_is_completed = task.is_completed
    old_assignee = task.assignee_id
    old_tag_ids = {t.id for t in task.tags} if task.tags else set()

    # Применяем изменения
    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.is_completed is not None:
        task.is_completed = payload.is_completed
        task.completed_at = datetime.now(timezone.utc) if payload.is_completed else None
    if payload.assignee_id is not None and payload.assignee_id != old_assignee:
        task.assignee_id = payload.assignee_id
    if payload.tag_ids is not None:
        result = await db.execute(
            select(Tag).where(Tag.id.in_(payload.tag_ids), Tag.project_id == task.project_id)
        )
        task.tags = list(result.scalars().all())

    # ---- Activity Log: записываем только изменившиеся поля ----
    if payload.title is not None and payload.title != old_title:
        await log_task_updated_field(
            db, task_id=task.id, user_id=user.id, field="title",
            old_value=old_title, new_value=payload.title,
        )
    if payload.description is not None and payload.description != old_description:
        await log_task_updated_field(
            db, task_id=task.id, user_id=user.id, field="description",
            old_value=(old_description or "")[:80] + ("..." if old_description and len(old_description) > 80 else ""),
            new_value=payload.description[:80] + ("..." if len(payload.description) > 80 else ""),
        )
    if payload.priority is not None and payload.priority != old_priority:
        await log_task_updated_field(
            db, task_id=task.id, user_id=user.id, field="priority",
            old_value=old_priority, new_value=payload.priority,
        )
    if payload.due_date is not None and payload.due_date != old_due_date:
        await log_task_updated_field(
            db, task_id=task.id, user_id=user.id, field="due_date",
            old_value=old_due_date.isoformat() if old_due_date else None,
            new_value=payload.due_date.isoformat() if payload.due_date else None,
        )
    if payload.is_completed is not None and payload.is_completed != old_is_completed:
        await log_task_completed(
            db, task_id=task.id, user_id=user.id, completed=payload.is_completed,
        )
    if payload.assignee_id is not None and payload.assignee_id != old_assignee:
        if old_assignee is not None:
            await log_task_unassigned(
                db, task_id=task.id, user_id=user.id, prev_assignee_id=old_assignee,
            )
        # Загружаем нового исполнителя для username в логе
        new_assignee = await db.get(User, payload.assignee_id) if payload.assignee_id else None
        if new_assignee:
            await log_task_assigned(
                db, task_id=task.id, user_id=user.id,
                assignee_id=new_assignee.id, assignee_username=new_assignee.username,
            )
        # Уведомление о новом назначении
        await notify_assignment(
            db=db,
            assigner=user,
            assignee_id=payload.assignee_id,
            task_id=task.id,
            project_id=task.project_id,
            task_title=task.title,
        )
    if payload.tag_ids is not None:
        new_tag_ids = set(payload.tag_ids)
        if new_tag_ids != old_tag_ids:
            added = new_tag_ids - old_tag_ids
            removed = old_tag_ids - new_tag_ids
            await log_task_updated_field(
                db, task_id=task.id, user_id=user.id, field="tags",
                old_value=sorted(str(t) for t in old_tag_ids),
                new_value=sorted(str(t) for t in new_tag_ids),
            )
            # Также логируем add/remove как отдельные действия (для удобства фильтрации)
            if added:
                await log_task_updated_field(
                    db, task_id=task.id, user_id=user.id, field="tags_added",
                    old_value=None, new_value=sorted(str(t) for t in added),
                )
            if removed:
                await log_task_updated_field(
                    db, task_id=task.id, user_id=user.id, field="tags_removed",
                    old_value=sorted(str(t) for t in removed), new_value=None,
                )

    # Упоминания в обновлённом описании
    if payload.description:
        await notify_mentions(
            db=db,
            text=payload.description,
            actor=user,
            task_id=task.id,
            project_id=task.project_id,
            context="описании задачи",
        )

    await db.commit()
    project_id_for_broadcast = task.project_id
    task = await _load_task_or_404(db, task.id)
    await ws_manager.broadcast(
        project_id_for_broadcast, "task.updated",
        TaskBrief.model_validate(task).model_dump(mode="json"),
    )
    return TaskRead.model_validate(task)


# -------- Перемещение задачи (drag-and-drop) --------

@router.patch(
    "/tasks/{task_id}/move",
    response_model=TaskMoveResponse,
    summary="Перемещение задачи (изменение section_id и order)",
    description=(
        "API автоматически пересчитывает порядок остальных задач в затронутых "
        "колонках. Возвращает обновлённую задачу + словарь section_id -> список "
        "задач с обновлёнными order для UI-обновления."
    ),
)
async def move_task(
    task_id: UUID,
    payload: TaskMove,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TaskMoveResponse:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")

    # Запоминаем старые значения для audit log
    old_section_id = task.section_id
    old_order = task.order

    # Проверка новой секции
    if payload.section_id is not None and payload.section_id != task.section_id:
        from app.models import Section
        new_section = await db.get(Section, payload.section_id)
        if new_section is None or new_section.project_id != task.project_id:
            raise NotFoundError("Целевая колонка не найдена в этом проекте")

    affected = await reorder_move_task(
        db=db,
        task=task,
        new_section_id=payload.section_id,
        new_order=payload.order,
    )

    # Activity log: перемещение задачи
    await log_task_moved(
        db,
        task_id=task.id,
        user_id=user.id,
        from_section_id=old_section_id,
        to_section_id=task.section_id,
        from_order=old_order,
        to_order=task.order,
    )

    await db.commit()

    # Возвращаем обновлённые порядки для UI.
    # Если source == target, берём только один список, чтобы избежать дубликатов.
    affected_orders: dict[str, list[TaskBrief]] = {}
    source_tasks = affected.get("source_section", [])
    target_tasks = affected.get("target_section", [])
    # Если списки идентичны (та же секция) — берём только target
    if source_tasks is target_tasks or (
        source_tasks and target_tasks and source_tasks == target_tasks
    ):
        sections_to_process = [("target_section", target_tasks)]
    else:
        sections_to_process = [
            ("source_section", source_tasks),
            ("target_section", target_tasks),
        ]
    for _, tasks in sections_to_process:
        for t in tasks:
            section_key = str(t.section_id)
            # Не добавляем дубликат, если задача уже в списке этой секции
            existing_ids = {existing.id for existing in affected_orders.get(section_key, [])}
            if t.id not in existing_ids:
                affected_orders.setdefault(section_key, []).append(
                    TaskBrief.model_validate(t)
                )

    await ws_manager.broadcast(
        task.project_id,
        "task.moved",
        {
            "task_id": str(task.id),
            "section_id": str(task.section_id),
            "order": task.order,
            "affected": {k: [t.model_dump(mode="json") for t in v] for k, v in affected_orders.items()},
        },
    )

    return TaskMoveResponse(
        task=TaskBrief.model_validate(task),
        affected_orders=affected_orders,
    )


# -------- Удаление задачи --------

@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление задачи",
)
async def delete_task(
    task_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if role != ProjectRole.MANAGER:
        raise ForbiddenError("Только manager может удалять задачи")
    project_id = task.project_id
    task_title = task.title
    # Activity log ДО удаления (после cascading delete запись тоже удалится)
    await log_task_deleted(
        db, task_id=task_id, user_id=user.id, task_title=task_title,
    )
    await db.commit()
    await db.delete(task)
    await db.commit()
    await ws_manager.broadcast(project_id, "task.deleted", {"task_id": str(task_id)})


# -------- Подзадачи --------

@router.post(
    "/tasks/{task_id}/subtasks",
    response_model=SubtaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавление подзадачи",
)
async def create_subtask(
    task_id: UUID,
    payload: SubtaskCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SubtaskRead:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")
    subtask = Subtask(task_id=task_id, title=payload.title)
    db.add(subtask)
    await db.flush()

    # Activity log
    await log_subtask_created(
        db, task_id=task_id, user_id=user.id, subtask_title=payload.title,
    )

    await db.commit()
    await db.refresh(subtask)
    await ws_manager.broadcast(
        task.project_id,
        "subtask.created",
        {"task_id": str(task_id), "subtask": SubtaskRead.model_validate(subtask).model_dump(mode="json")},
    )
    return SubtaskRead.model_validate(subtask)


@router.patch(
    "/tasks/{task_id}/subtasks/{subtask_id}",
    response_model=SubtaskRead,
    summary="Обновление подзадачи",
)
async def update_subtask(
    task_id: UUID,
    subtask_id: UUID,
    payload: SubtaskUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SubtaskRead:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")
    subtask = await db.get(Subtask, subtask_id)
    if subtask is None or subtask.task_id != task_id:
        raise NotFoundError("Подзадача не найдена")
    changes: dict[str, Any] = {}
    if payload.title is not None and payload.title != subtask.title:
        changes["title"] = {"old": subtask.title, "new": payload.title}
        subtask.title = payload.title
    if payload.is_completed is not None and payload.is_completed != subtask.is_completed:
        changes["is_completed"] = {"old": subtask.is_completed, "new": payload.is_completed}
        subtask.is_completed = payload.is_completed

    # Activity log: изменения подзадачи
    if changes:
        await log_subtask_updated(
            db, task_id=task_id, user_id=user.id, subtask_id=subtask_id, changes=changes,
        )

    await db.commit()
    await db.refresh(subtask)
    await ws_manager.broadcast(
        task.project_id,
        "subtask.updated",
        {"task_id": str(task_id), "subtask": SubtaskRead.model_validate(subtask).model_dump(mode="json")},
    )
    return SubtaskRead.model_validate(subtask)


# -------- Зависимости --------

@router.post(
    "/tasks/{task_id}/dependencies",
    response_model=DependencyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Установка связи (блокирует/заблокировано)",
    description=(
        "Создаёт зависимость: задача `predecessor_task_id` блокирует задачу "
        "`task_id` (successor). Невозможно заблокировать задачу самой собой "
        "или создать циклическую зависимость."
    ),
)
async def create_dependency(
    task_id: UUID,
    payload: DependencyCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DependencyRead:
    successor = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, successor, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")

    # Проверка predecessor
    predecessor = await db.get(Task, payload.predecessor_task_id)
    if predecessor is None:
        raise NotFoundError("Предшествующая задача не найдена")
    if predecessor.project_id != successor.project_id:
        raise ForbiddenError("Задачи должны быть в одном проекте")
    if predecessor.id == successor.id:
        raise ConflictError("Невозможно заблокировать задачу самой собой")

    # Проверка цикла
    await assert_no_cycle(db, predecessor.id, successor.id)

    # Проверка дубликата
    existing = await db.execute(
        select(TaskDependency).where(
            TaskDependency.predecessor_task_id == predecessor.id,
            TaskDependency.successor_task_id == successor.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("Зависимость уже существует")

    dep = TaskDependency(
        predecessor_task_id=predecessor.id,
        successor_task_id=successor.id,
    )
    db.add(dep)
    await db.flush()

    # Activity log: на обе задачи (predecessor блокирует, successor заблокирована)
    await log_dependency_created(
        db, task_id=successor.id, user_id=user.id,
        predecessor_id=predecessor.id, successor_id=successor.id,
    )
    await log_dependency_created(
        db, task_id=predecessor.id, user_id=user.id,
        predecessor_id=predecessor.id, successor_id=successor.id,
    )

    await db.commit()
    await db.refresh(dep)
    await ws_manager.broadcast(
        successor.project_id,
        "dependency.created",
        DependencyRead.model_validate(dep).model_dump(mode="json"),
    )
    return DependencyRead.model_validate(dep)


@router.get(
    "/tasks/{task_id}/dependencies",
    summary="Список зависимостей задачи",
)
async def list_dependencies(
    task_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await _load_task_or_404(db, task_id)
    await _assert_task_access(db, task, user)
    blocking = await db.execute(
        select(TaskDependency).where(TaskDependency.predecessor_task_id == task_id)
    )
    blocked_by = await db.execute(
        select(TaskDependency).where(TaskDependency.successor_task_id == task_id)
    )
    return {
        "blocking": [DependencyRead.model_validate(d).model_dump(mode="json") for d in blocking.scalars().all()],
        "blocked_by": [DependencyRead.model_validate(d).model_dump(mode="json") for d in blocked_by.scalars().all()],
    }


@router.delete(
    "/tasks/{task_id}/dependencies/{dep_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удаление зависимости",
)
async def delete_dependency(
    task_id: UUID,
    dep_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")
    dep = await db.get(TaskDependency, dep_id)
    if dep is None or (dep.predecessor_task_id != task_id and dep.successor_task_id != task_id):
        raise NotFoundError("Зависимость не найдена")

    # Activity log
    await log_dependency_deleted(
        db, task_id=task_id, user_id=user.id, dep_id=dep_id,
    )

    await db.delete(dep)
    await db.commit()
    await ws_manager.broadcast(task.project_id, "dependency.deleted", {"dependency_id": dep_id})


# -------- Комментарии --------

@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить комментарий",
)
async def create_comment(
    task_id: UUID,
    payload: CommentCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommentRead:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")

    comment = Comment(task_id=task_id, user_id=user.id, text=payload.text)
    db.add(comment)
    await db.flush()

    # Activity log
    await log_comment_created(
        db, task_id=task.id, user_id=user.id,
        comment_id=comment.id, text_preview=payload.text,
    )

    # Уведомления об упоминаниях
    await notify_mentions(
        db=db,
        text=payload.text,
        actor=user,
        task_id=task.id,
        project_id=task.project_id,
        context="комментарии",
    )

    await db.commit()
    await db.refresh(comment)
    await ws_manager.broadcast(
        task.project_id,
        "comment.created",
        {"task_id": str(task_id), "comment": CommentRead.model_validate(comment).model_dump(mode="json")},
    )
    return CommentRead.model_validate(comment)


@router.get(
    "/tasks/{task_id}/comments",
    summary="Список комментариев задачи (курсорная пагинация)",
)
async def list_comments(
    task_id: UUID,
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await _load_task_or_404(db, task_id)
    await _assert_task_access(db, task, user)

    stmt = select(Comment).where(Comment.task_id == task_id)

    # Курсор: (created_at, id)
    cursor_time = parse_cursor_time_str(cursor_params.cursor, "created_at")
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_time and cursor_id_str:
        stmt = stmt.where(
            or_(
                Comment.created_at < cursor_time,
                and_(Comment.created_at == cursor_time, Comment.id < cursor_id_str),
            )
        )

    stmt = stmt.order_by(desc(Comment.created_at), desc(Comment.id)).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    has_next = len(items) > cursor_params.limit
    if has_next:
        items = items[: cursor_params.limit]

    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor({
            "created_at": last.created_at.isoformat() if last.created_at else None,
            "id": str(last.id),
        })

    items_dicts = [CommentRead.model_validate(c).model_dump(mode="json") for c in items]
    return CursorPage(
        items=items_dicts,
        meta=CursorMeta(
            limit=cursor_params.limit,
            has_next=has_next,
            has_prev=bool(cursor_params.cursor),
            next_cursor=next_cursor,
            prev_cursor=None,
        ),
    ).to_dict()


# -------- Вложения --------

@router.post(
    "/tasks/{task_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузка файла (multipart/form-data)",
    description=(
        "Загружает файл во вложения задачи. Максимальный размер и допустимые "
        "MIME-типы настраиваются через переменные окружения "
        "MAX_UPLOAD_SIZE_MB и ALLOWED_MIME_TYPES."
    ),
)
async def upload_attachment(
    task_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
) -> AttachmentRead:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")

    file_url, filename, file_size, mime_type = await save_upload(file)
    attachment = Attachment(
        task_id=task_id,
        uploader_id=user.id,
        filename=filename,
        file_url=file_url,
        file_size=file_size,
        mime_type=mime_type,
    )
    db.add(attachment)
    await db.flush()

    # Activity log
    await log_attachment_created(
        db, task_id=task_id, user_id=user.id,
        attachment_id=attachment.id, filename=filename,
    )

    await db.commit()
    await db.refresh(attachment)
    await ws_manager.broadcast(
        task.project_id,
        "attachment.created",
        {"task_id": str(task_id), "attachment": AttachmentRead.model_validate(attachment).model_dump(mode="json")},
    )
    return AttachmentRead.model_validate(attachment)


# -------- Логи времени --------

@router.post(
    "/tasks/{task_id}/timelogs",
    response_model=TimeLogRead,
    status_code=status.HTTP_201_CREATED,
    summary="Логирование времени",
    description=(
        "Принимает либо `spent_seconds` (целое), либо `spent_time` "
        "(например '1h 30m', '45m', '2h')."
    ),
)
async def create_timelog(
    task_id: UUID,
    payload: TimeLogCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TimeLogRead:
    task = await _load_task_or_404(db, task_id)
    role = await _assert_task_access(db, task, user)
    if not has_min_project_role(role, ProjectRole.EDITOR):
        raise ForbiddenError("Требуется роль editor или выше")
    spent = resolve_spent_seconds(payload.spent_seconds, payload.spent_time)
    log = TimeLog(
        task_id=task_id,
        user_id=user.id,
        spent_seconds=spent,
        description=payload.description,
    )
    db.add(log)
    await db.flush()

    # Activity log
    await log_timelog_created(
        db, task_id=task_id, user_id=user.id,
        timelog_id=log.id, spent_seconds=spent,
    )

    await db.commit()
    await db.refresh(log)
    return TimeLogRead.model_validate(log)


@router.get(
    "/tasks/{task_id}/timelogs",
    summary="Список логов времени по задаче (курсорная пагинация)",
)
async def list_timelogs(
    task_id: UUID,
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await _load_task_or_404(db, task_id)
    await _assert_task_access(db, task, user)

    stmt = select(TimeLog).where(TimeLog.task_id == task_id)

    # Курсор: (logged_at, id)
    cursor_time = parse_cursor_time_str(cursor_params.cursor, "logged_at")
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_time and cursor_id_str:
        stmt = stmt.where(
            or_(
                TimeLog.logged_at < cursor_time,
                and_(TimeLog.logged_at == cursor_time, TimeLog.id < cursor_id_str),
            )
        )

    stmt = stmt.order_by(desc(TimeLog.logged_at), desc(TimeLog.id)).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    has_next = len(items) > cursor_params.limit
    if has_next:
        items = items[: cursor_params.limit]

    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor({
            "logged_at": last.logged_at.isoformat() if last.logged_at else None,
            "id": str(last.id),
        })

    items_dicts = [TimeLogRead.model_validate(t).model_dump(mode="json") for t in items]
    return CursorPage(
        items=items_dicts,
        meta=CursorMeta(
            limit=cursor_params.limit,
            has_next=has_next,
            has_prev=bool(cursor_params.cursor),
            next_cursor=next_cursor,
            prev_cursor=None,
        ),
    ).to_dict()


# -------- История изменений задачи (Activity Log / audit log) --------

@router.get(
    "/tasks/{task_id}/activities",
    summary="История изменений задачи (audit log) с курсорной пагинацией",
    description=(
        "Возвращает список событий задачи (создание, обновления полей, "
        "перемещения, назначения, комментарии и т.д.) в обратном хронологическом "
        "порядке (сначала новые). Используется курсорная пагинация: передайте "
        "`cursor` из ответа `meta.next_cursor` для получения следующей страницы."
    ),
)
async def list_activities(
    task_id: UUID,
    user: CurrentUser,
    cursor_params: CursorParams = Depends(CursorParams.from_query),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await _load_task_or_404(db, task_id)
    await _assert_task_access(db, task, user)

    # Базовый запрос: все записи для данной задачи, от новых к старым
    stmt = select(ActivityLog).where(ActivityLog.task_id == task_id)

    # Курсор: для ActivityLog используем только int id (монотонно возрастает)
    cursor_id_str = parse_cursor_id(cursor_params.cursor)
    if cursor_id_str:
        try:
            cursor_id = int(cursor_id_str)
            stmt = stmt.where(ActivityLog.id < cursor_id)
        except (ValueError, TypeError):
            pass

    stmt = stmt.order_by(desc(ActivityLog.id)).limit(cursor_params.limit + 1)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    # +1 элемент нужен, чтобы понять, есть ли следующая страница
    has_next = len(items) > cursor_params.limit
    if has_next:
        items = items[: cursor_params.limit]

    # Формируем next_cursor из последнего элемента
    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor({"id": str(last.id)})

    items_dicts = [ActivityLogRead.model_validate(a).model_dump(mode="json") for a in items]
    return CursorPage(
        items=items_dicts,
        meta=CursorMeta(
            limit=cursor_params.limit,
            has_next=has_next,
            has_prev=bool(cursor_params.cursor),  # если пришёл курсор — значит есть предыдущая
            next_cursor=next_cursor,
            prev_cursor=None,
        ),
    ).to_dict()
