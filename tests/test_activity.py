"""Тесты истории изменений задачи (Activity Log / audit log).

Проверяем:
- Создание задачи → запись "task.created"
- Обновление полей → записи "task.updated" с old/new
- Смена исполнителя → "task.assigned" / "task.unassigned"
- Перемещение → "task.moved"
- Завершение задачи → "task.completed"
- Комментарии, вложения, логи времени, подзадачи, зависимости
- Эндпоинт GET /tasks/{id}/activities с курсорной пагинацией
"""
import pytest

from tests.conftest import (
    auth_headers, create_project, create_section, create_task, register_user,
)


async def _setup(client):
    owner = await register_user(client, email="act@example.com", username="act")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Act WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    workspace_id = ws_resp.json()["id"]
    project = await create_project(client, owner["access_token"], workspace_id, "Act Proj")
    section = await create_section(client, owner["access_token"], project["id"])
    return {
        "token": owner["access_token"],
        "user": owner["user"],
        "workspace_id": workspace_id,
        "project_id": project["id"],
        "section": section,
    }


@pytest.mark.asyncio
async def test_task_creation_logs_activity(client):
    """Создание задачи создаёт запись task.created в истории."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "My Task",
        project_id=ctx["project_id"],
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    assert activities.status_code == 200
    items = activities.json()["items"]
    assert len(items) == 1
    assert items[0]["action"] == "task.created"
    assert "My Task" in items[0]["description"]


@pytest.mark.asyncio
async def test_task_update_logs_field_changes(client):
    """Обновление полей задачи создаёт отдельные записи для каждого изменённого поля."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "Original",
        project_id=ctx["project_id"], priority="low",
    )

    # Обновляем title и priority
    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Updated", "priority": "high"},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    items = activities.json()["items"]
    actions = [item["action"] for item in items]

    # Должны быть: task.created, task.updated (title), task.updated (priority)
    assert "task.created" in actions
    assert actions.count("task.updated") >= 2  # минимум 2 обновления

    # Проверяем, что в payload есть old/new
    updated_items = [item for item in items if item["action"] == "task.updated"]
    for item in updated_items:
        import json
        payload = json.loads(item["payload"])
        assert "field" in payload
        assert "old" in payload
        assert "new" in payload


@pytest.mark.asyncio
async def test_task_completion_logs_activity(client):
    """Завершение задачи создаёт запись task.completed."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "To complete",
        project_id=ctx["project_id"],
    )

    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"is_completed": True},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    items = activities.json()["items"]
    actions = [item["action"] for item in items]
    assert "task.completed" in actions


@pytest.mark.asyncio
async def test_task_reopen_logs_activity(client):
    """Переоткрытие задачи создаёт запись task.reopened."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "To reopen",
        project_id=ctx["project_id"],
    )
    # Сначала завершаем
    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"is_completed": True},
        headers=await auth_headers(ctx["token"]),
    )
    # Затем переоткрываем
    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"is_completed": False},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    actions = [item["action"] for item in activities.json()["items"]]
    assert "task.completed" in actions
    assert "task.reopened" in actions


@pytest.mark.asyncio
async def test_task_move_logs_activity(client):
    """Перемещение задачи создаёт запись task.moved."""
    ctx = await _setup(client)
    section_a = ctx["section"]
    section_b = await create_section(client, ctx["token"], ctx["project_id"], "Done", "done")
    task = await create_task(
        client, ctx["token"], section_a["id"], "Move me",
        project_id=ctx["project_id"],
    )

    await client.patch(
        f"/api/v1/tasks/{task['id']}/move",
        json={"section_id": section_b["id"], "order": 0},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    actions = [item["action"] for item in activities.json()["items"]]
    assert "task.moved" in actions


@pytest.mark.asyncio
async def test_task_assignment_logs_activity(client):
    """Назначение исполнителя создаёт запись task.assigned."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "Assign me",
        project_id=ctx["project_id"],
    )

    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"assignee_id": ctx["user"]["id"]},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    actions = [item["action"] for item in activities.json()["items"]]
    assert "task.assigned" in actions


@pytest.mark.asyncio
async def test_comment_creation_logs_activity(client):
    """Добавление комментария создаёт запись comment.created."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "With comment",
        project_id=ctx["project_id"],
    )

    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"text": "Hello world"},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    actions = [item["action"] for item in activities.json()["items"]]
    assert "comment.created" in actions


