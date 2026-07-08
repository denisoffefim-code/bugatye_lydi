# Yandex Cloud Deployment

## Scope

Этот каталог предназначен для deployment SkyCast в `Managed Service for Kubernetes`
с контейнерными образами из `Container Registry` и минимальным набором in-cluster зависимостей.

Подразумевается:

- `Managed PostgreSQL`;
- Redis в namespace `skycast`;
- Kafka-compatible broker в namespace `skycast`;
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

Текущие манифесты ссылаются на образы:

- `cr.yandex/crp0uld88a95dqoql4bj/skycast:<image-tag>` для backend workloads;
- `cr.yandex/crp0uld88a95dqoql4bj/skycast-frontend:<image-tag>` для frontend.

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
kubectl apply -f deploy/yandex-cloud/k8s/05-redis.yaml
kubectl apply -f deploy/yandex-cloud/k8s/06-kafka.yaml
kubectl apply -f deploy/yandex-cloud/k8s/10-forecast-service.yaml
kubectl apply -f deploy/yandex-cloud/k8s/11-telemetry-service.yaml
kubectl apply -f deploy/yandex-cloud/k8s/12-analytics-api.yaml
kubectl apply -f deploy/yandex-cloud/k8s/13-outbox-worker.yaml
kubectl apply -f deploy/yandex-cloud/k8s/14-transport-observer.yaml
kubectl apply -f deploy/yandex-cloud/k8s/15-frontend.yaml
kubectl apply -f deploy/yandex-cloud/k8s/20-ingress.yaml
```

## Notes

- В manifests `STARTUP_MIGRATE=false`, миграции выполняются отдельным `Job`.
- Все workload'ы рассчитаны на одновузловой кластер и используют `1 replica`.
- Публичный вход идёт через `Ingress` c `ingressClassName: gwin-default`; `skycast-frontend` обслуживает `/`, а `analytics-api` принимает `/api`, `/live`, `/ready`, `/health`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`.
- Сервисы `analytics-api` и `skycast-frontend` имеют тип `NodePort`, потому что этого требует Gwin/Yandex ALB.
- `outbox-worker` оформлен как `StatefulSet`, чтобы spool жил на отдельном PVC.
- `transport-observer` читает Kafka и Redis Streams, а агрегированное audit-state складывает обратно в Redis для admin endpoint `/api/admin/transports/overview`.
- В контейнерах SkyCast задан `runAsUser/runAsGroup=999`, что соответствует пользователю образа.
- Для быстрого человекочитаемого адреса без собственного DNS можно использовать `http://analytics.<INGRESS-IP>.sslip.io`.

## Smoke checks

После деплоя:

```bash
kubectl get pods -n skycast
kubectl get svc -n skycast
kubectl logs job/skycast-migrations -n skycast
kubectl logs statefulset/outbox-worker -n skycast
kubectl logs deployment/transport-observer -n skycast
```

Проверки:

- `kubectl get ingress -n skycast`
- `GET http://skycast.<INGRESS-IP>.sslip.io/`
- `GET http://skycast.<INGRESS-IP>.sslip.io/live`
- `GET http://skycast.<INGRESS-IP>.sslip.io/ready`
- `GET http://skycast.<INGRESS-IP>.sslip.io/metrics`
- `GET http://skycast.<INGRESS-IP>.sslip.io/api/analytics/coverage`
- `GET http://skycast.<INGRESS-IP>.sslip.io/api/admin/transports/overview`
