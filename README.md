# Task Manager API

RESTful API системы управления проектами и задачами (Канбан-доска).

**Стек:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL / SQLite, Redis (опц.), WebSockets, Pydantic v2, Alembic, PyTest.

## Возможности

- **Аутентификация:** регистрация, вход, refresh JWT, forgot-password, /me
- **Ролевая модель (RBAC):** глобальные роли (owner/admin/member/guest) + проектные (manager/editor/viewer)
- **Workspace + Projects:** создание, приглашение участников, смена ролей
- **Канбан-доска:** секции (колонки), drag-and-drop с автоматическим пересчётом `order`
- **Задачи:** создание, обновление, перемещение, удаление, подзадачи, теги
- **Зависимости:** блокировка задач друг другом + защита от циклических зависимостей
- **Комментарии:** с поддержкой Markdown и упоминаниями `@username`
- **Вложения:** загрузка файлов (локальное хранилище, лимит 10 МБ, проверка MIME)
- **Учёт времени:** логирование с парсингом строк вида `"1h 30m"`, `"45m"`, `"2h"`
- **Уведомления:** mention, assignment, отметка прочитанным
- **Реал-тайм:** WebSocket `/api/v1/projects/{project_id}/ws` для обновления доски
- **История изменений (Activity Log / audit log):** каждая значимая операция с задачей
  (создание, обновление полей, перемещение, назначение, комментарии, вложения, логи времени,
  подзадачи, зависимости) автоматически записывается. Эндпоинт `GET /tasks/{id}/activities`
  возвращает timeline с курсорной пагинацией. В payload каждой записи хранятся old_value и
  new_value для аудита.
- **Поиск и фильтрация:** глобальный поиск + фильтры по priority/assignee/tag/due_date
- **Курсорная пагинация:** все списочные эндпоинты (задачи, проекты, комментарии,
  уведомления, логи времени, история) используют cursor-based pagination вместо offset.
  Курсор — base64(JSON({"created_at": ISO, "id": UUID})). В ответе `meta.next_cursor`
  для запроса следующей страницы. Преимущества: O(limit) сложность, не теряет элементы
  при вставках/удалениях во время перебора.
- **Rate limiting:** опционально через Redis (100 запросов/мин на пользователя)
- **Документация:** автоматическая OpenAPI на `/docs` и `/redoc`
- **Структурированные логи:** JSON-формат

## Быстрый старт (локально, SQLite)

