"""Тесты комментариев, упоминаний и уведомлений."""
import pytest

from tests.conftest import (
    auth_headers, create_project, create_section, create_task, register_user,
)


async def _setup(client, with_member: bool = True):
    owner = await register_user(client, email="noto@example.com", username="noto")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Notif WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    workspace_id = ws_resp.json()["id"]
    project = await create_project(client, owner["access_token"], workspace_id, "Notif Proj")
    section = await create_section(client, owner["access_token"], project["id"])
    task = await create_task(
        client, owner["access_token"], section["id"], "Notif task",
        project_id=project["id"],
    )

    ctx = {
        "token": owner["access_token"],
        "user": owner["user"],
        "workspace_id": workspace_id,
        "project_id": project["id"],
        "section": section,
        "task": task,
    }

    if with_member:
        member = await register_user(
            client, email="noto2@example.com", username="noto2",
            workspace_name="Notif2Private",
        )
        # Приглашаем в workspace
        await client.post(
            f"/api/v1/workspaces/{workspace_id}/invite",
            json={"email": member["user"]["email"], "role": "member"},
            headers=await auth_headers(owner["access_token"]),
        )
        # Добавляем в проект как editor
        await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": member["user"]["id"], "role": "editor"},
            headers=await auth_headers(owner["access_token"]),
        )
        ctx["member_token"] = member["access_token"]
        ctx["member_user"] = member["user"]

    return ctx


@pytest.mark.asyncio
async def test_comment_creates_mention_notification(client):
    """Упоминание @username в комментарии создаёт уведомление."""
    ctx = await _setup(client)

    # Member пишет комментарий с упоминанием owner (noto)
    resp = await client.post(
        f"/api/v1/tasks/{ctx['task']['id']}/comments",
        json={"text": "Привет @noto, посмотри задачу"},
        headers=await auth_headers(ctx["member_token"]),
    )
    assert resp.status_code == 201, resp.text

    # У owner должно появиться непрочитанное уведомление
    notif_resp = await client.get(
        "/api/v1/notifications?unread_only=true",
        headers=await auth_headers(ctx["token"]),
    )
    assert notif_resp.status_code == 200
    notifs = notif_resp.json()["items"]
    assert len(notifs) >= 1
    assert notifs[0]["type"] == "mention"
    assert "noto2" in notifs[0]["title"]


@pytest.mark.asyncio
async def test_assignment_creates_notification(client):
    """Назначение на задачу создаёт уведомление."""
    ctx = await _setup(client)

    # Owner назначает member на задачу
    resp = await client.put(
        f"/api/v1/tasks/{ctx['task']['id']}",
        json={"assignee_id": ctx["member_user"]["id"]},
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200, resp.text

    # У member должно появиться уведомление о назначении
    notif_resp = await client.get(
        "/api/v1/notifications?unread_only=true",
        headers=await auth_headers(ctx["member_token"]),
    )
    assert notif_resp.status_code == 200
    notifs = notif_resp.json()["items"]
    assert any(n["type"] == "assignment" for n in notifs)


@pytest.mark.asyncio
async def test_mark_notification_as_read(client):
    """POST /notifications/{id}/read отмечает как прочитанное."""
    ctx = await _setup(client)
    # Создаём упоминание
    await client.post(
        f"/api/v1/tasks/{ctx['task']['id']}/comments",
        json={"text": "@noto прочитай",
        },
        headers=await auth_headers(ctx["member_token"]),
    )
    notif_resp = await client.get(
        "/api/v1/notifications?unread_only=true",
        headers=await auth_headers(ctx["token"]),
    )
    notif_id = notif_resp.json()["items"][0]["id"]

    mark_resp = await client.post(
        f"/api/v1/notifications/{notif_id}/read",
        headers=await auth_headers(ctx["token"]),
    )
    assert mark_resp.status_code == 200
    assert mark_resp.json()["is_read"] is True


@pytest.mark.asyncio
async def test_mark_all_notifications_as_read(client):
    """POST /notifications/read-all отмечает все как прочитанные."""
    ctx = await _setup(client)
    # Несколько упоминаний
    for i in range(3):
        await client.post(
            f"/api/v1/tasks/{ctx['task']['id']}/comments",
            json={"text": f"@noto сообщение {i}"},
            headers=await auth_headers(ctx["member_token"]),
        )

    resp = await client.post(
        "/api/v1/notifications/read-all",
        headers=await auth_headers(ctx["token"]),
    )
    assert resp.status_code == 200

    # Проверяем, что непрочитанных нет
    notif_resp = await client.get(
        "/api/v1/notifications?unread_only=true",
        headers=await auth_headers(ctx["token"]),
    )
    assert len(notif_resp.json()["items"]) == 0


@pytest.mark.asyncio
async def test_self_mention_does_not_notify(client):
    """Упоминание самого себя не создаёт уведомление."""
    ctx = await _setup(client, with_member=False)

    # Owner упоминает сам себя
    await client.post(
        f"/api/v1/tasks/{ctx['task']['id']}/comments",
        json={"text": "Заметка для @noto"},
        headers=await auth_headers(ctx["token"]),
    )

    notif_resp = await client.get(
        "/api/v1/notifications?unread_only=true",
        headers=await auth_headers(ctx["token"]),
    )
    assert len(notif_resp.json()["items"]) == 0
