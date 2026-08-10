# Kubernetes манифесты (ROADMAP.md §3.5)

Стартовая точка для деплоя AutoDialer Ultimate в Kubernetes, зеркалирующая
`docker-compose.yml` компонент за компонентом. **Не применялось к реальному
кластеру в этой сессии** — то же ограничение, что и в остальной части проекта (см.
ROADMAP.md §1.4: в песочнице, где это строилось, нет рабочего Docker-демона, тем
более нет Kubernetes-кластера). Валидировано только на синтаксис YAML
(`python3 -c "import yaml; yaml.safe_load_all(...)"` на каждом файле) и на
соответствие портов/переменных окружения/томов из `docker-compose.yml`, `Dockerfile`
и `.env.example`. Считайте это выверенным черновиком, а не доказанным деплоем —
прогоните это полностью на реальном кластере, прежде чем полагаться на него в
продакшене.

## Порядок применения

Файлы пронумерованы, чтобы `kubectl apply -f k8s/` применился чисто за один проход
(namespace → config/secrets → stateful-хранилища → общее хранилище → прикладные слои),
но здесь нет зависимостей через `Job`/хуки — порядок важен только потому, что
Service `postgres` должен существовать до того, как init-контейнер `backend`
попытается выполнить `alembic upgrade head` против него, что сам Kubernetes и
обрабатывает через ретрай/`CrashLoopBackOff`, даже если применить всё одновременно.

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
cp k8s/02-secret.example.yaml k8s/02-secret.yaml   # заполните реальными значениями, в gitignore
kubectl apply -f k8s/02-secret.yaml
kubectl create configmap nginx-conf -n autodialer --from-file=default.conf=nginx/autodialer.conf
kubectl apply -f k8s/10-postgres.yaml
kubectl apply -f k8s/11-redis.yaml
kubectl apply -f k8s/12-shared-storage.yaml
kubectl apply -f k8s/20-asterisk.yaml
kubectl apply -f k8s/30-backend.yaml
kubectl apply -f k8s/40-nginx.yaml
```

## Что нужно сделать перед тем, как это заработает

1. **Собрать и запушить три образа** — ни `autodialer/backend`, ни
   `autodialer/asterisk`, ни `autodialer/nginx` не существуют ни в каком реестре —
   это имена-заглушки. Соберите из `Dockerfile`, `docker/asterisk/Dockerfile`
   и нового однострочного `nginx:alpine` + `COPY frontend/dist` Dockerfile
   соответственно (см. комментарий вверху `40-nginx.yaml`), затем
   запушите в реестр, доступный вашему кластеру, и обновите поля
   `image:`.
2. **Вшить `frontend/dist` в образы при сборке.** `docker-compose.yml`
   бинд-монтирует `./frontend/dist` с хоста в контейнеры `backend` и
   `nginx` — у Kubernetes нет хостовой файловой системы для такого
   монтирования. Добавьте `COPY frontend/dist /srv/frontend` в `Dockerfile`
   (backend отдаёт его через `STATIC_DIR`) и соберите nginx-образ как
   описано выше. Пропуск этого шага означает, что `STATIC_DIR` и кореньвой
   каталог nginx будут пустыми в кластере.
3. **Выбрать RWX-совместимый StorageClass** для `12-shared-storage.yaml`
   (`tts-audio`, `call-recordings`) — оба PVC одновременно монтируются
   asterisk, backend и nginx, что требует `ReadWriteMany`. Большинство
   StorageClass по умолчанию (`gp2`/`gp3`, `standard`, `local-path`) поддерживают
   только `ReadWriteOnce` и оставят эти PVC висеть в `Pending`. Используйте
   NFS-провайдер, EFS (`efs-sc` на EKS), Azure Files (`azurefile` на AKS) или
   аналог, и укажите `storageClassName` в этом файле.
4. **Заполнить `02-secret.yaml`** реальными `DB_PASSWORD`, `JWT_SECRET`
   (32+ символа), `AMI_PASSWORD`, `EXTENSION_PASSWORD`, `FREEPBX_IP` и остальными
   ключами из `02-secret.example.yaml`. В продакшене лучше использовать
   интеграцию с менеджером секретов, а не простой закоммиченный
   `Secret` — см. комментарий в этом файле.
5. **Закрепить под Asterisk конкретный узел** (`nodeSelector` или
   отдельный нод-пул), если в вашем кластере больше одного узла — его
   `hostNetwork: true` занимает `5060/udp` и `10000-10100/udp` напрямую на
   том узле, куда он попадёт, и именно этот IP/правило файрвола нужно
   вашему SIP-провайдеру, а не IP кластерного Service.

## Известные пробелы относительно docker-compose.yml

- **Нет резервного копирования.** ROADMAP.md §3.7 всё ещё не реализован;
  у `StatefulSet` Postgres есть PVC, но нет расписания `pg_dump`/WAL-archiving —
  не считайте сам по себе PVC стратегией резервного копирования.
- **Нет HorizontalPodAutoscaler.** `backend` и `nginx` выставлены в `replicas: 2`
  как статичная отправная точка (нагрузочное тестирование из ROADMAP §3.3
  ещё не сделано, поэтому нет данных по CPS/конкурентности, чтобы подобрать
  пороги HPA, и угадывать их не имело смысла). См. также ROADMAP §3.8:
  запуск `backend` с `replicas: 2` означает, что `retry_queue`/
  `transcription_queue`/`health_monitor` выполняются избыточно, так как они не
leader-gated. Не некорректно, просто расточительно — снизьте до
  `replicas: 1`, пока это не исправлено, либо исправьте сначала.
- **Нет NetworkPolicy / PodDisruptionBudget / квот ресурсов** на уровне
  неймспейса — оставлено за рамками, чтобы это оставалось выверенной стартовой
  точкой, а не полноценным набором security/ops-политик с нуля — это отдельная
  задача.
- **Ingress вместо LoadBalancer**: `40-nginx.yaml` использует Service типа
  `LoadBalancer` (ближайший аналог публикации портов хоста в docker-compose.yml).
  Если в вашем кластере уже есть ingress-контроллер, обычно лучше подходит
  ресурс `Ingress` + `ClusterIP` Service — замените им вместо добавления
  второго публичного балансировщика.