```bash
cd task_manager
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# По умолчанию используется SQLite — никаких внешних сервисов не требуется

# Применяем миграции (или используем auto-create при первом запуске)
alembic upgrade head

# Запускаем
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: http://localhost:8000/docs
ReDoc: http://localhost:8000/redoc

## Запуск через Docker (PostgreSQL + Redis)

```bash
docker-compose up --build
```

API будет доступно на http://localhost:8000, Postgres на :5432, Redis на :6379.

## Запуск тестов

```bash
pytest -v
```

Тесты используют in-memory SQLite — внешних зависимостей не требуется.

## Структура проекта

```
task_manager/
├── app/
│   ├── main.py                  # FastAPI app, middleware, роутеры
│   ├── config.py                # Pydantic Settings (.env)
│   ├── database.py              # SQLAlchemy 2.0 async engine + Base
│   ├── dependencies.py          # auth, RBAC, пагинация
│   ├── core/
│   │   ├── security.py          # JWT (access/refresh), bcrypt
│   │   ├── rbac.py              # роли и проверки прав
│   │   ├── ws_manager.py        # WebSocket connection manager
│   │   ├── rate_limit.py        # Redis sliding-window rate limiter
│   │   ├── exceptions.py        # кастомные HTTP-исключения
│   │   └── logging_config.py    # JSON-логирование
│   ├── models/                  # SQLAlchemy 2.0 модели
│   │   ├── user.py
│   │   ├── workspace.py
│   │   ├── project.py           # Project, ProjectMember, Section, Tag
│   │   ├── task.py              # Task, Subtask, TaskDependency, task_tags (M2M)
│   │   ├── comment.py           # Comment, Attachment
│   │   ├── notification.py
│   │   └── dependency.py        # TimeLog
│   ├── schemas/                 # Pydantic v2 схемы
│   ├── services/
│   │   ├── reorder.py           # бизнес-логика пересчёта order при drag-and-drop
│   │   ├── notification.py      # создание уведомлений, парсинг @mentions
│   │   ├── dependencies.py      # проверка циклических зависимостей
│   │   ├── timelog.py           # парсинг "1h 30m" → секунды
│   │   └── storage.py           # сохранение файлов локально
│   ├── routers/
│   │   ├── auth.py              # /auth/*
│   │   ├── workspaces.py        # /workspaces/*
│   │   ├── projects.py          # /projects/*, /projects/{id}/sections, /tags
│   │   ├── tasks.py             # /projects/{id}/tasks, /tasks/{id}/*
│   │   ├── notifications.py     # /notifications/*
│   │   └── ws.py                # /projects/{id}/ws (WebSocket)
│   └── utils/
├── alembic/                     # миграции
├── tests/                       # PyTest (RBAC, reorder, deps, auth, tasks)
├── uploads/                     # локальное хранилище файлов
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── alembic.ini
└── pytest.ini
```

## Основные эндпоинты

### Auth (`/api/v1/auth`)
| Метод | Путь | Описание |
|------|------|----------|
| POST | `/auth/register` | Регистрация (+ создание workspace или приглашение) |
| POST | `/auth/login` | Вход, возвращает access + refresh |
| POST | `/auth/refresh` | Обновление access-токена |
| POST | `/auth/forgot-password` | Запрос сброса пароля |
| GET  | `/auth/me` | Данные текущего пользователя |

### Workspaces (`/api/v1/workspaces`)
| Метод | Путь | Описание |
|------|------|----------|
| POST | `/workspaces` | Создание workspace |
| GET  | `/workspaces/{id}` | Информация о workspace |
| GET  | `/workspaces/{id}/members` | Список участников |
| POST | `/workspaces/{id}/invite` | Приглашение по email |
| PUT  | `/workspaces/{id}/members/{user_id}` | Смена роли участника |

### Projects (`/api/v1/projects`)
| Метод | Путь | Описание |
|------|------|----------|
| POST | `/projects` | Создание проекта (admin/owner) |
| GET  | `/projects` | Список доступных проектов |
| GET  | `/projects/{id}` | Детали проекта |
| PUT  | `/projects/{id}` | Обновление настроек (manager) |
| POST | `/projects/{id}/members` | Добавление участника (manager) |
| POST | `/projects/{id}/sections` | Создание колонки |
| PUT  | `/projects/{id}/sections/{section_id}` | Переименование/порядок |
| POST | `/projects/{id}/tags` | Создание тега |
| GET  | `/projects/{id}/tags` | Список тегов |
| GET  | `/projects/{id}/tasks` | Список задач с фильтрами |

### Tasks (`/api/v1`)
| Метод | Путь | Описание |
|------|------|----------|
| POST | `/projects/{id}/tasks` | Создание задачи |
| GET  | `/tasks/search?q=...` | Глобальный поиск |
| GET  | `/tasks/{id}` | Детали (с подзадачами, тегами) |
| PUT  | `/tasks/{id}` | Обновление |
| PATCH| `/tasks/{id}/move` | Drag-and-drop (возвращает обновлённые порядки) |
| DELETE | `/tasks/{id}` | Удаление (manager) |
| POST | `/tasks/{id}/subtasks` | Подзадача |
| PATCH| `/tasks/{id}/subtasks/{subtask_id}` | Обновление подзадачи |
| POST | `/tasks/{id}/dependencies` | Создание связи (с проверкой циклов) |
| GET  | `/tasks/{id}/dependencies` | Список blocking/blocked_by |
| DELETE | `/tasks/{id}/dependencies/{dep_id}` | Удаление связи |
| POST | `/tasks/{id}/comments` | Комментарий |
| GET  | `/tasks/{id}/comments` | Список комментариев |
| POST | `/tasks/{id}/attachments` | Загрузка файла (multipart) |
| POST | `/tasks/{id}/timelogs` | Логирование времени |
| GET  | `/tasks/{id}/timelogs` | Список логов (курсорная пагинация) |
| GET  | `/tasks/{id}/activities` | История изменений (audit log, курсорная пагинация) |

### Notifications (`/api/v1/notifications`)
| Метод | Путь | Описание |
|------|------|----------|
| GET  | `/notifications` | Список (с `unread_only=true`) |
| POST | `/notifications/{id}/read` | Отметить прочитанным |
| POST | `/notifications/read-all` | Отметить все |

### WebSocket
```
ws://api/v1/projects/{project_id}/ws?token=JWT_ACCESS_TOKEN
```
События: `task.created`, `task.updated`, `task.moved`, `task.deleted`,
`subtask.created`, `subtask.updated`, `comment.created`, `attachment.created`,
`dependency.created`, `dependency.deleted`.

## Примеры использования

### Регистрация и создание проекта
```bash
# Регистрируемся
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","username":"alice","password":"Password123!","workspace_name":"Alice WS"}'
# → {"access_token":"...","refresh_token":"..."}

# Создаём проект
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"<WORKSPACE_ID>","name":"My First Project"}'

# Создаём колонку
curl -X POST http://localhost:8000/api/v1/projects/<PROJECT_ID>/sections \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"To Do","type":"todo"}'

# Создаём задачу
curl -X POST http://localhost:8000/api/v1/projects/<PROJECT_ID>/tasks \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"section_id":"<SECTION_ID>","title":"Implement API","priority":"high"}'

# Перемещаем задачу (drag-and-drop)
curl -X PATCH http://localhost:8000/api/v1/tasks/<TASK_ID>/move \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"section_id":"<NEW_SECTION_ID>","order":0}'
```

### Логирование времени
```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK_ID>/timelogs \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"spent_time":"1h 30m","description":"Рефакторинг"}'
```

## Ролевая модель

### Глобальные роли (Workspace)
| Роль | Возможности |
|------|-------------|
| `owner` | Полный доступ, биллинг, удаление организации |
| `admin` | Управление пользователями, создание проектов, интеграции |
| `member` | Базовый доступ, может быть добавлен в проекты |
| `guest` | Доступ только к явно приглашённым проектам |

### Проектные роли
| Роль | Возможности |
|------|-------------|
| `manager` | Настройки проекта, участники, удаление задач |
| `editor` | Создание/редактирование задач, комментарии, файлы |
| `viewer` | Только просмотр и скачивание файлов |

## Безопасность

- Все входные данные валидируются через Pydantic v2
- Пароли хешируются через bcrypt (`passlib`)
- JWT access (30 мин) + refresh (7 дней)
- CORS настраивается через `CORS_ORIGINS`
- SQL-инъекции предотвращаются через ORM (без raw SQL)
- Rate limiting (опц. через Redis): 100 запросов/мин/пользователь
- Загрузка файлов: проверка MIME + лимит 10 МБ

## Производительность

- Все списочные эндпоинты поддерживают пагинацию (`limit`, `offset`)
- Индексы БД на `assignee_id`, `project_id`, `section_id`, `task_id`
- `selectinload` для избегания N+1 проблемы при загрузке задач с тегами и исполнителем
- Предзагрузка связанных данных (`assignee`, `reporter`, `tags`, `subtasks`)

## Лицензия

MIT
