# Сервис анализа и сравнения реальной погоды с предсказанной

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
