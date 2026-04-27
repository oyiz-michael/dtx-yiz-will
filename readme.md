# DTX App Observability Stack

This repository deploys:

- Two Flask apps (`dtx-app` and `dtx-app-broken`)
- Prometheus + Grafana (via `kube-prometheus-stack`)
- Loki + Fluent Bit for logs
- Tempo for traces
- OpenTelemetry tracing from both apps to Tempo
- AI Observability Agent (autonomous analysis via Claude)

## Monitoring Components

| Component | Purpose | What it does |
| --- | --- | --- |
| Prometheus | Metrics | Scrapes `/metrics` from both `dtx-app` and `dtx-app-broken` |
| Loki + Fluent Bit | Logs | Fluent Bit collects container stdout/stderr and ships to Loki |
| Tempo | Traces | Receives OTLP traces from both apps |
| Grafana | Dashboards | Visualizes logs, metrics, and traces |
| AI Observability Agent | Autonomous analysis | Queries Prometheus, Loki, and Tempo every 5 min; analyses signals with Claude; posts findings to Grafana annotations |

## 1. Prerequisites

Install and verify:

```bash
docker --version
kind --version
kubectl version --client
helm version
```

## 2. Create Kind Cluster

```bash
kind create cluster --config kind-config.yaml
kubectl cluster-info --context kind-kind
```

## 3. Build and Load App Images

```bash
docker build -t dtx-app:v1 ./app
docker build -t dtx-app:v2 ./app-broken

kind load docker-image dtx-app:v1 dtx-app:v2 --name kind
```

## 4. Deploy Apps and ServiceMonitors

```bash
kubectl apply -f deployment.yml
kubectl apply -f monitoring.yml

kubectl get pods -w
```

## 5. Install Prometheus and Grafana

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin
```

## 6. Deploy Loki, Fluent Bit, and Tempo

```bash
kubectl apply -f loki-stack.yml

kubectl -n monitoring get pods -l app=loki
kubectl -n monitoring get pods -l app=fluent-bit
kubectl -n monitoring get pods -l app=tempo
```

## 7. Port-Forward Access

Use separate terminals for each command.

Apps:

```bash
kubectl port-forward service/dtx-app-service 8084:80
kubectl port-forward service/dtx-app-broken-service 8085:80
```

Prometheus and Grafana:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090:9090
kubectl -n monitoring port-forward svc/kube-prometheus-grafana 3000:80
```

Optional direct API debugging:

```bash
kubectl -n monitoring port-forward svc/loki 3100:3100
kubectl -n monitoring port-forward svc/tempo 3200:3200
```

## 8. Verify the Stack

### A) App Endpoints

- Working app: http://localhost:8084/
- Broken app: http://localhost:8085/
- Working app metrics: http://localhost:8084/metrics
- Broken app metrics: http://localhost:8085/metrics
- Working app UI playground: http://localhost:8084/ui
- Broken app UI playground: http://localhost:8085/ui

Iterative trace endpoints:

- Working journey endpoint: `http://localhost:8084/journey?steps=6`
- Broken chaos endpoint: `http://localhost:8085/chaos?steps=6&failure_rate=0.5`

Both apps return `trace_id` in JSON and also include `X-Trace-Id` in response headers for quick trace correlation.

### B) Prometheus Metrics

Open http://localhost:9090 and query:

- `flask_http_request_total`

### C) Loki Logs

Open Grafana at http://localhost:3000 (`admin` / `admin`), then go to Explore and select Loki.

Loki root path behavior:

- `http://localhost:3100/` returns `404` by design (no web UI).

Useful Loki endpoints:

- `http://localhost:3100/ready` should return ready.
- `http://localhost:3100/loki/api/v1/labels` returns labels.
- `http://localhost:3100/loki/api/v1/query?query=%7Bkubernetes_labels_app%3D%22dtx-app%22%7D` example query.

Useful LogQL queries in Grafana Explore -> Loki:

- `{kubernetes_labels_app="dtx-app"}`
- `{kubernetes_labels_app="dtx-app-broken"}`
- `{kubernetes_namespace_name="default"}`
- `{job="fluent-bit"}`

Loki dashboard imports in Grafana:

- ID `13639` (popular Loki logs dashboard)
- ID `12019` (Loki and Promtail overview)
- ID `15141` (Loki logs with filtering)

Import path:

- Dashboards -> New -> Import -> enter dashboard ID -> Load -> select Loki datasource -> Import

### D) Tempo Traces

Open Grafana -> Explore -> Tempo.

Filter by service name:

- `dtx-app`
- `dtx-app-broken`

Tempo direct endpoints (debugging):

- `http://localhost:3200/status/services`
- `http://localhost:3200/metrics`

If no traces appear yet, generate traffic from inside cluster:

