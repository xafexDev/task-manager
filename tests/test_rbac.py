"""Тесты RBAC: проверка прав доступа согласно ролевой модели.

Ключевые сценарии из ТЗ:
- Пользователь Guest не может создать проект
- Пользователь Viewer не может удалить задачу
- Только Manager может управлять участниками проекта
- Только Editor+ может создавать задачи
"""
import pytest
from uuid import uuid4

from tests.conftest import (
    auth_headers, create_project, create_section, create_task, register_user,
)


async def _setup_workspace_with_members(client):
    """Создаёт workspace с owner и несколькими участниками разных глобальных ролей.

    Returns:
        dict с owner_token, member_token, guest_token, workspace_id
    """
    # Owner создаёт workspace
    owner = await register_user(client, email="owner@example.com", username="owner")
    workspace_id = owner["user"]["id"]  # упрощение: workspace_id = user_id (только для теста)

    # Реально workspace_id нужно получить из API. Создадим новый workspace.
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Test WS"},
        headers=await auth_headers(owner["access_token"]),
    )
    assert ws_resp.status_code == 201
    workspace_id = ws_resp.json()["id"]

    # Member, Guest, Admin — регистрируются без workspace, потом приглашаются
    member = await register_user(
        client, email="member@example.com", username="member",
        workspace_name="MemberPrivateWS",
    )
    guest = await register_user(
        client, email="guest@example.com", username="guest",
        workspace_name="GuestPrivateWS",
    )
    admin = await register_user(
        client, email="admin@example.com", username="admin",
        workspace_name="AdminPrivateWS",
    )

    # Приглашаем в workspace owner'а
    for user_data, role in [(member, "member"), (guest, "guest"), (admin, "admin")]:
        resp = await client.post(
            f"/api/v1/workspaces/{workspace_id}/invite",
            json={"email": user_data["user"]["email"], "role": role},
            headers=await auth_headers(owner["access_token"]),
        )
        assert resp.status_code == 201, f"Invite {role} failed: {resp.text}"

    return {
        "owner_token": owner["access_token"],
        "owner_user": owner["user"],
        "member_token": member["access_token"],
        "member_user": member["user"],
        "guest_token": guest["access_token"],
        "guest_user": guest["user"],
        "admin_token": admin["access_token"],
        "admin_user": admin["user"],
        "workspace_id": workspace_id,
    }


@pytest.mark.asyncio
async def test_guest_cannot_create_project(client):
    """ТЗ: Пользователь Guest не может создать проект."""
    ctx = await _setup_workspace_with_members(client)
    resp = await client.post(
        "/api/v1/projects",
        json={"workspace_id": ctx["workspace_id"], "name": "Guest Project"},
        headers=await auth_headers(ctx["guest_token"]),
    )
    assert resp.status_code == 403, f"Guest should not create project: {resp.text}"


