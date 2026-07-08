# SkyCast V1 Architecture

## Scope

Первая версия системы должна решать одну прикладную задачу: показывать самые большие ошибки прогноза по станциям и датам. При этом кодовая база должна уже быть разложена не как один backend, а как набор отдельных сервисов с явным аналитическим слоем.

В первую итерацию входят:

- `forecast-service` для загрузки прогноза и backfill координат станций;
- `telemetry-service` для приема фактической погоды;
- `analytics-api` для чтения агрегатов и аналитических представлений;
- PostgreSQL как основной operational store;
- staging/raw слои внутри PostgreSQL с последующим переходом к отдельному DWH;
- dev-запуск через `docker-compose`;
- probes `live` / `ready` / `health`.

Не входят в первую итерацию как готовая реализация, но должны учитываться в дизайне:

- Redis Streams или Kafka;
- S3/Object Storage для сырого архива;
- отдельные Kubernetes-манифесты;
- full auth flow и UI.

## Service Boundaries

### forecast-service

Ответственность:

- загрузка прогнозов из Open-Meteo;
- загрузка и актуализация координат станций из NOAA IGRA;
- запись результата в staging / ingest слой;
- дальнейший переход на producer в очередь без изменения публичного контракта сервиса.

Текущие HTTP-операции:

- `POST /api/forecasts/fetch`
- `POST /api/stations/backfill-coordinates`
- `GET /live`
- `GET /ready`
- `GET /health`

### telemetry-service

Ответственность:

- прием фактической телеметрии;
- валидация payload;
- дедупликация по `station_id + observation_date`;
- запись в ingest/raw слой.

Текущие HTTP-операции:

- `POST /api/telemetry`
- `GET /live`
- `GET /ready`
- `GET /health`

### analytics-api

Ответственность:

- чтение станций, запусков прогноза и аналитических витрин;
- отдача UI-ориентированных read models;
- переход к чтению `dm_*` витрин без изменения внешнего API.

Текущие HTTP-операции:

- `GET /api/stations`
- `GET /api/stations/{station_id}/details`
- `GET /api/forecast-runs`
- `GET /api/analytics/top-errors`
- `GET /api/analytics/summary`
- `GET /api/analytics/worst-stations`
- `GET /api/analytics/station-series`
- `GET /api/analytics/coverage`
- `GET /live`
- `GET /ready`
- `GET /health`

## Data Flow

1. `forecast-service` получает прогноз и пишет результаты в operational store.
2. `telemetry-service` принимает фактическую погоду и нормализует записи.
3. Аналитический слой собирает сопоставление `forecast` vs `actual`.
4. `analytics-api` читает подготовленные read models и отдает UI.

Целевая эволюция хранения:

- `raw`: входящие payload и staging-таблицы;
- `ods`: очищенные, дедуплицированные факты и прогнозы;
- `dm`: витрины под аналитику.

Ключевая витрина V1:

- `dm_forecast_errors`
  - `station_id`
  - `forecast_date`
  - `model`
  - `horizon_days`
  - `forecast_value`
  - `actual_value`
  - `absolute_error`
  - `error_rank`

## Reliability

На текущем шаге уже нужны:

- идемпотентность загрузки телеметрии и прогноза;
- retry/backoff на внешних HTTP-вызовах;
- liveness/readiness/health endpoints;
- разделение read и write трафика по сервисам.

Следующий шаг после этого коммита:

- вынести запись прогноза и телеметрии в outbox;
- подключить Redis Streams или Kafka;
- добавить spool на локальный диск при недоступности очереди;
- перенести аналитику на отдельные `dm_*` представления.

## Deployment Shape

Dev-среда должна поднимать три контейнера из одного репозитория:

- `forecast-service`
- `telemetry-service`
- `analytics-api`

Все сервисы используют общую базу и разные `APP_MODULE` / `APP_PORT`.

## Observability Baseline

Минимальный baseline на ближайший этап:

- structured logs;
- latency/error counters по endpoint;
- ingest lag / queue lag после появления очереди;
- alerting на недоступность БД и массовые ошибки прогноза.
