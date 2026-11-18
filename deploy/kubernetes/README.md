# OpsPilot on Kubernetes

Kustomize manifests for the whole stack in one namespace, `opspilot`:

| Component | Kind | Notes |
| --- | --- | --- |
| storefront, payments | Deployment + Service | Python demo services, one replica each |
| orders | Deployment + Service | Spring Boot; password from the `orders-db` Secret |
| postgres | StatefulSet + Service | 1 GiB volume claim |
| control-plane | Deployment + Service | deploy registry and chaos API |
| loadgen | Deployment | 4 requests per second against the storefront |
| prometheus | Deployment + Service | same scrape jobs as the compose stack |
| loki | Deployment + Service | single binary, filesystem storage, 24 h retention |
| alloy | Deployment + RBAC | ships the services' pod logs to Loki |
| jaeger | Deployment + Service | all-in-one, in-memory storage capped at 5,000 traces |
| agent-api | Deployment + Service + claim | SQLite data on a 1 GiB claim |
| dashboard | Deployment + Service | Next.js, proxies to the agent API |

## How it differs from docker compose

- **Logs come from Loki, not the Docker socket.** Grafana Alloy reads pod logs through the
  Kubernetes API (`pods/log`, namespace-scoped Role), labels each stream with
  `service=<app.kubernetes.io/name>` and pushes it to Loki. The MCP server queries
  `{service="orders"}` through Loki's `query_range` API (`OPSPILOT_LOG_BACKEND=loki`). No pod
  mounts a host path, and only Alloy gets a service account token.
- **Probes cannot erase a fault.** An injected outage makes a service's health endpoint answer
  503. The three services the agent investigates use HTTP only for the startup probe; readiness
  and liveness only check the TCP port. An HTTP probe would pull the pod out of its Service or
  restart it, and a restart clears the in-process fault before the agent sees it.
- **One replica per demo service.** Fault state and the deploy registry live in the process.
- **Hardened pods.** Every container runs as non-root with a read-only root filesystem, no
  capabilities, no privilege escalation, the runtime's default seccomp profile, and a memory
  limit. The limits add up to 2.75 GiB, within the compose stack's budget.
- **Tracing is on.** Compose starts Jaeger only with the `tracing` or `dashboard` profile and
  leaves `OPSPILOT_TRACING_ENABLED` off by default; here Jaeger is always part of the stack, so
  the demo services, the agent API and the MCP server it starts export spans to
  `http://jaeger:4318`. Jaeger keeps traces in memory (at most 5,000, oldest evicted first) and
  loses them on a restart.

## Run it on kind

```bash
# Build the images with the same tags as the compose stack.
docker compose -f demo-system/docker-compose.yml --profile dashboard build

kind create cluster --name opspilot
for image in opspilot-python-services opspilot-orders opspilot-agent-api opspilot-dashboard; do
  kind load docker-image "$image:dev" --name opspilot
done

kubectl create namespace opspilot
kubectl -n opspilot create secret generic orders-db --from-literal=password="$(openssl rand -hex 16)"
# Optional: model and API keys for the agent (without it, the agent runs the rule-based playbook).
kubectl -n opspilot create secret generic opspilot-agent --from-env-file=.env

kubectl apply -k deploy/kubernetes
kubectl -n opspilot rollout status deploy/agent-api
kubectl -n opspilot port-forward svc/dashboard 8100:8080
kubectl -n opspilot port-forward svc/jaeger 8166:16686   # in a second terminal
```

Then open http://localhost:8100 (dashboard) and http://localhost:8166 (traces). Without `OPSPILOT_API_KEYS` in the `opspilot-agent` Secret,
anyone who can reach the dashboard can approve a rollback; keep the Services cluster-internal
(the default here) or set keys before exposing it.

For another cluster, push the four images to a registry and set them in the `images` list of
`kustomization.yaml`.

## Validate

```bash
make k8s-check                                # Kustomize render + kubeconform (also in CI)
.venv/bin/pytest tests/deploy                 # consistency with compose and the agent settings
```

Status: rendered and validated statically; not yet applied to a running cluster.
