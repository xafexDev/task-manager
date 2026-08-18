"""Тесты аутентификации: регистрация, вход, refresh, /me."""
import pytest

from tests.conftest import auth_headers, register_user


@pytest.mark.asyncio
async def test_register_creates_workspace_and_returns_tokens(client):
    data = await register_user(
        client, email="alice@example.com", username="alice", workspace_name="Alice WS"
    )
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["username"] == "alice"


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client):
    await register_user(client, email="bob@example.com", username="bob")
    response = await client.post("/api/v1/auth/register", json={
        "email": "bob@example.com",
        "username": "bob2",
        "password": "Password123!",
        "workspace_name": "WS2",
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client):
    await register_user(client, email="carol@example.com", username="carol")
    response = await client.post("/api/v1/auth/login", json={
        "email": "carol@example.com",
        "password": "Password123!",
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await register_user(client, email="dave@example.com", username="dave")
    response = await client.post("/api/v1/auth/login", json={
        "email": "dave@example.com",
        "password": "WrongPassword!",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_works(client):
    data = await register_user(client, email="eve@example.com", username="eve")
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": data["refresh_token"],
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user(client):
    data = await register_user(client, email="frank@example.com", username="frank")
    response = await client.get(
        "/api/v1/auth/me",
        headers=await auth_headers(data["access_token"]),
    )
    assert response.status_code == 200
    assert response.json()["email"] == "frank@example.com"


@pytest.mark.asyncio
async def test_password_too_short_rejected(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "short@example.com",
        "username": "short",
        "password": "123",
        "workspace_name": "WS",
    })
    # Pydantic валидация → 422
    assert response.status_code == 422
