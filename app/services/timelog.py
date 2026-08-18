"""Сервис логирования времени с парсингом строк вида '1h 30m', '45m', '2h'."""
import re
from dataclasses import dataclass

# Паттерны: "1h 30m", "2h", "45m", "1h30m", "90s"
_HM_PATTERN = re.compile(
    r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?",
    re.IGNORECASE,
)


@dataclass
class ParsedDuration:
    seconds: int
    raw: str


def parse_duration(text: str) -> int:
    """Парсит строку длительности в секунды.

    Поддерживаемые форматы:
        "1h 30m"   -> 5400
        "2h"       -> 7200
        "45m"      -> 2700
        "1h30m"    -> 5400
        "90s"      -> 90
        "5400"     -> 5400 (только число — секунды)
    """
    text = text.strip().lower()
    if not text:
        raise ValueError("Пустая строка длительности")

    # Если это просто число — интерпретируем как секунды
    if text.isdigit():
        return int(text)

    match = _HM_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(f"Не удалось разобрать длительность: {text!r}")

    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    if total == 0:
        raise ValueError(f"Длительность равна 0: {text!r}")
    return total


def resolve_spent_seconds(spent_seconds: int | None, spent_time: str | None) -> int:
    """Разрешает входные данные TimeLog в секунды (целое)."""
    if spent_seconds is not None and spent_seconds > 0:
        return spent_seconds
    if spent_time is not None:
        return parse_duration(spent_time)
    raise ValueError("Необходимо указать spent_seconds или spent_time")
