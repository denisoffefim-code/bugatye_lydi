FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY analytics_api ./analytics_api
COPY forecast_service ./forecast_service
COPY skycast ./skycast
COPY telemetry_service ./telemetry_service

EXPOSE 8080

ENV APP_MODULE=analytics_api.app:app
ENV APP_PORT=8080

CMD ["sh", "-c", "uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port \"$APP_PORT\""]
