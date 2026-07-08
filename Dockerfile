FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_MODULE=analytics_api.app:app \
    APP_PORT=8080 \
    OUTBOX_SPOOL_DIR=/var/lib/skycast/outbox-spool

WORKDIR /app

RUN groupadd --system skycast \
    && useradd --system --gid skycast --create-home --home-dir /home/skycast skycast \
    && mkdir -p /var/lib/skycast/outbox-spool \
    && chown -R skycast:skycast /var/lib/skycast

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY analytics_api ./analytics_api
COPY forecast_service ./forecast_service
COPY skycast ./skycast
COPY telemetry_service ./telemetry_service

RUN chown -R skycast:skycast /app

USER skycast

EXPOSE 8080

CMD ["sh", "-c", "uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port \"$APP_PORT\""]