@pytest.mark.asyncio
async def test_member_cannot_create_project(client):
    """Member также не может создавать проекты (только admin/owner)."""
    ctx = await _setup_workspace_with_members(client)
    resp = await client.post(
        "/api/v1/projects",
        json={"workspace_id": ctx["workspace_id"], "name": "Member Project"},
        headers=await auth_headers(ctx["member_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_project(client):
    """Admin может создавать проекты."""
    ctx = await _setup_workspace_with_members(client)
    resp = await client.post(
        "/api/v1/projects",
        json={"workspace_id": ctx["workspace_id"], "name": "Admin Project"},
        headers=await auth_headers(ctx["admin_token"]),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_owner_can_create_project(client):
    """Owner может создавать проекты."""
    ctx = await _setup_workspace_with_members(client)
    resp = await client.post(
        "/api/v1/projects",
        json={"workspace_id": ctx["workspace_id"], "name": "Owner Project"},
        headers=await auth_headers(ctx["owner_token"]),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_viewer_cannot_delete_task(client):
    """ТЗ: Пользователь Viewer не может удалить задачу."""
    ctx = await _setup_workspace_with_members(client)

    # Owner создаёт проект и добавляет guest как viewer
    project = await create_project(
        client, ctx["owner_token"], ctx["workspace_id"], "Project with viewer"
    )
    project_id = project["id"]

    # Добавляем guest как viewer в проект
    add_resp = await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": ctx["guest_user"]["id"], "role": "viewer"},
        headers=await auth_headers(ctx["owner_token"]),
    )
    assert add_resp.status_code == 201

    # Owner создаёт колонку и задачу
    section = await create_section(client, ctx["owner_token"], project_id, "To Do")
    task = await create_task(
        client, ctx["owner_token"], section["id"], "Task to delete",
        project_id=project_id,
    )

    # Guest (viewer) пытается удалить задачу → 403
    del_resp = await client.delete(
        f"/api/v1/tasks/{task['id']}",
        headers=await auth_headers(ctx["guest_token"]),
    )
    assert del_resp.status_code == 403, f"Viewer should not delete task: {del_resp.text}"


@pytest.mark.asyncio
async def test_manager_can_delete_task(client):
    """Manager может удалять задачи."""
    ctx = await _setup_workspace_with_members(client)
    project = await create_project(
        client, ctx["owner_token"], ctx["workspace_id"], "Project for delete"
    )
    project_id = project["id"]
    section = await create_section(client, ctx["owner_token"], project_id)
    task = await create_task(
        client, ctx["owner_token"], section["id"], "Task to delete",
        project_id=project_id,
    )
    # Owner — это manager проекта (по умолчанию при создании)
    del_resp = await client.delete(
        f"/api/v1/tasks/{task['id']}",
        headers=await auth_headers(ctx["owner_token"]),
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_viewer_cannot_create_task(client):
    """Viewer не может создавать задачи (только editor+)."""
    ctx = await _setup_workspace_with_members(client)
    project = await create_project(
        client, ctx["owner_token"], ctx["workspace_id"], "Viewer test"
    )
    project_id = project["id"]
    # Добавляем guest как viewer
    await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": ctx["guest_user"]["id"], "role": "viewer"},
        headers=await auth_headers(ctx["owner_token"]),
    )
    section = await create_section(client, ctx["owner_token"], project_id)

    # Viewer пытается создать задачу
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"section_id": section["id"], "title": "Viewer task"},
        headers=await auth_headers(ctx["guest_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_create_task(client):
    """Editor может создавать задачи."""
    ctx = await _setup_workspace_with_members(client)
    project = await create_project(
        client, ctx["owner_token"], ctx["workspace_id"], "Editor test"
    )
    project_id = project["id"]
    # Member = editor проекта
    await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": ctx["member_user"]["id"], "role": "editor"},
        headers=await auth_headers(ctx["owner_token"]),
    )
    section = await create_section(client, ctx["owner_token"], project_id)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"section_id": section["id"], "title": "Editor task"},
        headers=await auth_headers(ctx["member_token"]),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_non_member_cannot_access_project(client):
    """Пользователь без доступа к проекту получает 403."""
    ctx = await _setup_workspace_with_members(client)
    project = await create_project(
        client, ctx["owner_token"], ctx["workspace_id"], "Private project"
    )

    # Guest (не добавлен в проект) пытается получить детали
    resp = await client.get(
        f"/api/v1/projects/{project['id']}",
        headers=await auth_headers(ctx["guest_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_only_manager_can_add_project_members(client):
    """Только manager может добавлять участников в проект."""
    ctx = await _setup_workspace_with_members(client)
    project = await create_project(
        client, ctx["owner_token"], ctx["workspace_id"], "Members test"
    )
    project_id = project["id"]
    # Добавляем member как editor
    await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": ctx["member_user"]["id"], "role": "editor"},
        headers=await auth_headers(ctx["owner_token"]),
    )

    # Editor пытается добавить участника → 403
    resp = await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": ctx["admin_user"]["id"], "role": "viewer"},
        headers=await auth_headers(ctx["member_token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client):
    """Запрос без токена отклоняется."""
    resp = await client.post(
        "/api/v1/projects",
        json={"workspace_id": str(uuid4()), "name": "Anon project"},
    )
    assert resp.status_code == 401