```bash
kubectl run tracegen --rm -i --restart=Never --image=busybox:1.36 -- sh -lc '
for i in $(seq 1 20); do
  wget -qO- http://dtx-app-service/ >/dev/null || true
  wget -qO- http://dtx-app-service/data >/dev/null || true
  wget -qO- http://dtx-app-broken-service/ >/dev/null || true
  wget -qO- http://dtx-app-broken-service/data >/dev/null || true
done'
```

Then verify Tempo ingestion counters increase:

```bash
kubectl -n monitoring exec tempo-0 -- sh -lc \
  "wget -qO- http://localhost:3200/metrics | grep -E 'tempo_distributor_push_duration_seconds_count|tempo_distributor_traces_per_batch_count'"
```

## 9. Rebuild Workflow After App Changes

```bash
docker build -t dtx-app:v1 ./app
docker build -t dtx-app:v2 ./app-broken

kind load docker-image dtx-app:v1 dtx-app:v2 --name kind

kubectl apply -f deployment.yml
kubectl rollout restart deployment dtx-app dtx-app-broken
kubectl rollout status deployment/dtx-app
kubectl rollout status deployment/dtx-app-broken
```

## 10. Troubleshooting

No logs in Grafana/Loki:

```bash
kubectl -n monitoring get pods -l app=fluent-bit
kubectl -n monitoring logs -l app=fluent-bit --tail=50
```

No traces in Grafana/Tempo:

```bash
kubectl -n monitoring exec tempo-0 -- wget -qO- http://localhost:3200/status/services
kubectl -n monitoring exec tempo-0 -- sh -lc "wget -qO- http://localhost:3200/metrics | grep tempo_distributor_push_duration_seconds_count"
```

Port-forward fails because port is in use:

```bash
lsof -i :3000
lsof -i :9090
lsof -i :3100
lsof -i :3200
```

---

## 11. AI Observability Agent

An autonomous AI agent that runs as a Kubernetes CronJob every 5 minutes on the EKS cluster (`cityaura`, `us-east-1`). It queries Prometheus, Loki, and Tempo, sends the signals to Claude (Anthropic API), and posts findings to Grafana as annotations.

Full documentation: [`ai-observability-agent/README.md`](ai-observability-agent/README.md)

### Architecture

```
CronJob (every 5 min)
       │
       ▼
  Collect signals ──► Prometheus metrics
                      Loki logs
                      Tempo traces
                          │
                          ▼
                  Claude (Anthropic API)
                          │
                          ▼
              ┌───────────┴───────────┐
              ▼                       ▼
        Grafana annotation       Slack (optional)
```

### Deploy the agent (EKS)

**1. Create the Kubernetes secret:**

```bash
kubectl create secret generic ai-observability-agent-secrets \
  --namespace monitoring \
  --from-literal=ANTHROPIC_API_KEY=<your-key> \
  --from-literal=GRAFANA_PASSWORD=$(aws secretsmanager get-secret-value \
    --secret-id eks/cityaura/grafana-admin \
    --query SecretString --output text | jq -r .password) \
  --dry-run=client -o yaml | kubectl apply -f -
```

**2. Apply config and CronJob:**

```bash
kubectl apply -f ai-observability-agent/k8s/configmap.yaml
kubectl apply -f ai-observability-agent/k8s/serviceaccount.yaml
kubectl apply -f ai-observability-agent/k8s/cronjob.yaml
```

**3. Build and push the image:**

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export IMAGE="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/ai-observability-agent:v2"

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com"

docker build -t "${IMAGE}" ai-observability-agent/
docker push "${IMAGE}"
```

### Monitor the agent

```bash
# Watch CronJob runs
kubectl get jobs -n monitoring -w

# Trigger a manual run immediately
kubectl create job ai-agent-manual --from=cronjob/ai-observability-agent -n monitoring

# Check logs
kubectl logs -n monitoring -l job-name=ai-agent-manual
```

### Sample output

```
🟡  AI OBSERVABILITY REPORT  —  WARNING
======================================================================
  Summary: dtx-app-broken is degraded as expected, but dtx-app shows
  elevated error rate at 7.81% (baseline <1%).

  ANOMALIES:
    🟡 [WARNING] dtx-app error rate elevated to 7.81%, above baseline <1%
       Evidence: error_rate=7.81 vs baseline <1%
    🟢 [INFO] dtx-app-broken in CrashLoopBackOff — consistent with memory leak design

  RECOMMENDATIONS:
    1. 🚨 [IMMEDIATE] Investigate dtx-app error rate spike
    2. ⚠️  [SHORT_TERM] Confirm dtx-app-broken degradation is intentional demo state
    3. 🔍 [INVESTIGATION] Enable Loki log collection for error context

{"annotation_id": 70, "severity": "WARNING", "event": "grafana.annotation_posted"}
{"severity": "WARNING", "event": "agent.done"}
```

### Severity semantics

| Severity | Meaning | CronJob exit code |
| --- | --- | --- |
| `CRITICAL` | Signals significantly exceed known-bad baselines | `1` (registers failure) |
| `WARNING` | Signals trending bad but within expected ranges | `0` |
| `INFO` | All signals nominal | `0` |