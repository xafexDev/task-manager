"""Rate Limiting middleware (опционально, через Redis).

Если Redis недоступен — middleware отключается и логирует предупреждение.
Лимит: N запросов в минуту на пользователя (по user_id из JWT).
"""
import time
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.core.security import decode_access_token

_redis = None
_redis_checked = False


async def _get_redis():
    """Ленивая инициализация Redis с проверкой доступности."""
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    if not settings.rate_limit_enabled:
        return None
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await _redis.ping()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.warning(f"Redis недоступен, rate limiting отключён: {exc}")
        _redis = None
    return _redis


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Ограничивает количество запросов от пользователя в минуту."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Пропускаем если rate limit выключен
        if not settings.rate_limit_enabled:
            return await call_next(request)

        redis = await _get_redis()
        if redis is None:
            return await call_next(request)

        # Извлекаем пользователя из токена (если есть)
        auth = request.headers.get("Authorization", "")
        identifier = "anonymous"
        if auth.startswith("Bearer "):
            try:
                payload = decode_access_token(auth[7:])
                identifier = f"user:{payload['sub']}"
            except Exception:  # noqa: BLE001
                identifier = f"ip:{request.client.host if request.client else 'unknown'}"
        else:
            identifier = f"ip:{request.client.host if request.client else 'unknown'}"

        # Скользящее окно через Redis sorted set
        now = time.time()
        window = 60.0
        key = f"rate_limit:{identifier}"

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, int(window) + 1)
        _, _, count, _ = await pipe.execute()

        if count > settings.rate_limit_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "Превышен лимит запросов. Попробуйте позже."},
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, settings.rate_limit_per_minute - count)
        )
        return response
