"""Утилита курсорной пагинации (cursor-based pagination).

В отличие от offset-пагинации, курсорная:
- Не теряет элементы при вставках/удалениях во время перебора страниц
- Имеет O(limit) сложность вместо O(offset+limit)
- Подходит для бесконечных лент и realtime-списков

Реализация: курсор = base64(JSON({"id": <last_id>, "sort": <last_sort_value>})).
Сервер возвращает next_cursor, который клиент передаёт как ?cursor=...

Для таблиц с целочисленным autoincrement-ным id (comments, activity_logs, ...)
курсор использует только id (так как id монотонно возрастает вместе с временем).

Для таблиц с UUID-ным id (tasks, projects, notifications) необходимо указать
поле сортировки (например, created_at) — курсор хранит пару (created_at, id).
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Query


def encode_cursor(payload: dict[str, Any]) -> str:
    """Кодирует словарь в base64-строку для передачи в URL."""
    raw = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Декодирует курсор из base64. Возвращает None при невалидном курсоре."""
    if not cursor:
        return None
    try:
        # Добиваем padding для корректного base64
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


@dataclass
class CursorParams:
    """Параметры курсорной пагинации.

    Если `cursor` передан — игнорируем `after_id`/`after_sort`.
    Если cursor не передан — возвращаем первую страницу (limit элементов с начала).
    """
    limit: int
    cursor: str | None
    # Направление: "next" (по умолчанию) или "prev" для обратного прохода
    direction: str = "next"

    @classmethod
    def from_query(
        cls,
        limit: int = Query(20, ge=1, le=100, description="Размер страницы (1-100)"),
        cursor: str | None = Query(None, description="Курсор следующей страницы"),
        direction: str = Query("next", pattern="^(next|prev)$", description="Направление"),
    ) -> "CursorParams":
        return cls(limit=limit, cursor=cursor, direction=direction)


@dataclass
class CursorMeta:
    """Метаданные курсорной пагинации для ответа API."""
    limit: int
    has_next: bool
    has_prev: bool
    next_cursor: str | None = None
    prev_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "has_next": self.has_next,
            "has_prev": self.has_prev,
            "next_cursor": self.next_cursor,
            "prev_cursor": self.prev_cursor,
        }


@dataclass
class CursorPage:
    """Универсальный ответ курсорной пагинации.

    items: список объектов (уже сериализованных в dict)
    meta: объект CursorMeta
    """
    items: list[dict[str, Any]]
    meta: CursorMeta

    def to_dict(self) -> dict[str, Any]:
        return {"items": self.items, "meta": self.meta.to_dict()}


def build_cursor_from_row(
    row: dict[str, Any], sort_field: str | None, id_field: str = "id"
) -> str:
    """Создаёт курсор из строки данных.

    Args:
        row: словарь с полями строки
        sort_field: имя поля сортировки (например, "created_at"). None —只用 id.
        id_field: имя поля id (по умолчанию "id")
    """
    payload: dict[str, Any] = {"id": str(row[id_field])}
    if sort_field and sort_field in row:
        val = row[sort_field]
        # datetime сериализуем в ISO
        if isinstance(val, datetime):
            payload[sort_field] = val.isoformat()
        else:
            payload[sort_field] = str(val)
    return encode_cursor(payload)


def parse_cursor_time(cursor: str | None, field: str) -> datetime | None:
    """Парсит datetime из курсора с обнулением микросекунд.

    SQLite CURRENT_TIMESTAMP хранит только секунды (без микросекунд),
    поэтому сравнение `created_at == cursor_time` всегда false,
    если в курсоре есть микросекунды. Эта функция обнуляет их.

    В PostgreSQL такой проблемы нет — тип TIMESTAMP хранит микросекунды.
    """
    decoded = decode_cursor(cursor)
    if not decoded or field not in decoded:
        return None
    try:
        dt = datetime.fromisoformat(decoded[field])
        return dt.replace(microsecond=0)
    except (ValueError, TypeError):
        return None


def parse_cursor_time_str(cursor: str | None, field: str) -> str | None:
    """Парсит datetime из курсора и возвращает как строку 'YYYY-MM-DD HH:MM:SS'.

    Это необходимо для корректного сравнения в SQLite, который хранит
    DATETIME как TEXT. Если передать datetime-объект, SQLAlchemy добавит
    микросекунды ('.000000'), и сравнение `created_at == cursor_time`
    будет всегда false (строгое текстовое сравнение).

    Возвращаем строку в формате 'YYYY-MM-DD HH:MM:SS' (без микросекунд),
    чтобы она точно совпадала с тем, как CURRENT_TIMESTAMP хранит значения.
    """
    dt = parse_cursor_time(cursor, field)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_cursor_id(cursor: str | None) -> str | None:
    """Парсит id из курсора как строку.

    ВАЖНО: всегда возвращаем строку, т.к. в SQLite UUID хранится как VARCHAR(36),
    и сравнение UUID-объекта со строкой может работать некорректно.
    """
    decoded = decode_cursor(cursor)
    if not decoded or "id" not in decoded:
        return None
    return str(decoded["id"])
