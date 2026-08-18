"""Сервис загрузки файлов: валидация, сохранение на локальный диск."""
import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.core.exceptions import ValidationError


def _ensure_upload_dir() -> Path:
    """Создаёт директорию для загрузок, если её нет."""
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload(file: UploadFile) -> tuple[str, str, int, str]:
    """Сохраняет файл на локальный диск.

    Returns:
        Кортеж (file_url, filename, file_size, mime_type)
    """
    if not file.filename or not file.filename.strip():
        raise ValidationError("Имя файла обязательно")

    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    # Проверка MIME-типа
    allowed = set(settings.allowed_mime_types_list)
    if file.content_type and allowed and file.content_type not in allowed:
        raise ValidationError(
            f"Недопустимый тип файла: {file.content_type}. "
            f"Разрешены: {', '.join(sorted(allowed))}"
        )

    # Читаем содержимое с проверкой размера
    upload_dir = _ensure_upload_dir()
    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = upload_dir / stored_name

    size = 0
    with open(stored_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                f.close()
                os.remove(stored_path)
                raise ValidationError(
                    f"Размер файла превышает лимит {settings.max_upload_size_mb} МБ"
                )
            f.write(chunk)

    # URL для доступа (через статический эндпоинт /uploads/{filename})
    file_url = f"/uploads/{stored_name}"
    return file_url, file.filename, size, file.content_type or "application/octet-stream"
