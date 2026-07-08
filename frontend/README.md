# SkyCast Frontend

Frontend находится в `skycast/bugatye_lydi/frontend` и работает с существующим FastAPI backend из `skycast/bugatye_lydi`.

## Запуск

1. Запустите backend монолитным entrypoint, чтобы были доступны auth и аналитика:

```bash
cd ..
uvicorn skycast.main:app --host 0.0.0.0 --port 8080
```

2. Установите зависимости frontend:

```bash
npm install
```

3. Запустите интерфейс:

```bash
npm run dev
```

По умолчанию Vite проксирует `/api` и `/health` на `http://localhost:8080`. Это можно изменить через `VITE_API_PROXY_TARGET` в `.env`.

## Используемые API

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/stations`
- `GET /api/stations/{station_id}/details`
- `GET /api/forecast-runs`
- `GET /api/analytics/summary`
- `GET /api/analytics/top-errors`
- `GET /api/analytics/worst-stations`
- `GET /api/analytics/station-series`
- `GET /api/analytics/forecast-coverage`
- `GET /api/analytics/coverage` для admin-аккаунта

## Production

Если frontend обслуживается не с того же origin, задайте:

```bash
VITE_API_BASE_URL=https://your-api-host.example.com
```

Затем выполните:

```bash
npm run build
```
