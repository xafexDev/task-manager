"""Структурированное JSON-логирование."""
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Форматирует логи в JSON (одна строка на событие)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Доп. поля
        for attr in ("user_id", "project_id", "task_id", "action"):
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def setup_logging(debug: bool = False) -> None:
    """Настраивает корневой логгер на JSON-формат."""
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Уровень ERROR+ для критичных операций
    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(logging.INFO)
