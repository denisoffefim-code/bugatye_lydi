"""Telemetry service entrypoint."""

from skycast.main import ingest_telemetry
from skycast.service_runtime import create_service_app


app = create_service_app(title="SkyCast Telemetry Service")
app.add_api_route("/api/telemetry", ingest_telemetry, methods=["POST"])
