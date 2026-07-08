# Yandex Cloud Deployment

## Scope

Этот каталог предназначен для remote deployment SkyCast в `Managed Service for Kubernetes`
с контейнерными образами из `Container Registry` и внешними managed зависимостями.

Подразумевается:

- `Managed PostgreSQL`;
- `Managed Redis` или совместимый Redis endpoint;
- `Managed Kafka` или совместимый Kafka endpoint;
- CA certificate Yandex Cloud, смонтированный в pod'ы как secret.

## Build and push image

```bash
docker build -t skycast:latest .
docker tag skycast:latest cr.yandex/<registry-id>/skycast:<image-tag>
docker push cr.yandex/<registry-id>/skycast:<image-tag>
```

Рекомендуемая tagging strategy:

- immutable tag: commit SHA, например `cr.yandex/<registry-id>/skycast:git-<sha>`;
- optional release tag: `cr.yandex/<registry-id>/skycast:release-<version>`.

После этого замени `cr.yandex/replace-me/skycast:replace-me` в манифестах на реальный образ.

## Prepare secrets

1. Скопируй [k8s/02-runtime-secrets.template.yaml](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/deploy/yandex-cloud/k8s/02-runtime-secrets.template.yaml) и подставь реальные значения.
2. Скопируй [k8s/03-yandex-ca-secret.template.yaml](/C:/Users/Дарья/Documents/programming_projects/lshpi/bugatye_lydi/deploy/yandex-cloud/k8s/03-yandex-ca-secret.template.yaml) и вставь актуальный CA certificate.
3. Проверь, что `DATABASE_URL` и `KAFKA_SSL_CAFILE` указывают на `/etc/ssl/certs/yandex-cloud/yandex-ca.pem`.

## Apply order

```bash
kubectl apply -f deploy/yandex-cloud/k8s/00-namespace.yaml
kubectl apply -f deploy/yandex-cloud/k8s/01-shared-config.yaml
kubectl apply -f deploy/yandex-cloud/k8s/02-runtime-secrets.template.yaml
kubectl apply -f deploy/yandex-cloud/k8s/03-yandex-ca-secret.template.yaml
kubectl apply -f deploy/yandex-cloud/k8s/04-migration-job.yaml
kubectl wait --for=condition=complete job/skycast-migrations -n skycast --timeout=300s
kubectl apply -f deploy/yandex-cloud/k8s/10-forecast-service.yaml
kubectl apply -f deploy/yandex-cloud/k8s/11-telemetry-service.yaml
kubectl apply -f deploy/yandex-cloud/k8s/12-analytics-api.yaml
kubectl apply -f deploy/yandex-cloud/k8s/13-outbox-worker.yaml
kubectl apply -f deploy/yandex-cloud/k8s/20-ingress.yaml
```

## Notes

- В remote manifests `STARTUP_MIGRATE=false`, миграции выполняются отдельным `Job`.
- `outbox-worker` оформлен как `StatefulSet`, чтобы каждая реплика имела свой spool volume.
- `Ingress` задан как базовый Kubernetes `Ingress` с `ingressClassName: alb`. Если в кластере
  используется другой ingress controller, замени `ingressClassName` и hosts.
- Для managed Kafka нужен `SASL_SSL`-совместимый набор env vars:
  `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME`,
  `KAFKA_SASL_PASSWORD`, `KAFKA_SSL_CAFILE`.

## Smoke checks

После деплоя:

```bash
kubectl get pods -n skycast
kubectl get ingress -n skycast
kubectl logs job/skycast-migrations -n skycast
kubectl port-forward svc/analytics-api 8083:80 -n skycast
```

Проверки:

- `GET /live`
- `GET /ready`
- `GET /metrics`
- `GET /api/analytics/coverage`
