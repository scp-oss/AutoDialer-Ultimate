# Kubernetes manifests (ROADMAP.md §3.5)

Starting point for deploying AutoDialer Ultimate to Kubernetes, mirroring
`docker-compose.yml` component-for-component. **Not applied against a real
cluster in this session** — same constraint as the rest of the project (see
ROADMAP.md §1.4: the sandbox this was built in has no working Docker
daemon, let alone a Kubernetes cluster). Validated only for YAML syntax
(`python3 -c "import yaml; yaml.safe_load_all(...)"` on every file) and for
matching the ports/env vars/volumes actually declared in
`docker-compose.yml`, `Dockerfile`, and `.env.example`. Treat this as a
reviewed draft, not a proven deployment — run it end-to-end against a real
cluster before relying on it in production.

## Apply order

Files are numbered for `kubectl apply -f k8s/` to apply cleanly in one pass
(namespace → config/secrets → stateful stores → shared storage → app
tiers), but nothing here has a `Job`/hook dependency — order only matters
because `postgres`'s Service must exist before `backend`'s init container
tries `alembic upgrade head` against it, which Kubernetes' own retry/back-off
on `CrashLoopBackOff` handles even if you apply everything simultaneously.

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
cp k8s/02-secret.example.yaml k8s/02-secret.yaml   # fill in real values, gitignored
kubectl apply -f k8s/02-secret.yaml
kubectl create configmap nginx-conf -n autodialer --from-file=default.conf=nginx/autodialer.conf
kubectl apply -f k8s/10-postgres.yaml
kubectl apply -f k8s/11-redis.yaml
kubectl apply -f k8s/12-shared-storage.yaml
kubectl apply -f k8s/20-asterisk.yaml
kubectl apply -f k8s/30-backend.yaml
kubectl apply -f k8s/40-nginx.yaml
```

## What you must do before this works

1. **Build and push three images** — none of `autodialer/backend`,
   `autodialer/asterisk`, `autodialer/nginx` exist in any registry; these
   are placeholder names. Build from `Dockerfile`, `docker/asterisk/Dockerfile`,
   and a new one-line `nginx:alpine` + `COPY frontend/dist` Dockerfile
   respectively (see the comment atop `40-nginx.yaml`), then push to
   whatever registry your cluster can pull from and update the `image:`
   fields.
2. **Bake `frontend/dist` into images at build time.** `docker-compose.yml`
   bind-mounts `./frontend/dist` from the host into both `backend` and
   `nginx` containers — Kubernetes has no host filesystem to bind-mount
   from. Add `COPY frontend/dist /srv/frontend` to `Dockerfile` (backend
   serves it via `STATIC_DIR`) and build the nginx image as described
   above. Skipping this means `STATIC_DIR` and nginx's document root are
   empty in the cluster.
3. **Pick an RWX-capable StorageClass** for `12-shared-storage.yaml`
   (`tts-audio`, `call-recordings`) — both PVCs are mounted by asterisk,
   backend, *and* nginx simultaneously, which needs `ReadWriteMany`. Most
   default StorageClasses (`gp2`/`gp3`, `standard`, `local-path`) are
   `ReadWriteOnce` only and will leave these PVCs stuck `Pending`. Use an
   NFS provisioner, EFS (`efs-sc` on EKS), Azure Files (`azurefile` on
   AKS), or equivalent, and set `storageClassName` in that file.
4. **Fill in `02-secret.yaml`** with real `DB_PASSWORD`, `JWT_SECRET`
   (32+ chars), `AMI_PASSWORD`, `EXTENSION_PASSWORD`, `FREEPBX_IP`, and the
   rest of `02-secret.example.yaml`'s keys. In production, prefer a secrets
   manager integration over a plain committed `Secret` — see the comment
   in that file.
5. **Pin the Asterisk pod to a specific node** (`nodeSelector` or a
   dedicated node pool) if your cluster has more than one node — its
   `hostNetwork: true` binds `5060/udp` and `10000-10100/udp` directly on
   whichever node it lands on, and that's the IP/firewall rule your SIP
   trunk provider needs to reach, not a cluster-wide Service IP.

## Known gaps vs. docker-compose.yml

- **No backups.** ROADMAP.md §3.7 is still unimplemented; the Postgres
  `StatefulSet` here has a PVC but no scheduled `pg_dump`/WAL-archiving —
  do not treat the PVC alone as a backup strategy.
- **No HorizontalPodAutoscaler.** `backend` and `nginx` are both set to
  `replicas: 2` as a static starting point (ROADMAP §3.3's load-testing
  work isn't done yet, so there's no CPS/concurrency data to size an HPA
  against). `replicas: 2` on `backend` is safe with respect to its
  periodic workers — a prior draft of this README flagged
  `retry_queue`/`transcription_queue`/`health_monitor` as unsafe to run
  redundantly across replicas; ROADMAP §3.8 was audited and that turned
  out to be wrong (they're either `SKIP LOCKED`-safe, `blpop()`-safe, or
  purely per-replica local state). Only `cleanup_audio`/`log_cleanup`/
  `asterisk_reconciliation` need single-leader execution, and they already
  have it via leader election.
- **No NetworkPolicy / PodDisruptionBudget / resource quotas** at the
  namespace level — left out to keep this a reviewed starting point rather
  than a from-scratch security/ops policy set, which is its own separate
  piece of work.
- **Ingress vs. LoadBalancer**: `40-nginx.yaml` uses a `LoadBalancer`
  Service (closest 1:1 match to `docker-compose.yml`'s host port
  publishing). If your cluster already runs an ingress controller, an
  `Ingress` resource + `ClusterIP` Service is usually the better fit —
  swap it in instead of adding a second public load balancer.
