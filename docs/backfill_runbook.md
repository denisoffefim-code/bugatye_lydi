# Historical Forecast Backfill Runbook

## Purpose

Этот runbook описывает безопасный historical backfill Open-Meteo `previous_runs`,
policy для outbox и валидацию результата после rerun.

## Recommended mode

- Для больших исторических прогонов использовать `--skip-outbox`.
- Включать transport-события только если downstream действительно должен получить replay historical forecast payloads.
- Для обычного analytics/backfill пополнения БД писать данные напрямую в `forecast_runs` / `forecast_values` без массового fan-out в `service_outbox`.

## Example command

```bash
python data_loaders/load_open_meteo_backfill.py \
  --start-date 2021-03-01 \
  --end-date 2026-07-08 \
  --chunk-days 120 \
  --horizon 1 \
  --horizon 2 \
  --horizon 3 \
  --horizon 4 \
  --horizon 5 \
  --horizon 6 \
  --horizon 7 \
  --skip-outbox
```

## Safe rerun contract

- Повторный запуск безопасен: каждый rerun создает новый `forecast_runs.id`.
- Данные одного run идемпотентны внутри себя за счет `UNIQUE (run_id, station_id, forecast_date)` в `forecast_values`.
- Аналитика выбирает latest forecast внутри ключа `station_id + forecast_date + horizon_days + provider + model`.
- Основной порядок выбора: `run_at DESC`; tie-break: `forecast_runs.id DESC`, затем `forecast_values.id DESC`.
- Старые historical runs сохраняются для аудита и сравнения, но не должны побеждать более новый rerun в аналитике.

## Retry policy

- Держать `--retry-count` больше 1 для сетевых проблем Open-Meteo.
- Не раздувать `--max-parallel-requests` выше уровня, который начинает давать rate limiting.
- При длинных диапазонах уменьшать `--chunk-days`, если появляются таймауты или слишком долгие run'ы.

## Validation after run

1. Проверить список запусков:

```text
GET /api/forecast-runs?model=best_match
```

2. Проверить coverage по `model/source/horizon`:

```text
GET /api/analytics/forecast-coverage?model=best_match
```

3. Проверить общие totals и backlog:

```text
GET /api/analytics/coverage
```

4. Если нужен точечный контроль по станции:

```text
GET /api/analytics/station-series?station_id=...&start_date=...&end_date=...&horizon_days=...
```

## What to record after completion

- фактический диапазон дат по каждому `horizon_days`;
- число станций с coverage;
- заполненность `avg_temp`, `min_temp`, `max_temp`, `precipitation`, `max_wind_speed`;
- список станций и диапазонов, где Open-Meteo вернул пропуски или ошибки.
