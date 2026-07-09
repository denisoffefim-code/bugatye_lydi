# SkyCast V1 Architecture

## Scope

Первая версия системы должна решать одну прикладную задачу: показывать самые большие ошибки прогноза по станциям и датам. При этом кодовая база должна уже быть разложена не как один backend, а как набор отдельных сервисов с явным аналитическим слоем.

В первую итерацию входят:

- `forecast-service` для загрузки прогноза и backfill координат станций;
- `telemetry-service` для приема фактической погоды;
- `analytics-api` для чтения агрегатов и аналитических представлений;
- PostgreSQL как основной operational store;
- `users` и `auth_sessions` в той же PostgreSQL для базового auth;
- RBAC-роли `admin`, `analyst`, `viewer`;
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
- `GET /api/analytics/forecast-coverage`
- `GET /api/admin/transports/overview` (мониторинг событий)
- `GET /live`
- `GET /ready`
- `GET /health`

### outbox-worker

Ответственность (фоновый процесс, не HTTP-сервис):

- опросить `service_outbox` таблицу каждые 2 сек;
- публиковать события одновременно в Redis Streams и Kafka;
- управлять retry'ями с экспоненциальным backoff'ом (до 8 попыток, макс. 300 сек);
- дублировать в локальный spool при недоступности брокеров;
- replay'ить из spool после восстановления транспорта.

Конфигурация:

- `OUTBOX_POLL_SECONDS`: 2 сек между опросами
- `OUTBOX_BATCH_SIZE`: 100 сообщений за раз
- `OUTBOX_MAX_ATTEMPTS`: 8 попыток
- `OUTBOX_SPOOL_ENABLED`: локальный spool на диск
- `OUTBOX_SPOOL_DIR`: .skycast-outbox-spool

### transport-observer

Ответственность (фоновый процесс, не HTTP-сервис):

- подписаться на Redis Streams и Kafka topics;
- записывать события в `transport_runtime` таблицу для аудита и мониторинга;
- отслеживать время доставки, количество retry'ев и статусы;
- поддерживать историю для админов.

Конфигурация:

- `TRANSPORT_TOPICS`: какие topics слушать (forecast.accepted, telemetry.accepted)
- `TRANSPORT_RECENT_EVENTS_LIMIT`: 100 последних событий
- `TRANSPORT_EVENT_TTL_SECONDS`: 7 дней (604800 сек)

## Data Flow

### Write Path (Ingest)

1. `forecast-service` загружает прогноз из Open-Meteo:
   - BEGIN TRANSACTION
   - INSERT INTO `raw_forecast_events` (сырой payload, dedupe_key)
   - INSERT INTO `forecast_values` (очищенные данные)
   - INSERT INTO `service_outbox` (событие для публикации)
   - COMMIT TRANSACTION
   - Ответить клиенту (fast)

2. `telemetry-service` принимает фактическую погоду:
   - Валидация payload (WMO код, диапазоны температур)
   - Дедупликация: проверить `dedupe_key` (telemetry:{wmo_index}:{observation_date})
   - BEGIN TRANSACTION
   - INSERT INTO `raw_telemetry_events`
   - INSERT INTO `weather_data`
   - INSERT INTO `service_outbox`
   - COMMIT TRANSACTION
   - Ответить клиенту (fast)

3. `outbox-worker` публикует события (асинхронно):
   - Каждые 2 сек: SELECT * FROM `service_outbox` WHERE status='pending' LIMIT 100
   - Для каждого сообщения:
     - Опубликовать в Redis Stream: `skycast.{topic}`
     - Опубликовать в Kafka topic: `skycast.{topic}`
     - UPDATE `service_outbox` SET status='published'
   - При ошибке: UPDATE с попыткой+1, вычислить next_retry_at с экспоненциальным backoff
   - Дополнительно зеркалировать в локальный spool (файлы)

### Read Path (Analytics)

1. `analytics-api` читает витрины (при запросе):
   - Проверить Redis кэш (TTL 300 сек)
   - Если кэш miss: SQL JOIN forecast_values + weather_data
   - Вычислить absolute_error, error_rank
   - Закэшировать в Redis
   - Вернуть клиенту

2. `transport-observer` (асинхронно) слушает события:
   - Subscribe на Redis Streams и Kafka topics
   - Записывать каждое событие в `transport_runtime` таблицу
   - Для мониторинга и аудита

### Слои данных

Целевая эволюция хранения:

