"""Сервис проверки циклических зависимостей между задачами."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models import TaskDependency


async def would_create_cycle(
    db: AsyncSession, predecessor_id: UUID, successor_id: UUID
) -> bool:
    """Проверяет, создаст ли новая зависимость (predecessor -> successor) цикл.

    Идея: если из successor можно дойти до predecessor по существующим
    связям predecessor -> successor, то добавление predecessor -> successor
    замкнёт цикл.

    Алгоритм: BFS по рёбрам (предшественник -> преемник), начиная от successor.
    Если встретим predecessor — цикл.
    """
    if predecessor_id == successor_id:
        return True  # задача не может блокировать сама себя

    visited: set[UUID] = set()
    queue: list[UUID] = [successor_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        # Находим всех преемников current (current -> X)
        result = await db.execute(
            select(TaskDependency.successor_task_id).where(
                TaskDependency.predecessor_task_id == current
            )
        )
        for (succ_id,) in result.all():
            if succ_id == predecessor_id:
                return True
            queue.append(succ_id)
    return False


async def assert_no_cycle(
    db: AsyncSession, predecessor_id: UUID, successor_id: UUID
) -> None:
    """Бросает ConflictError, если добавление связи создаст цикл."""
    if await would_create_cycle(db, predecessor_id, successor_id):
        raise ConflictError(
            "Невозможно создать зависимость: обнаружена циклическая зависимость"
        )
