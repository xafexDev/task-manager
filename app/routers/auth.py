"""Роутер аутентификации: регистрация, вход, refresh, forgot-password, /me."""
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.dependencies import CurrentUser
from app.models import User, Workspace, WorkspaceMember
from app.schemas.auth import (
    ForgotPasswordRequest,
    PasswordResetConfirm,
    RefreshRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
)
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["Auth"])


def _create_tokens(user_id: UUID) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового пользователя",
    description=(
        "Создаёт пользователя. Если указан `workspace_name` — создаёт новый "
        "workspace с пользователем как owner. Если указан "
        "`workspace_invite_code` — добавляет пользователя в существующий "
        "workspace с ролью member."
    ),
)
async def register(
    payload: UserRegister,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    # Проверка уникальности email и username
    exists = await db.execute(
        select(User).where((User.email == payload.email) | (User.username == payload.username))
    )
    if exists.scalar_one_or_none():
        raise ConflictError("Пользователь с таким email или username уже существует")

    # Создание пользователя
    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        status="active",
    )
    db.add(user)
    await db.flush()

    # Workspace: либо новый, либо через код приглашения
    if payload.workspace_invite_code:
        # В MVP код приглашения = ID workspace (упрощение)
        # В реальном проекте — отдельная таблица Invitation с кодами
        try:
            ws_id = UUID(payload.workspace_invite_code)
        except ValueError:
            raise NotFoundError("Невалидный код приглашения")
        ws = await db.get(Workspace, ws_id)
        if ws is None:
            raise NotFoundError("Workspace по коду приглашения не найден")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="member"))
    else:
        # Создаём новый workspace
        ws_name = payload.workspace_name or f"Workspace {payload.username}"
        ws = Workspace(name=ws_name, owner_id=user.id)
        db.add(ws)
        await db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))

    await db.commit()
    await db.refresh(user)
    return _create_tokens(user.id)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход в систему",
    description="Возвращает access и refresh JWT-токены.",
)
async def login(
    payload: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("Неверный email или пароль")
    if user.status != "active":
        raise UnauthorizedError("Пользователь деактивирован")
    return _create_tokens(user.id)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление access-токена",
)
async def refresh(payload: RefreshRequest) -> TokenResponse:
    try:
        decoded = decode_refresh_token(payload.refresh_token)
        user_id = UUID(decoded["sub"])
    except (JWTError, ValueError) as exc:
        raise UnauthorizedError(f"Невалидный refresh-токен: {exc}")
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запрос на сброс пароля",
    description=(
        "Принимает email. Если пользователь существует — генерирует токен сброса "
        "(в MVP просто логируется, в продакшене отправляется по email через "
        "фоновую задачу)."
    ),
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Чтобы не утечь существование email — всегда возвращаем 202
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user:
        # В MVP: токен = подписанный JWT с коротким сроком жизни
        # В реальном проекте — отдельная таблица PasswordResetToken
        from app.core.security import _create_token
        reset_token = _create_token(
            subject=str(user.id),
            token_type="password_reset",
            expires_delta=timedelta(hours=1),
        )
        # Имитация отправки письма в фоновой задаче
        background_tasks.add_task(
            _send_reset_email_stub, user.email, reset_token
        )
    return {"message": "Если email существует, инструкция отправлена"}


def _send_reset_email_stub(email: str, token: str) -> None:
    """Заглушка отправки письма сброса пароля."""
    print(f"[EMAIL STUB] To: {email}, Reset token: {token}")


@router.get(
    "/me",
    response_model=UserRead,
    summary="Данные текущего пользователя",
)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
