# AI Observability Agent

An autonomous monitoring agent that collects signals from Prometheus, Loki, and
Tempo, analyses them via the **Anthropic API** (Claude), and dispatches findings
to Grafana annotations and Slack — every 5 minutes as a Kubernetes CronJob on
EKS cluster `cityaura` (us-east-1).

---

## Architecture

```
CronJob (every 5 min)
       │
       ▼
   src/main.py  ──asyncio.gather──►  prometheus.collect()
                                     loki.collect()
                                     tempo.collect()
                                          │
                                          ▼
                                  CollectedSignals
                                          │
                                          ▼
                                 llm_analyzer.analyse()
                                  (Claude via Anthropic API)
                                          │
                                          ├──► sns.send()    (SMS — optional)
                                          ├──► email.send()  (SES — optional)
                                          │
                                          ▼
                                   AnalysisResult
                                          │
                         ┌────────────────┴──────────────────┐
                         ▼                                    ▼
                   slack.send()                grafana.post_annotation()
```

## Project Structure

```
ai-observability-agent/
├── src/
│   ├── main.py               # CLI entry point + async pipeline orchestrator
│   ├── config.py             # pydantic-settings (env vars + .env file)
│   ├── collectors/
│   │   ├── prometheus.py     # PromQL instant queries via httpx
│   │   ├── loki.py           # LogQL stream + metric queries via httpx
│   │   └── tempo.py          # TraceQL search via httpx
│   ├── analyzer/
│   │   └── llm_analyzer.py   # Prompt builder + Anthropic SDK + JSON parser
│   ├── outputs/
│   │   ├── slack.py          # Block Kit webhook post (or stdout dry-run)
│   │   ├── grafana.py        # POST /api/annotations
│   │   ├── sns.py            # SMS via AWS SNS (optional)
│   │   └── email.py          # Email via AWS SES (optional)
│   └── models/
│       └── signals.py        # Pydantic v2 models for all data
├── k8s/
│   ├── cronjob.yaml          # CronJob — every 5 min, backoffLimit=2
│   ├── configmap.yaml        # Non-sensitive config
│   ├── secret.yaml           # Template for secrets (API key, Grafana, Slack)
│   └── serviceaccount.yaml   # Kubernetes service account
├── terraform/
│   └── bedrock-irsa.tf       # IAM role + policy (legacy — not used for LLM auth)
├── Dockerfile                # Multi-stage, non-root, python:3.12-slim
├── requirements.txt
├── .env.example
└── README.md
```

---

## Prerequisites

- AWS EKS cluster `cityaura` (us-east-1) with monitoring namespace
- Monitoring stack deployed: kube-prometheus, Loki, Tempo, Fluent Bit
- ECR repository: `ai-observability-agent`
- **Anthropic API key** — the agent calls Claude directly via `anthropic` SDK

---

## Configuration

All configuration is via environment variables. Non-sensitive values come from
the ConfigMap; secrets come from the Kubernetes Secret.

| Variable | Default (in-cluster) | Description |
|---|---|---|
| `PROMETHEUS_URL` | `http://kube-prometheus-...monitoring.svc:9090` | Prometheus endpoint |
| `LOKI_URL` | `http://loki.monitoring.svc:3100` | Loki endpoint |
| `TEMPO_URL` | `http://tempo.monitoring.svc:3200` | Tempo endpoint |
| `GRAFANA_URL` | `http://kube-prometheus-grafana.monitoring.svc` | Grafana endpoint |
| `AWS_REGION` | `us-east-1` | AWS region (used by SNS/SES outputs) |
| `ANTHROPIC_API_KEY` | *(from secret)* | Anthropic API key |
| `ANTHROPIC_MODEL_ID` | `claude-haiku-4-5-20251001` | Claude model ID |
| `LLM_MAX_TOKENS` | `1024` | Max response tokens |
| `GRAFANA_USER` | `admin` | Grafana username |
| `GRAFANA_PASSWORD` | *(from secret)* | Grafana password for annotations |
| `GRAFANA_API_KEY` | *(optional)* | Grafana API key (preferred over password) |
| `SLACK_WEBHOOK_URL` | *(optional)* | Slack incoming webhook URL |
| `SNS_PHONE_NUMBER` | *(optional)* | E.164 phone number for SMS alerts, e.g. `+15551234567` |
| `QUERY_LOOKBACK_MINUTES` | `5` | Lookback window for all queries |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DRY_RUN` | `false` | Print output only; skip all external posts |
| `HTTP_TIMEOUT` | `10` | Per-request HTTP timeout (seconds) |

---

## Build & Deploy

### 1. Build and push the image

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REGION=us-east-1
export IMAGE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/ai-observability-agent:v2"

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin \
    "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

docker build -t "${IMAGE}" .
docker push "${IMAGE}"
```