- `raw`: входящие payload и staging-таблицы;
- `ods`: очищенные, дедуплицированные факты и прогнозы;
- `dm`: витрины под аналитику.

Текущая реализация в репозитории:

- **RAW слой**:
  - `raw_telemetry_events` для сырых событий телеметрии (JSONB payload)
  - `raw_forecast_events` для сырых событий прогноза (JSONB payload)

- **ODS слой** (Operational Data Store):
  - `weather_data` – очищенные фактические наблюдения с индексом по (station_id, observation_date)
  - `forecast_values` – прогнозы с UNIQUE constraint по (run_id, station_id, forecast_date)
  - `forecast_runs` – запуски загрузок с метаданными и статусом

- **DM слой** (Data Mart, витрины для аналитики):
  - `dm_forecast_errors` – READ-витрина: сопоставление forecast vs actual с вычисленной ошибкой

- **Service Layer**:
  - `service_outbox` – события для публикации в очереди (topic, message_key, payload, attempts, status)
  - `transport_runtime` – история событий для мониторинга (что и когда было опубликовано)

Ключевая витрина V1: `dm_forecast_errors`

- `station_id`
- `forecast_date`
- `model`
- `horizon_days`
- `forecast_value`
- `actual_value`
- `absolute_error`
- `error_rank`

Контракт `latest forecast`:

- идентичность прогноза задается ключом `station_id + forecast_date + horizon_days + provider + model + source`;
- аналитика и `station-series` выбирают запись с максимальным `run_at` внутри этого ключа;
- если `run_at` совпал, tie-break идет по `forecast_runs.id DESC`, затем по `forecast_values.id DESC`;
- разные `horizon_days`, `model` или `source` не схлопываются в одну запись и живут как отдельные forecast variants.

## Reliability

На текущем шаге уже реализованы:

- идемпотентность загрузки телеметрии и прогноза
- retry/backoff на внешних HTTP-вызовах
- liveness/readiness/health endpoints
- разделение read и write трафика по сервисам
- Service Outbox Pattern для гарантированной доставки

### Дедупликация

**Телеметрия:** ключ `telemetry:{wmo_index}:{observation_date}`
- UNIQUE constraint предотвращает вставку дубля
- Повторный POST того же факта безопасен (идемпотентно)

**Прогноз:** ключ `forecast:{run_id}:{station_id}:{forecast_date}`
- UNIQUE constraint на dedupe_key
- Безопасен при retry'ях загрузки

### Service Outbox Pattern

Гарантированная доставка событий в очереди (Redis + Kafka):

1. **WRITE фаза** (синхронно):
   - BEGIN TRANSACTION
   - INSERT INTO forecast_values/weather_data (главное действие)
   - INSERT INTO service_outbox (событие для публикации)
   - COMMIT

