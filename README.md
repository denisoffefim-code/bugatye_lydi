# SkyCast

FastAPI-бэкенд для сравнения прогноза погоды с фактической телеметрией из PostgreSQL в Yandex Cloud.

## Что уже есть

- прямое подключение к удалённой БД `weather` через `DATABASE_URL`;
- миграции, которые расширяют существующую схему:
  - координаты и метаданные NOAA у `stations`;
  - `forecast_runs` и `forecast_values` для хранения прогнозов;
- API для:
  - просмотра станций;
  - просмотра детали станции и покрытия по таблицам;
  - backfill координат станций из NOAA IGRA;
  - приёма телеметрии напрямую в облачную БД;
  - загрузки прогнозов из Open-Meteo;
  - аналитики по самым большим ошибкам прогноза;
  - сводной аналитики, таймсерии по станции и списка запусков прогнозов.

## Структура

- `skycast/` — FastAPI-приложение;
- `data_loaders/` — загрузчики исторических файлов и CLI для первичной remote-загрузки;
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

## Загрузка исторических данных

Remote-загрузчик умеет продолжать загрузку с последнего сохранённого byte offset и теперь настраивается через CLI без правки кода.

```bash
python data_loaders/load_remote.py \
  --source stations \
  --source tttr \
  --source atm8c \
  --download-chunk-size 1048576 \
  --atm8c-batch-size 50000 \
  --loader-max-retries 8 \
  --loader-retry-delay 10 \
  --db-command-timeout 0 \
  --http-sock-read-timeout 1800
```

Полезные параметры:

- `--weather-batch-size`, `--atm8c-batch-size`, `--srok8c-batch-size` — размер батча на вставку в PostgreSQL;
- `--download-chunk-size` — размер HTTP-чанка в байтах;
- `--loader-max-retries`, `--loader-retry-delay` — повторные попытки и стартовая задержка при обрыве;
- `--db-command-timeout 0` — отключает timeout asyncpg для долгих `COPY` и больших `INSERT`;
- `--http-total-timeout`, `--http-connect-timeout`, `--http-sock-read-timeout` — таймауты сетевого клиента.

## Основные эндпоинты

- `GET /health`
- `GET /api/stations`
- `GET /api/stations/{station_id}/details`
- `POST /api/stations/backfill-coordinates`
- `POST /api/telemetry`
- `POST /api/forecasts/fetch`
- `GET /api/forecast-runs`
- `GET /api/analytics/top-errors`
- `GET /api/analytics/summary`
- `GET /api/analytics/worst-stations`
- `GET /api/analytics/station-series`
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
