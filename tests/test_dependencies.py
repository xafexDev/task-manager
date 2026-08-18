"""Тесты зависимостей между задачами.

ТЗ-сценарий: Невозможно заблокировать задачу самой собой (циклическая зависимость).
Также: невозможно создать цикл A→B→C→A.
"""
import pytest

from tests.conftest import (
    auth_headers, create_project, create_section, create_task, register_user,
)


async def _setup_project_with_tasks(client, n_tasks: int = 3):
    """Создаёт проект и N задач в одной колонке."""
    owner = await register_user(client, email="deps@example.com", username="deps")
    workspace_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Deps WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    workspace_id = workspace_resp.json()["id"]
    project = await create_project(client, owner["access_token"], workspace_id, "Deps Project")
    project_id = project["id"]
    section = await create_section(client, owner["access_token"], project_id, "To Do")
    tasks = [
        await create_task(client, owner["access_token"], section["id"], f"Task {i}",
                          project_id=project_id)
        for i in range(n_tasks)
    ]
    return {
        "token": owner["access_token"],
        "project_id": project_id,
        "section": section,
        "tasks": tasks,
    }


@pytest.mark.asyncio
async def test_cannot_block_task_by_itself(client):
    """ТЗ-сценарий: Невозможно заблокировать задачу самой собой."""
    ctx = await _setup_project_with_tasks(client, n_tasks=1)
    task_id = ctx["tasks"][0]["id"]

    resp = await client.post(
        f"/api/v1/tasks/{task_id}/dependencies",
        json={"predecessor_task_id": task_id},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 409, f"Self-dependency should be 409, got {resp.status_code}: {resp.text}"
    assert "самой собой" in resp.json()["detail"] or "циклическ" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_can_create_simple_dependency(client):
    """Можно создать простую зависимость A → B (A блокирует B)."""
    ctx = await _setup_project_with_tasks(client, n_tasks=2)
    task_a, task_b = ctx["tasks"]

    # A блокирует B: на эндпоинте задачи B указываем predecessor=A
    resp = await client.post(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["predecessor_task_id"] == task_a["id"]
    assert body["successor_task_id"] == task_b["id"]


@pytest.mark.asyncio
async def test_cannot_create_cycle_3_tasks(client):
    """Невозможно создать цикл A→B→C→A."""
    ctx = await _setup_project_with_tasks(client, n_tasks=3)
    task_a, task_b, task_c = ctx["tasks"]

    # Создаём A→B и B→C
    r1 = await client.post(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert r1.status_code == 201

    r2 = await client.post(
        f"/api/v1/tasks/{task_c['id']}/dependencies",
        json={"predecessor_task_id": task_b["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert r2.status_code == 201

    # Пытаемся создать C→A (замыкает цикл)
    r3 = await client.post(
        f"/api/v1/tasks/{task_a['id']}/dependencies",
        json={"predecessor_task_id": task_c["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert r3.status_code == 409, f"Cycle should be 409, got {r3.status_code}: {r3.text}"
    assert "цикл" in r3.json()["detail"].lower() or "cycle" in r3.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_create_duplicate_dependency(client):
    """Нельзя создать дубликат зависимости."""
    ctx = await _setup_project_with_tasks(client, n_tasks=2)
    task_a, task_b = ctx["tasks"]

    r1 = await client.post(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert r1.status_code == 201

    r2 = await client.post(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_dependency_must_be_in_same_project(client):
    """Зависимость можно создать только между задачами одного проекта."""
    # Создаём два разных проекта с задачами
    owner = await register_user(client, email="cross@example.com", username="cross")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Cross WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    workspace_id = ws_resp.json()["id"]

    proj1 = await create_project(client, owner["access_token"], workspace_id, "P1")
    proj2 = await create_project(client, owner["access_token"], workspace_id, "P2")
    sec1 = await create_section(client, owner["access_token"], proj1["id"])
    sec2 = await create_section(client, owner["access_token"], proj2["id"])
    task1 = await create_task(client, owner["access_token"], sec1["id"], "T1", project_id=proj1["id"])
    task2 = await create_task(client, owner["access_token"], sec2["id"], "T2", project_id=proj2["id"])

    # Пытаемся создать зависимость между задачами разных проектов
    resp = await client.post(
        f"/api/v1/tasks/{task2['id']}/dependencies",
        json={"predecessor_task_id": task1["id"]},
        headers=await auth_headers(owner["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_dependencies(client):
    """GET /tasks/{id}/dependencies возвращает blocking и blocked_by."""
    ctx = await _setup_project_with_tasks(client, n_tasks=3)
    task_a, task_b, task_c = ctx["tasks"]

    # A→B, A→C (A блокирует B и C)
    await client.post(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    await client.post(
        f"/api/v1/tasks/{task_c['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )

    # У task_a: blocking = [B, C], blocked_by = []
    resp = await client.get(
        f"/api/v1/tasks/{task_a['id']}/dependencies",
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["blocking"]) == 2
    assert len(body["blocked_by"]) == 0

    # У task_b: blocking = [], blocked_by = [A]
    resp_b = await client.get(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        headers=await auth_headers(ctx["token"]),
    )
    body_b = resp_b.json()
    assert len(body_b["blocking"]) == 0
    assert len(body_b["blocked_by"]) == 1
    assert body_b["blocked_by"][0]["predecessor_task_id"] == task_a["id"]
