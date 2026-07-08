"""Analytics API entrypoint."""

from skycast.main import (
    analytics_coverage,
    forecast_coverage,
    analytics_summary,
    auth_me,
    list_forecast_runs,
    list_stations,
    login_user,
    logout_user,
    logout_user_sessions,
    register_user,
    station_details,
    station_series,
    transport_overview,
    top_errors,
    worst_stations,
)
from skycast.service_runtime import create_service_app


app = create_service_app(title="SkyCast Analytics API")
app.add_api_route("/api/auth/register", register_user, methods=["POST"], status_code=201)
app.add_api_route("/api/auth/login", login_user, methods=["POST"])
app.add_api_route("/api/auth/logout", logout_user, methods=["POST"], status_code=204)
app.add_api_route("/api/auth/users/{user_id}/logout-sessions", logout_user_sessions, methods=["POST"], status_code=204)
app.add_api_route("/api/auth/me", auth_me, methods=["GET"])
app.add_api_route("/api/stations", list_stations, methods=["GET"])
app.add_api_route("/api/stations/{station_id}/details", station_details, methods=["GET"])
app.add_api_route("/api/forecast-runs", list_forecast_runs, methods=["GET"])
app.add_api_route("/api/analytics/top-errors", top_errors, methods=["GET"])
app.add_api_route("/api/analytics/summary", analytics_summary, methods=["GET"])
app.add_api_route("/api/analytics/worst-stations", worst_stations, methods=["GET"])
app.add_api_route("/api/analytics/station-series", station_series, methods=["GET"])
app.add_api_route("/api/analytics/coverage", analytics_coverage, methods=["GET"])
app.add_api_route("/api/analytics/forecast-coverage", forecast_coverage, methods=["GET"])
app.add_api_route("/api/admin/transports/overview", transport_overview, methods=["GET"])
