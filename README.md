# cafe-provans
Сайт для ресторану Provans який знаходиться в місті Болехів із AI офіціантом


## Backend

**Запуск:** `cp .env.example .env`, підставити пароль БД, далі `docker compose up --build`.
API: `/api/v1/...`, перевірка стану: `/health`, документація: `/docs` (вимкнена в production).

**Тести** (потрібна піднята БД; створюється окрема база `<DB_NAME>_test`, робочу вони не чіпають):

```
docker compose exec backend pip install -r requirements-dev.txt
docker compose exec backend pytest
```

**Як влаштований модуль** (еталон: `backend/app/modules/categories`):

| Файл | За що відповідає |
|---|---|
| `schemas.py` | що приймаємо й віддаємо: `Create` / `Update` / `Read` |
| `service.py` | уся бізнес-логіка та транзакція: метод, що пише, сам викликає `commit()`; кидає `NotFoundError`, `ConflictError` тощо, про HTTP не знає |
| `router.py` | лише HTTP: розбір запиту, права (`require_roles`), виклик сервісу |

Новий модуль: скопіювати `categories`, замінити модель і підключити роутер у `backend/app/api/router.py`.

**Помилки** завжди в одному форматі: `{"error": {"code", "message", "details", "request_id"}}`. `code` для фронтенду, `message` для людини, `request_id` збігається із заголовком `X-Request-ID` і рядком у логах.

**Права:** `Depends(require_roles(UserRole.waiter))`, адмін проходить скрізь. Доки не реалізований вхід, захищені ендпоінти відповідають 401.
