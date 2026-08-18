"""Тесты эндпоинтов задач: создание, получение, обновление, фильтрация, пагинация."""
import pytest

from tests.conftest import (
    auth_headers, create_project, create_section, create_task, register_user,
)


async def _setup(client):
    owner = await register_user(client, email="task@example.com", username="task")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Task WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    workspace_id = ws_resp.json()["id"]
    project = await create_project(client, owner["access_token"], workspace_id, "Task Proj")
    section = await create_section(client, owner["access_token"], project["id"])
    return {
        "token": owner["access_token"],
        "user": owner["user"],
        "workspace_id": workspace_id,
        "project_id": project["id"],
        "section": section,
    }


@pytest.mark.asyncio
async def test_create_task_returns_full_object(client):
    ctx = await _setup(client)
    resp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/tasks",
        json={
            "section_id": ctx["section"]["id"],
            "title": "My Task",
            "description": "Описание задачи",
            "priority": "high",
        },
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "My Task"
    assert body["description"] == "Описание задачи"
    assert body["priority"] == "high"
    assert body["is_completed"] is False
    assert body["reporter"]["username"] == "task"
    assert body["tags"] == []
    assert body["subtasks"] == []


@pytest.mark.asyncio
async def test_get_task_includes_subtasks_and_tags(client):
    ctx = await _setup(client)
    # Создаём задачу
    task = await create_task(client, ctx["token"], ctx["section"]["id"], "T",
                              project_id=ctx["project_id"])
    # Создаём тег
    tag_resp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/tags",
        json={"name": "bug", "color": "#FF0000"},
        headers=await auth_headers(ctx["token"]),
    )
    tag_id = tag_resp.json()["id"]

    # Привязываем тег к задаче
    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"tag_ids": [tag_id]},
        headers=await auth_headers(ctx["token"]),
    )

    # Создаём подзадачу
    await client.post(
        f"/api/v1/tasks/{task['id']}/subtasks",
        json={"title": "Subtask 1"},
        headers=await auth_headers(ctx["token"]),
    )

    # Получаем детали задачи
    resp = await client.get(
        f"/api/v1/tasks/{task['id']}",
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tags"]) == 1
    assert body["tags"][0]["name"] == "bug"
    assert len(body["subtasks"]) == 1
    assert body["subtasks"][0]["title"] == "Subtask 1"


@pytest.mark.asyncio
async def test_filter_tasks_by_priority(client):
    ctx = await _setup(client)
    await create_task(client, ctx["token"], ctx["section"]["id"], "Low",
                      project_id=ctx["project_id"], priority="low")
    await create_task(client, ctx["token"], ctx["section"]["id"], "High",
                      project_id=ctx["project_id"], priority="high")
    await create_task(client, ctx["token"], ctx["section"]["id"], "Urgent",
                      project_id=ctx["project_id"], priority="urgent")

    resp = await client.get(
        f"/api/v1/projects/{ctx['project_id']}/tasks?priority=high",
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["priority"] == "high"


@pytest.mark.asyncio
async def test_cursor_pagination_works(client, db_direct):
    """Курсорная пагинация: первая страница + следующая через cursor.

    ВАЖНО: SQLite CURRENT_TIMESTAMP хранит только секунды (без микросекунд).
    Поэтому в этом тесте мы вручную обновляем created_at у задач, чтобы
    гарантировать их различие. В PostgreSQL такой проблемы нет.
    """
    from sqlalchemy import text
    ctx = await _setup(client)
    # Создаём 3 задачи
    task_ids = []
    for i in range(3):
        t = await create_task(client, ctx["token"], ctx["section"]["id"], f"T{i}",
                              project_id=ctx["project_id"])
        task_ids.append(t["id"])

    # Принудительно выставляем разные created_at (SQLite-специфичный workaround)
    for idx, tid in enumerate(task_ids):
        await db_direct.execute(
            text("UPDATE tasks SET created_at = :ts WHERE id = :id"),
            {"ts": f"2026-01-01 00:00:0{idx+1}", "id": tid},
        )
    await db_direct.commit()

    # Первая страница: limit=2 — должны получить задачи T2 и T1 (created_at DESC)
    resp = await client.get(
        f"/api/v1/projects/{ctx['project_id']}/tasks?limit=2",
        headers=await auth_headers(ctx["token"]),
    )
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["meta"]["has_next"] is True
    assert body["meta"]["next_cursor"] is not None
    assert body["meta"]["has_prev"] is False  # первая страница

    # Вторая страница через cursor — должна вернуть 1 элемент (T0)
    resp2 = await client.get(
        f"/api/v1/projects/{ctx['project_id']}/tasks?limit=2&cursor={body['meta']['next_cursor']}",
        headers=await auth_headers(ctx["token"]),
    )
    body2 = resp2.json()
    assert len(body2["items"]) == 1
    assert body2["meta"]["has_next"] is False
    assert body2["meta"]["has_prev"] is True

    # Проверяем, что все 3 задачи уникальные
    all_ids = set()
    for b in [body, body2]:
        for item in b["items"]:
            all_ids.add(item["id"])
    assert len(all_ids) == 3, f"Expected 3 unique tasks, got {len(all_ids)}"


@pytest.mark.asyncio
async def test_global_search_finds_by_title(client):
    ctx = await _setup(client)
    await create_task(client, ctx["token"], ctx["section"]["id"], "Deploy production",
                      project_id=ctx["project_id"])
    await create_task(client, ctx["token"], ctx["section"]["id"], "Write docs",
                      project_id=ctx["project_id"])

    resp = await client.get(
        "/api/v1/tasks/search?q=deploy",
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert "Deploy" in items[0]["title"]


@pytest.mark.asyncio
async def test_update_task_changes_fields(client):
    ctx = await _setup(client)
    task = await create_task(client, ctx["token"], ctx["section"]["id"], "Original",
                              project_id=ctx["project_id"])
    resp = await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Updated", "priority": "urgent", "is_completed": True},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Updated"
    assert body["priority"] == "urgent"
    assert body["is_completed"] is True
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_subtask_crud(client):
    ctx = await _setup(client)
    task = await create_task(client, ctx["token"], ctx["section"]["id"], "T",
                              project_id=ctx["project_id"])

    # Создание подзадачи
    create_resp = await client.post(
        f"/api/v1/tasks/{task['id']}/subtasks",
        json={"title": "Subtask"},
        headers=await auth_headers(ctx["token"]),
    )
    assert create_resp.status_code == 201
    subtask_id = create_resp.json()["id"]

    # Обновление
    upd_resp = await client.patch(
        f"/api/v1/tasks/{task['id']}/subtasks/{subtask_id}",
        json={"is_completed": True, "title": "Done subtask"},
        headers=await auth_headers(ctx["token"]),
    )
    assert upd_resp.status_code == 200
    assert upd_resp.json()["is_completed"] is True
    assert upd_resp.json()["title"] == "Done subtask"


@pytest.mark.asyncio
async def test_timelog_parses_string_duration(client):
    ctx = await _setup(client)
    task = await create_task(client, ctx["token"], ctx["section"]["id"], "T",
                              project_id=ctx["project_id"])

    # "1h 30m" → 5400 секунд
    resp = await client.post(
        f"/api/v1/tasks/{task['id']}/timelogs",
        json={"spent_time": "1h 30m", "description": "Работа над задачей"},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["spent_seconds"] == 5400


@pytest.mark.asyncio
async def test_timelog_accepts_seconds_directly(client):
    ctx = await _setup(client)
    task = await create_task(client, ctx["token"], ctx["section"]["id"], "T",
                              project_id=ctx["project_id"])

    resp = await client.post(
        f"/api/v1/tasks/{task['id']}/timelogs",
        json={"spent_seconds": 3600},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["spent_seconds"] == 3600


@pytest.mark.asyncio
async def test_create_section_in_project(client):
    ctx = await _setup(client)
    resp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/sections",
        json={"name": "In Progress", "type": "todo"},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "In Progress"
    assert resp.json()["order"] >= 1


@pytest.mark.asyncio
async def test_create_tag_in_project(client):
    ctx = await _setup(client)
    resp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/tags",
        json={"name": "urgent", "color": "#FF0000"},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "urgent"
    assert resp.json()["color"] == "#FF0000"


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
