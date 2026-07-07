# SkyCast

FastAPI-бэкенд для сравнения прогноза погоды с фактической телеметрией из PostgreSQL в Yandex Cloud.

## Что уже есть

- прямое подключение к удалённой БД `weather` через `DATABASE_URL`;
- миграции, которые расширяют существующую схему:
  - координаты и метаданные NOAA у `stations`;
  - `forecast_runs` и `forecast_values` для хранения прогнозов;
- API для:
  - просмотра станций;
  - backfill координат станций из NOAA IGRA;
  - приёма телеметрии напрямую в облачную БД;
  - загрузки прогнозов из Open-Meteo;
  - аналитики по самым большим ошибкам прогноза.

## Структура

- `skycast/` — FastAPI-приложение;
- `data_loaders/` — старая заготовка загрузчика, оставлена как референс;
- `er_diagram.png` — исходная ER-диаграмма текущей БД.

## Быстрый старт

1. Подготовьте `.env` по образцу `.env.example`.
2. Убедитесь, что `DATABASE_URL` указывает на облачную БД и путь к `yandex-ca.pem` корректен.
3. Установите зависимости:

```bash
pip install -r requirements.txt
```

4. Запустите API:

```bash
uvicorn skycast.main:app --reload --port 8080
```

## Основные эндпоинты

- `GET /health`
- `GET /api/stations`
- `POST /api/stations/backfill-coordinates`
- `POST /api/telemetry`
- `POST /api/forecasts/fetch`
- `GET /api/analytics/top-errors`
- `GET /api/analytics/coverage`

## Примеры запросов

### Backfill координат станций

```bash
curl -X POST http://localhost:8080/api/stations/backfill-coordinates \
  -H "Content-Type: application/json" \
  -d "{\"dry_run\": true}"
```

### Загрузка прогноза

```bash
curl -X POST http://localhost:8080/api/forecasts/fetch \
  -H "Content-Type: application/json" \
  -d "{\"start_date\":\"2026-07-07\",\"end_date\":\"2026-07-10\",\"limit\":10}"
```

### Топ ошибок прогноза

```bash
curl "http://localhost:8080/api/analytics/top-errors?start_date=2026-07-01&end_date=2026-07-10&metric=avg_temp&limit=10"
```

## Что дальше

- добрать координаты для станций, которых нет в NOAA IGRA;
- вынести загрузку прогнозов и телеметрии в отдельные сервисы/воркеры;
- добавить Redis/Kafka/outbox для устойчивой очереди;
- добавить авторизацию и фронтенд-аналитику.
