"""Тесты пересчёта порядка задач при drag-and-drop.

ТЗ-сценарий: Перемещение задачи из Section A в Section B
меняет order у задач в обеих колонках.
"""
import pytest

from tests.conftest import (
    auth_headers, create_project, create_section, create_task, register_user,
)


async def _setup_project_with_sections(client):
    """Создаёт workspace, проект и 2 колонки с задачами. Возвращает контекст."""
    owner = await register_user(client, email="drag@example.com", username="drag")
    workspace_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Drag WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    workspace_id = workspace_resp.json()["id"]
    project = await create_project(client, owner["access_token"], workspace_id, "Drag Project")
    project_id = project["id"]

    section_a = await create_section(client, owner["access_token"], project_id, "Backlog")
    section_b = await create_section(client, owner["access_token"], project_id, "Done")

    return {
        "token": owner["access_token"],
        "project_id": project_id,
        "section_a": section_a,
        "section_b": section_b,
    }


@pytest.mark.asyncio
async def test_move_task_within_same_section_reorders(client):
    """Перемещение задачи внутри колонки пересчитывает order остальных."""
    ctx = await _setup_project_with_sections(client)
    section_id = ctx["section_a"]["id"]

    # Создаём 3 задачи в колонке A
    t1 = await create_task(client, ctx["token"], section_id, "T1", project_id=ctx["project_id"])
    t2 = await create_task(client, ctx["token"], section_id, "T2", project_id=ctx["project_id"])
    t3 = await create_task(client, ctx["token"], section_id, "T3", project_id=ctx["project_id"])

    # Изначально: T1 (order=1), T2 (order=2), T3 (order=3)
    # Перемещаем T3 в начало (order=0)
    resp = await client.patch(
        f"/api/v1/tasks/{t3['id']}/move",
        json={"section_id": section_id, "order": 0},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # T3 должна быть первой
    assert body["task"]["order"] == 0

    # В affected_orders должны быть задачи с обновлёнными order
    affected = body["affected_orders"]
    section_key = section_id
    assert section_key in affected
    orders = [t["order"] for t in affected[section_key]]
    # Должны быть 0, 1, 2 (без пропусков и дубликатов)
    assert sorted(orders) == [0, 1, 2], f"Expected [0,1,2], got {sorted(orders)}"


@pytest.mark.asyncio
async def test_move_task_between_sections_reorders_both(client):
    """ТЗ-сценарий: перемещение из A в B меняет order в обеих колонках."""
    ctx = await _setup_project_with_sections(client)
    section_a = ctx["section_a"]["id"]
    section_b = ctx["section_b"]["id"]

    # В A: 3 задачи, в B: 2 задачи
    ta1 = await create_task(client, ctx["token"], section_a, "A1", project_id=ctx["project_id"])
    ta2 = await create_task(client, ctx["token"], section_a, "A2", project_id=ctx["project_id"])
    ta3 = await create_task(client, ctx["token"], section_a, "A3", project_id=ctx["project_id"])
    tb1 = await create_task(client, ctx["token"], section_b, "B1", project_id=ctx["project_id"])
    tb2 = await create_task(client, ctx["token"], section_b, "B2", project_id=ctx["project_id"])

    # Перемещаем ta2 (из A) в B на позицию 0
    resp = await client.patch(
        f"/api/v1/tasks/{ta2['id']}/move",
        json={"section_id": section_b, "order": 0},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Проверяем, что affected_orders содержит обе секции
    affected = body["affected_orders"]
    assert section_a in affected, "Source section should be in affected_orders"
    assert section_b in affected, "Target section should be in affected_orders"

    # В колонке A теперь 2 задачи с order 0, 1
    orders_a = sorted(t["order"] for t in affected[section_a])
    assert orders_a == [0, 1], f"Source orders should be [0,1], got {orders_a}"

    # В колонке B теперь 3 задачи с order 0, 1, 2
    orders_b = sorted(t["order"] for t in affected[section_b])
    assert orders_b == [0, 1, 2], f"Target orders should be [0,1,2], got {orders_b}"

    # Перемещённая задача должна быть в B с order=0
    moved_task_ids_b = [t["id"] for t in affected[section_b]]
    assert ta2["id"] in moved_task_ids_b


@pytest.mark.asyncio
async def test_move_task_to_end_of_section(client):
    """Перемещение задачи в конец колонки работает корректно."""
    ctx = await _setup_project_with_sections(client)
    section_id = ctx["section_a"]["id"]

    t1 = await create_task(client, ctx["token"], section_id, "T1", project_id=ctx["project_id"])
    t2 = await create_task(client, ctx["token"], section_id, "T2", project_id=ctx["project_id"])
    t3 = await create_task(client, ctx["token"], section_id, "T3", project_id=ctx["project_id"])

    # Перемещаем t1 в конец (order=2, но это уже позиция t3)
    # Корректный order=2 или больше → t1 уходит в конец
    resp = await client.patch(
        f"/api/v1/tasks/{t1['id']}/move",
        json={"section_id": section_id, "order": 5},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    affected = body["affected_orders"]
    orders = sorted(t["order"] for t in affected[section_id])
    assert orders == [0, 1, 2], f"Expected [0,1,2] after renormalization, got {orders}"


@pytest.mark.asyncio
async def test_orders_no_duplicates_after_move(client):
    """После перемещения не должно быть дубликатов order в колонке."""
    ctx = await _setup_project_with_sections(client)
    section_id = ctx["section_a"]["id"]

    tasks = [
        await create_task(client, ctx["token"], section_id, f"T{i}", project_id=ctx["project_id"])
        for i in range(5)
    ]

    # Перемещаем последнюю задачу в середину (order=2)
    last_task = tasks[-1]
    resp = await client.patch(
        f"/api/v1/tasks/{last_task['id']}/move",
        json={"section_id": section_id, "order": 2},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200

    # Получаем список задач колонки через API
    list_resp = await client.get(
        f"/api/v1/projects/{ctx['project_id']}/tasks?section_id={section_id}",
        headers=await auth_headers(ctx["token"]),
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    orders = [t["order"] for t in items]
    # Не должно быть дубликатов
    assert len(orders) == len(set(orders)), f"Duplicate orders detected: {orders}"
    # Должны быть 0..4
    assert sorted(orders) == [0, 1, 2, 3, 4], f"Expected [0,1,2,3,4], got {sorted(orders)}"
