"""Shared SQL fragments for latest-forecast selection."""

from __future__ import annotations


def forecast_source_sql(forecast_run_alias: str = "fr") -> str:
    del forecast_run_alias
    return "'forecast'"


FORECAST_SOURCE_SQL = forecast_source_sql()

LATEST_FORECAST_CONTRACT = (
    "Within the same station_id + forecast_date + horizon_days + provider + model, "
    "the latest forecast is the row with the greatest run_at; ties are broken by "
    "forecast_runs.id DESC and forecast_values.id DESC."
)


def latest_forecast_identity_sql(
    *,
    forecast_value_alias: str = "fv",
    forecast_run_alias: str = "fr",
) -> str:
    return ",\n                ".join(
        [
            f"{forecast_value_alias}.station_id",
            f"{forecast_value_alias}.forecast_date",
            f"{forecast_value_alias}.horizon_days",
            f"{forecast_run_alias}.provider",
            f"{forecast_run_alias}.model",
        ]
    )


def latest_forecast_order_by_sql(
    *,
    forecast_value_alias: str = "fv",
    forecast_run_alias: str = "fr",
) -> str:
    return ",\n                ".join(
        [
            latest_forecast_identity_sql(
                forecast_value_alias=forecast_value_alias,
                forecast_run_alias=forecast_run_alias,
            ),
            f"{forecast_run_alias}.run_at DESC",
            f"{forecast_run_alias}.id DESC",
            f"{forecast_value_alias}.id DESC",
        ]
    )
