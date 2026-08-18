"""Схемы аутентификации."""
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    """Регистрация нового пользователя.

    `workspace_invite_code` — опциональный код приглашения в существующий workspace.
    Если не указан — будет создан новый workspace с пользователем как owner.
    """
    email: EmailStr = Field(..., description="Email пользователя (уникальный)")
    username: str = Field(..., min_length=3, max_length=64, description="Никнейм (уникальный)")
    password: str = Field(..., min_length=8, max_length=128, description="Пароль (мин. 8 символов)")
    workspace_name: str | None = Field(None, description="Имя нового workspace (если создаётся)")
    workspace_invite_code: str | None = Field(None, description="Код приглашения в существующий workspace")


class UserLogin(BaseModel):
    """Вход в систему."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Ответ с access и refresh токенами."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Запрос на обновление access-токена."""
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    """Запрос на сброс пароля."""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Подтверждение сброса пароля."""
    token: str
    new_password: str = Field(..., min_length=8)
