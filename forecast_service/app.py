"""Forecast service entrypoint."""

from skycast.main import backfill_station_coordinates, fetch_forecasts
from skycast.service_runtime import create_service_app


app = create_service_app(title="SkyCast Forecast Service")
app.add_api_route("/api/stations/backfill-coordinates", backfill_station_coordinates, methods=["POST"])
app.add_api_route("/api/forecasts/fetch", fetch_forecasts, methods=["POST"])