### 2. Apply the ServiceAccount

```bash
kubectl apply -f k8s/serviceaccount.yaml
```

### 3. Create the Kubernetes secret

```bash
GRAFANA_PWD=$(aws secretsmanager get-secret-value \
  --secret-id eks/cityaura/grafana-admin \
  --query SecretString --output text | jq -r .password)

kubectl create secret generic ai-observability-agent-secrets \
  --namespace monitoring \
  --from-literal=ANTHROPIC_API_KEY=<your-anthropic-api-key> \
  --from-literal=GRAFANA_PASSWORD="${GRAFANA_PWD}" \
  --from-literal=SLACK_WEBHOOK_URL="" \
  --from-literal=GRAFANA_API_KEY="" \
  --from-literal=SNS_PHONE_NUMBER="" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 4. Deploy the ConfigMap and CronJob

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/cronjob.yaml
```

### 5. Verify

```bash
# Check the CronJob is scheduled
kubectl get cronjob -n monitoring ai-observability-agent

# Trigger a manual run immediately
kubectl create job ai-agent-manual \
  --from=cronjob/ai-observability-agent -n monitoring

# Watch the pod logs
kubectl logs -n monitoring -l job-name=ai-agent-manual -f

# Watch scheduled runs
kubectl get jobs -n monitoring -w
```

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and edit config
cp .env.example .env
# Set ANTHROPIC_API_KEY and point URLs at port-forwarded services

# Port-forward the monitoring stack
kubectl port-forward -n monitoring svc/kube-prometheus-kube-prome-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/loki 3100:3100 &
kubectl port-forward -n monitoring svc/tempo 3200:3200 &
kubectl port-forward -n monitoring svc/kube-prometheus-grafana 3000:80 &

# Dry-run — prints formatted output, no external calls
python -m src.main --dry-run

# Normal run
python -m src.main
```

---

## Outputs

### Grafana annotation

A vertical line appears on all dashboards tagged `["ai-agent", "<severity>", "anomaly"]`
with the analysis summary as tooltip text.

### Slack Block Kit message (if `SLACK_WEBHOOK_URL` is set)

```
🔴 CRITICAL — AI Observability Report
Summary: dtx-app-broken memory usage reached 420MB (3× baseline)...

🔎 Anomalies:
  🔴 [CRITICAL] Memory leak worsening: 420MB vs 150MB baseline
     Evidence: container_memory_usage_bytes{pod="dtx-app-broken-xxx"} = 440200192
  🟡 [WARNING]  Error rate elevated: 48% vs 35% baseline

🔗 Correlations:
  • Memory growth correlates with OOMKill pod restarts
    Root cause: Memory leak in dtx-app-broken /data endpoint

✅ Recommendations:
  1. 🚨 [IMMEDIATE] kubectl rollout restart deployment/dtx-app-broken
  2. ⚠️  [SHORT_TERM] Set memory limit of 200Mi to trigger OOMKill sooner

dtx-app (healthy): Operating within expected parameters (<1% error rate, ~82MB memory)

📊 Grafana | 🕐 2026-04-27 09:00 UTC | AI Observability Agent
```

### SMS (if `SNS_PHONE_NUMBER` is set)

A concise single-message summary is sent via AWS SNS to the configured E.164 number.

---

## Severity semantics

| Severity | Meaning | CronJob exit code |
|---|---|---|
| `CRITICAL` | One or more signals significantly exceed known-bad baselines | `1` (registers failure) |
| `WARNING` | Signals trending bad but within expected ranges | `0` |
| `INFO` | All signals nominal | `0` |

The CronJob only registers a failure when the agent exits `1` — i.e., only on
`CRITICAL` findings. This can trigger Kubernetes backoff and alerting.
