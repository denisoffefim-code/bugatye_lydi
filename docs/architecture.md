# SkyCast V1 Architecture

## Scope

Первая версия системы должна решать одну прикладную задачу: показывать самые большие ошибки прогноза по станциям и датам. При этом кодовая база должна уже быть разложена не как один backend, а как набор отдельных сервисов с явным аналитическим слоем.

В первую итерацию входят:

- `forecast-service` для загрузки прогноза и backfill координат станций;
- `telemetry-service` для приема фактической погоды;
- `analytics-api` для чтения агрегатов и аналитических представлений;
- PostgreSQL как основной operational store;
- `users` и `auth_sessions` в той же PostgreSQL для базового auth;
- staging/raw слои внутри PostgreSQL с последующим переходом к отдельному DWH;
- dev-запуск через `docker-compose`;
- probes `live` / `ready` / `health`.

Не входят в первую итерацию как готовая реализация, но должны учитываться в дизайне:

- Redis Streams или Kafka;
- S3/Object Storage для сырого архива;
- отдельные Kubernetes-манифесты;
- UI.

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

Текущая реализация в репозитории:

- `raw_telemetry_events` для сырых событий телеметрии;
- `raw_forecast_events` для сырых событий прогноза;
- `weather_data` и `forecast_values` фактически играют роль `ods`;
- `dm_forecast_errors` как аналитическая read-витрина поверх последних прогнозов и факта;
- `service_outbox` и отдельный worker для публикации событий в Redis Streams и Kafka.

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
- разделение read и write трафика по сервисам;
- локальный spool у producer/worker при недоступности очереди.

Текущая реализация дедупликации:

- телеметрия дедуплицируется ключом `telemetry:{wmo_index}:{observation_date}`;
- прогноз дедуплицируется ключом `forecast:{run_id}:{station_id}:{forecast_date}`;
- transport-события публикуются из `service_outbox` одновременно в Redis Streams и Kafka;
- `message_key` сохраняется в обоих transport’ах как downstream dedupe key.
- при ошибке публикации сообщение дополнительно зеркалируется в локальный spool-каталог и replay'ится после восстановления брокеров.

Следующий шаг после этого коммита:

- перенести аналитику на отдельные `dm_*` представления.
- добавить OpenTelemetry tracing;
- подготовить Kubernetes manifests для Yandex Cloud.

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
- ingest lag / queue lag;
- alerting на недоступность БД и массовые ошибки прогноза.