@pytest.mark.asyncio
async def test_subtask_creation_logs_activity(client):
    """Добавление подзадачи создаёт запись subtask.created."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "With subtask",
        project_id=ctx["project_id"],
    )

    await client.post(
        f"/api/v1/tasks/{task['id']}/subtasks",
        json={"title": "Subtask 1"},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    actions = [item["action"] for item in activities.json()["items"]]
    assert "subtask.created" in actions


@pytest.mark.asyncio
async def test_timelog_creation_logs_activity(client):
    """Логирование времени создаёт запись timelog.created."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "With timelog",
        project_id=ctx["project_id"],
    )

    await client.post(
        f"/api/v1/tasks/{task['id']}/timelogs",
        json={"spent_time": "1h 30m"},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    actions = [item["action"] for item in activities.json()["items"]]
    assert "timelog.created" in actions


@pytest.mark.asyncio
async def test_dependency_creation_logs_activity(client):
    """Создание зависимости создаёт запись dependency.created."""
    ctx = await _setup(client)
    task_a = await create_task(
        client, ctx["token"], ctx["section"]["id"], "A",
        project_id=ctx["project_id"],
    )
    task_b = await create_task(
        client, ctx["token"], ctx["section"]["id"], "B",
        project_id=ctx["project_id"],
    )

    await client.post(
        f"/api/v1/tasks/{task_b['id']}/dependencies",
        json={"predecessor_task_id": task_a["id"]},
        headers=await auth_headers(ctx["token"]),
    )

    # Запись должна быть на обеих задачах
    for tid in [task_a["id"], task_b["id"]]:
        activities = await client.get(
            f"/api/v1/tasks/{tid}/activities",
            headers=await auth_headers(ctx["token"]),
        )
        actions = [item["action"] for item in activities.json()["items"]]
        assert "dependency.created" in actions, f"task {tid} should have dependency.created"


@pytest.mark.asyncio
async def test_activities_cursor_pagination(client, db_direct):
    """История изменений с курсорной пагинацией."""
    from sqlalchemy import text
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "Many events",
        project_id=ctx["project_id"],
    )

    # Создаём несколько комментариев → несколько activity_logs
    for i in range(5):
        await client.post(
            f"/api/v1/tasks/{task['id']}/comments",
            json={"text": f"Comment {i}"},
            headers=await auth_headers(ctx["token"]),
        )

    # Принудительно выставляем разные created_at для activity_logs
    # (SQLite workaround: CURRENT_TIMESTAMP хранит только секунды)
    activity_ids = (
        await db_direct.execute(
            text("SELECT id FROM activity_logs WHERE task_id = :tid ORDER BY id"),
            {"tid": task["id"]},
        )
    ).all()
    for idx, (aid,) in enumerate(activity_ids):
        await db_direct.execute(
            text("UPDATE activity_logs SET created_at = :ts WHERE id = :id"),
            {"ts": f"2026-01-01 00:00:0{idx+1}", "id": aid},
        )
    await db_direct.commit()

    # Первая страница: limit=3
    resp = await client.get(
        f"/api/v1/tasks/{task['id']}/activities?limit=3",
        headers=await auth_headers(ctx["token"]),
    )
    body = resp.json()
    assert len(body["items"]) == 3
    assert body["meta"]["has_next"] is True
    assert body["meta"]["next_cursor"] is not None
    assert body["meta"]["has_prev"] is False

    # Вторая страница
    resp2 = await client.get(
        f"/api/v1/tasks/{task['id']}/activities?limit=3&cursor={body['meta']['next_cursor']}",
        headers=await auth_headers(ctx["token"]),
    )
    body2 = resp2.json()
    # task.created + 5 comments = 6 записей. На первой странице 3, на второй должно быть 3.
    assert len(body2["items"]) == 3
    assert body2["meta"]["has_prev"] is True

    # Проверяем, что все записи уникальны
    all_ids = set()
    for b in [body, body2]:
        for item in b["items"]:
            all_ids.add(item["id"])
    assert len(all_ids) == 6


@pytest.mark.asyncio
async def test_activities_ordered_newest_first(client):
    """История изменений возвращается в обратном хронологическом порядке (сначала новые)."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "Order test",
        project_id=ctx["project_id"],
    )

    # Создаём 2 комментария — они добавят 2 записи в activity_logs
    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"text": "First comment"},
        headers=await auth_headers(ctx["token"]),
    )
    await client.post(
        f"/api/v1/tasks/{task['id']}/comments",
        json={"text": "Second comment"},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    items = activities.json()["items"]
    # Порядок: comment.created (2nd), comment.created (1st), task.created
    assert items[0]["action"] == "comment.created"
    assert "Second comment" in items[0]["description"]
    assert items[-1]["action"] == "task.created"


@pytest.mark.asyncio
async def test_non_member_cannot_view_activities(client):
    """Пользователь без доступа к задаче не может видеть её историю."""
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "Private",
        project_id=ctx["project_id"],
    )

    # Создаём другого пользователя (без доступа к проекту)
    other = await register_user(
        client, email="other@example.com", username="other",
        workspace_name="OtherPrivateWS",
    )

    resp = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(other["access_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_activity_payload_contains_old_and_new_values(client):
    """Payload записи task.updated содержит old_value и new_value."""
    import json
    ctx = await _setup(client)
    task = await create_task(
        client, ctx["token"], ctx["section"]["id"], "Original title",
        project_id=ctx["project_id"], priority="low",
    )

    await client.put(
        f"/api/v1/tasks/{task['id']}",
        json={"priority": "urgent"},
        headers=await auth_headers(ctx["token"]),
    )

    activities = await client.get(
        f"/api/v1/tasks/{task['id']}/activities",
        headers=await auth_headers(ctx["token"]),
    )
    items = activities.json()["items"]
    # Находим запись с field=priority
    priority_updates = [
        item for item in items
        if item["action"] == "task.updated" and json.loads(item["payload"]).get("field") == "priority"
    ]
    assert len(priority_updates) == 1
    payload = json.loads(priority_updates[0]["payload"])
    assert payload["old"] == "low"
    assert payload["new"] == "urgent"
