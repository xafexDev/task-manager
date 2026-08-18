"""Сервис пересчёта порядка задач при drag-and-drop.

Ключевая бизнес-логика: при перемещении задачи между/внутри колонок
API автоматически пересчитывает `order` остальных задач в затронутых колонках.

Подход:
- order — целое число, начинается с 0, шаг 1.
- При перемещении задачи:
  1. Удаляем задачу из старой колонки (если section_id изменился).
  2. Вставляем в новую позицию: сдвигаем все задачи с order >= target
     на +1 в целевой колонке.
  3. Перенумеровываем обе затронутые колонки (0, 1, 2, ...) для консистентности.
"""
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task


async def _renumber_section(db: AsyncSession, section_id: UUID) -> list[Task]:
    """Перенумеровывает все задачи в секции: 0, 1, 2, ...

    Возвращает обновлённый список задач (отсортированный по order).
    """
    result = await db.execute(
        select(Task)
        .where(Task.section_id == section_id)
        .order_by(Task.order, Task.created_at)
    )
    tasks = list(result.scalars().all())
    for new_order, task in enumerate(tasks):
        if task.order != new_order:
            task.order = new_order
    return tasks


async def move_task(
    db: AsyncSession,
    task: Task,
    new_section_id: UUID | None,
    new_order: int,
) -> dict[str, list[Task]]:
    """Перемещает задачу внутри/между секциями.

    Args:
        db: асинхронная сессия
        task: перемещаемая задача
        new_section_id: новая секция (None = остаться в текущей)
        new_order: новая позиция (целое >= 0)

    Returns:
        dict {"source_section": [...], "target_section": [...]} — обновлённые списки задач
        для рассылки клиентам (для обновления UI).
    """
    old_section_id = task.section_id
    target_section_id = new_section_id or old_section_id

    # 1. Если колонка сменилась — у задачи order временно -1, чтобы не мешать
    if target_section_id != old_section_id:
        task.order = -1
        await db.flush()

    # 2. Сдвигаем все задачи в целевой колонке с order >= new_order на +1
    await db.execute(
        update(Task)
        .where(
            Task.section_id == target_section_id,
            Task.order >= new_order,
        )
        .values(order=Task.order + 1)
    )
    await db.flush()

    # 3. Назначаем задаче новые значения
    task.section_id = target_section_id
    task.order = new_order
    await db.flush()

    # 4. Перенумеровываем целевую колонку
    target_tasks = await _renumber_section(db, target_section_id)

    # 5. Если колонка сменилась — перенумеровываем исходную
    if target_section_id != old_section_id:
        source_tasks = await _renumber_section(db, old_section_id)
    else:
        source_tasks = target_tasks

    return {
        "source_section": source_tasks,
        "target_section": target_tasks,
    }
