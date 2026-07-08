# Сервис анализа и сравнения реальной погоды с предсказанной

## Local Docker

Локальный стек теперь самодостаточный: `postgres`, `redis`, `kafka`, три API-сервиса и `outbox-worker`.
`docker-compose.yml` больше не зависит от внешней Yandex PostgreSQL и не использует `localhost`
внутри контейнерной сети.

Запуск:

```bash
docker compose up --build
```

Порты:

- `forecast-service`: `http://localhost:8081`
- `telemetry-service`: `http://localhost:8082`
- `analytics-api`: `http://localhost:8083`
- `postgres`: `localhost:5432`
- `redis`: `localhost:6379`
- `kafka`: `localhost:9092`

Compose использует committed env file [deploy/docker/local.env](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/deploy/docker/local.env).
Для запуска приложений вне Docker можно взять за основу [.env.example](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/.env.example).

## Yandex Cloud

Для remote deployment подготовлен набор манифестов в [deploy/yandex-cloud/k8s](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/deploy/yandex-cloud/k8s)
и отдельный runbook в [deploy/yandex-cloud/README.md](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/deploy/yandex-cloud/README.md).

В комплект входят:

- `Namespace`, `ConfigMap`, runtime `Secret` template;
- secret template для Yandex CA certificate;
- `migration Job`;
- `Deployment`/`Service`/`HPA`/`PDB` для `forecast-service`, `telemetry-service`, `analytics-api`;
- `StatefulSet`/`HPA`/`PDB` для `outbox-worker`;
- базовый `Ingress`.

Для managed Kafka добавлены env-параметры `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SSL_CAFILE`,
`KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD`.

## Bulk backfill

Для historical backfill Open-Meteo можно отключать массовую публикацию
`forecast.accepted` в `service_outbox`, если прогон нужен только для наполнения БД
и аналитики.

CLI:

```bash
python data_loaders/load_open_meteo_backfill.py \
  --start-date 2021-03-01 \
  --end-date 2026-07-08 \
  --skip-outbox
```

HTTP API:

```json
{
  "start_date": "2021-03-01",
  "end_date": "2022-03-01",
  "source": "previous_runs",
  "archive_horizon_days": 1,
  "publish_outbox_events": false
}
```

Coverage по historical forecast:

```text
GET /api/analytics/forecast-coverage?source=previous_runs&model=best_match
```

Safe rerun policy и operational steps описаны в [docs/backfill_runbook.md](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/docs/backfill_runbook.md).

## Access model

Текущие роли:

- `viewer`: read-only доступ к станциям, forecast runs и аналитике;
- `analyst`: права `viewer` плюс `POST /api/telemetry`;
- `admin`: права `analyst` плюс forecast fetch/backfill, service coverage и revoke user sessions.

Подробная схема split-service auth и role matrix описаны в [docs/architecture.md](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/docs/architecture.md).