2. **PUBLISH фаза** (асинхронно, worker'ом):
   - SELECT * FROM service_outbox WHERE status='pending' LIMIT 100
   - Для каждого сообщения:
     - Опубликовать в Redis Stream
     - Опубликовать в Kafka
     - UPDATE service_outbox SET status='published'
   - При ошибке: exponential backoff + дублировать в локальный spool

3. **REPLAY фаза** (при восстановлении):
   - Прочитать spool-файлы и пересылать события

**Преимущества:**
- ✅ Гарантия: событие не потеряется, даже если Kafka упал
- ✅ Скорость write: асинхронная публикация
- ✅ Retry: до 8 попыток с экспоненциальной задержкой (макс 300 сек)
- ✅ Durability: локальный spool на диск
- ✅ Deduplication: message_key используется в обоих transport'ах

### HTTP Retry и Rate Limiting

При запросах к Open-Meteo и NOAA IGRA:

- `AsyncRateLimiter`: встроенный (default 3 req/sec)
- `with_retries()`: retry на 5xx и timeout
- `request_timeout_seconds`: 45 сек
- `max_parallel_requests`: 4 одновременных запроса

### Health Probes

Каждый сервис предоставляет:

- `GET /live` – liveness probe (для K8s restart)
- `GET /ready` – readiness probe (для traffic routing)
- `GET /health` – общий status

Следующий шаг после этого коммита:

- перенести аналитику на отдельные `dm_*` представления
- добавить OpenTelemetry tracing
- подготовить Kubernetes manifests для Yandex Cloud
- мониторинг outbox lag и queue depth

Historical backfill и safe rerun policy описаны в [backfill_runbook.md](backfill_runbook.md).

## Auth And Access

Текущая auth-схема для split services:

- `forecast-service`, `telemetry-service` и `analytics-api` используют один и тот же bearer token format;
- каждая HTTP-нода валидирует токен напрямую по общим таблицам `users` и `auth_sessions` в PostgreSQL;
- отдельного auth gateway сейчас нет, это остается отдельным deployment-решением;
- legacy-роль `user` нормализуется в `viewer`.

Текущая role matrix:

- `viewer`: `GET /api/stations`, `GET /api/stations/{station_id}/details`, `GET /api/forecast-runs`, `GET /api/analytics/top-errors`, `GET /api/analytics/summary`, `GET /api/analytics/worst-stations`, `GET /api/analytics/station-series`, `GET /api/analytics/forecast-coverage`;
- `analyst`: все права `viewer` плюс `POST /api/telemetry`;
- `admin`: все права `analyst` плюс `POST /api/forecasts/fetch`, `POST /api/stations/backfill-coordinates`, `GET /api/analytics/coverage`, `POST /api/auth/users/{user_id}/logout-sessions`.

## Deployment Shape

### Dev (Docker-Compose)

Поднимает контейнеры из одного репозитория:

- `skycast-postgres:15` – PostgreSQL БД
- `skycast-redis:7` – Redis (Stream + кэш)
- `skycast-kafka:7` – Kafka брокер
- `skycast-forecast-service` (PORT=8081) – загрузка прогнозов
- `skycast-telemetry-service` (PORT=8082) – приём фактов
- `skycast-analytics-api` (PORT=8080) – аналитика и UI
- `skycast-outbox-worker` – фоновый worker для публикации
- `skycast-transport-observer` – слушатель событий
- `skycast-frontend` (PORT=5173, Vite) – React SPA

Все сервисы используют общую БД, разные `APP_MODULE` и `APP_PORT`.

### Production (Kubernetes на Yandex Cloud)

Manifests в `deploy/yandex-cloud/k8s/`:

- `00-namespace.yaml` – namespace `skycast`
- `01-shared-config.yaml` – ConfigMap с settings
- `02-runtime-secrets.yaml` – шаблон для DB URL, API keys, Kafka credentials
- `04-migration-job.yaml` – запуск миграций БД
- `05-redis.yaml` – Redis StatefulSet
- `06-kafka.yaml` – Kafka StatefulSet
- `10-forecast-service.yaml` – Deployment (replica=2)
- `11-telemetry-service.yaml` – Deployment (replica=2)
- `12-analytics-api.yaml` – Deployment (replica=3)
- `13-outbox-worker.yaml` – Deployment (replica=1, distributed lock)
- `14-transport-observer.yaml` – Deployment (replica=1)
- `15-frontend.yaml` – Deployment (replica=2)
- `20-ingress.yaml` – Nginx Ingress с TLS

Запуск: `kubectl apply -f deploy/yandex-cloud/k8s/`

## Observability Baseline

На ближайший этап:

- **Structured logs:** JSON format с полями (timestamp, level, service, user_id, request_id, message)
- **Metrics:**
  - latency/error counters по endpoint
  - ingest lag (задержка между реальным временем и загрузкой прогноза)
  - queue lag (backlog в service_outbox)
  - broker lag (разница между published и consumed в Kafka/Redis)
- **Health checks:**
  - Database availability
  - Redis connection
  - Kafka brokers
  - Forecast API rate limits
- **Alerting:**
  - Недоступность БД
  - Массовые ошибки прогноза (5xx rate > 5%)
  - Outbox backlog > 1000 messages
  - Worker падает больше 2 раз за час

## System Diagram

```
                    ┌──────────────────┐
                    │   FRONTEND       │
                    │   (React/Vite)   │
                    │   port 5173      │
                    └────────┬─────────┘
                             │ HTTP (Bearer Token)
        ┌────────────────────┼────────────────────┐
        │                    │                    │
    ┌───▼────────┐    ┌──────▼──────┐    ┌───────▼────┐
    │ FORECAST   │    │ TELEMETRY   │    │ ANALYTICS  │
    │ SERVICE    │    │ SERVICE     │    │ API        │
    │ 8081       │    │ 8082        │    │ 8080       │
    │            │    │             │    │            │
    │ • Fetch    │    │ • Ingest    │    │ • Read     │
    │   from OM  │    │   facts     │    │   vitrine  │
    │ • NOAA     │    │ • Validate  │    │ • Cache    │
    │   IGRA     │    │ • Dedup     │    │   (Redis)  │
    │ • Write    │    │ • Write ODS │    │ • RBAC     │
    │   to ODS   │    │ • Outbox    │    │            │
    └──┬─────────┘    └──┬──────────┘    └────┬───────┘
       │                  │                    │
       └──────────────────┼────────────────────┘
                          │
                ┌─────────▼──────────┐
                │  PostgreSQL (1 БД) │
                │                    │
                │ • raw_telemetry   │
                │ • raw_forecast    │
                │ • weather_data    │
                │ • forecast_values │
                │ • service_outbox  │
                │ • users/auth      │
                └──────────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
    ┌───▼────────┐    ┌────▼──────┐    ┌─────▼──────┐
    │ Redis      │    │ Kafka     │    │ Spool      │
    │ Streams    │    │ Topics    │    │ (Files)    │
    └────────────┘    └───────────┘    └────────────┘
        ▲                  ▲                  ▲
        │                  │                  │
        └──────┬───────────┼──────────────────┘
               │           │
        ┌──────▼───────────▼──────┐
        │  OUTBOX-WORKER          │
        │  (фоновый процесс)      │
        │                         │
        │ • Poll outbox каждые 2с │
        │ • Publish в Redis+Kafka │
        │ • Retry на ошибку       │
        │ • Спул при отказе       │
        └────────────────────────┘
                    │
        ┌───────────▼────────────┐
        │ TRANSPORT-OBSERVER     │
        │ (слушатель событий)    │
        │                        │
        │ • Subscribe на topics  │
        │ • Record в БД          │
        │ • Мониторинг           │
        └────────────────────────┘
```

## Quick Reference: Endpoints

### forecast-service (8081, admin only)

| Method | Path | Описание |
|--------|------|---------|
| POST | /api/forecasts/fetch | Загрузить прогнозы из Open-Meteo |
| POST | /api/stations/backfill-coordinates | Обновить координаты из NOAA |
| GET | /live, /ready, /health | Health checks |

### telemetry-service (8082, analyst+)

| Method | Path | Описание |
|--------|------|---------|
| POST | /api/telemetry | Отправить фактическое наблюдение |
| GET | /live, /ready, /health | Health checks |

### analytics-api (8080, viewer+)

| Method | Path | Роль | Описание |
|--------|------|------|---------|
| GET | /api/stations | viewer | Список станций |
| GET | /api/stations/{id}/details | viewer | Детали станции |
| GET | /api/forecast-runs | viewer | История запусков |
| GET | /api/analytics/top-errors | viewer | ТОП ошибок |
| GET | /api/analytics/summary | viewer | Сводка |
| GET | /api/analytics/worst-stations | viewer | Худшие станции |
| GET | /api/analytics/station-series | viewer | Серия по станции |
| GET | /api/analytics/forecast-coverage | viewer | Покрытие |
| GET | /api/analytics/coverage | admin | Подробное покрытие |
| POST | /api/auth/register | - | Регистрация |
| POST | /api/auth/login | - | Логин |
| POST | /api/auth/logout | auth | Логаут |
| GET | /api/auth/me | auth | Текущий пользователь |
| POST | /api/auth/users/{id}/logout-sessions | admin | Логаут сессий |
| GET | /api/admin/transports/overview | admin | Мониторинг событий |
| GET | /live, /ready, /health | - | Health checks |

## Key Tables

### Raw Layer

- `raw_telemetry_events`: wmo_index, observation_date, payload (JSONB)
- `raw_forecast_events`: run_id, station_id, forecast_date, payload (JSONB)

### ODS Layer

- `weather_data`: station_id, observation_date, avg_temp, min_temp, max_temp, precipitation
- `forecast_values`: run_id, station_id, forecast_date, horizon_days, temps, wind
- `forecast_runs`: provider, model, run_at, status, error_message

### DM Layer

- `dm_forecast_errors`: station_id, forecast_date, model, forecast_value, actual_value, absolute_error, error_rank

### Service Layer

- `service_outbox`: topic, message_key, payload (JSONB), attempts, status, next_retry_at
- `transport_runtime`: topic, message_key, status, published_at, attempts

### Auth

- `users`: email, password_hash, role (admin/analyst/viewer)
- `auth_sessions`: user_id, token_hash, expires_at, last_used_at
