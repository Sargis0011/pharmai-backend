# PharmAI backend (FastAPI + SQLite)

## Запуск

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API: http://127.0.0.1:8000  ·  Swagger: http://127.0.0.1:8000/docs

При первом старте автоматически выполняется seed:
1. Пробует подтянуть открытый реестр (`pharm.am`).
2. Если недоступен — использует встроенный fallback (~80 препаратов на HY/RU/EN).

Принудительно пересоздать БД:
```bash
curl -X POST http://127.0.0.1:8000/admin/sync
# или
python -m app.seed
```

## Endpoints

| Метод | URL | Описание |
| --- | --- | --- |
| GET | `/medicines?q=...&category=...&limit=&offset=` | Поиск (HY/RU/EN/INN, case-insensitive, частичный) |
| GET | `/medicines/{id}` | Карточка лекарства |
| GET | `/medicines/categories` | Список категорий с количеством |
| GET | `/medicines/stats` | Общая статистика |
| GET | `/analogs/{id}` | Аналоги по `active_substance` |
| GET | `/pharmacies` | Все аптеки (только название) |
| GET | `/pharmacies/medicine/{id}` | Аптеки, где доступен препарат |
| POST | `/admin/sync` | Принудительный re-seed |
