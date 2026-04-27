EKS cluster with NGINX Gateway Fabric, DTX observability apps, and full monitoring stack (Prometheus, Grafana, Loki, Tempo).

## Architecture

```
curl / browser
    │
    ▼
AWS ELB (LoadBalancer)
    │
    ▼
NGF Gateway (nginx-gateway namespace)
    │
    ├── Host: cafe.example.com  →  coffee / tea pods (dev namespace)
    └── Host: dtx.example.com   →  dtx-app / dtx-app-broken pods (default namespace)
```

Monitoring stack in `monitoring` namespace:
- **Prometheus** — scrapes `/metrics` from dtx apps via ServiceMonitors
- **Grafana** — dashboards for metrics, logs, and traces
- **Loki + Fluent Bit** — log aggregation from all pods
- **Tempo** — distributed tracing via OpenTelemetry

---

## 1. Prerequisites

```bash
aws --version
terraform --version
docker --version
kubectl version --client
helm version
```

---

## 2. Deploy EKS Cluster + Monitoring (Terraform)

```bash
cd eks-ngf-gateway

terraform init
terraform plan
terraform apply
```

This creates:
- EKS cluster "demo-dtx" with 2× t3.medium SPOT nodes
- ECR repos: `dtx-app`, `dtx-app-broken`
- NGF gateway via Helm
- kube-prometheus-stack (Prometheus + Grafana) via Helm
- monitoring namespace

---

## 3. Connect to the Cluster

```bash
aws eks update-kubeconfig --region us-east-1 --name demo-dtx
kubectl get nodes
```

---

## 4. Build and Push DTX App Images to ECR

Get your AWS account ID and ECR login:

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REGION=us-east-1

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com
```

Build and push both app images (from the dtx-yiz-nd-will directory):

```bash
# Build dtx-app (working app)
docker build --platform linux/amd64 -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app:v1 ../dtx-yiz-nd-will/app
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app:v1

# Build dtx-app-broken
docker build --platform linux/amd64 -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app-broken:v1 ../dtx-yiz-nd-will/app-broken
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app-broken:v1
```

---

## 5. Update Image References and Deploy Apps

Replace `<ACCOUNT_ID>` in `k8/dtx-deployment.yml` with your actual account ID:

```bash
sed -i '' "s/427613144745/$ACCOUNT_ID/g" k8/dtx-deployment.yml
```

Deploy the cafe apps (existing) and DTX apps:

```bash
# Existing cafe apps
kubectl create namespace dev --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8/serviceaccount.yml
kubectl apply -f k8/cafe.yml
kubectl apply -f k8/gateway.yml
kubectl apply -f k8/ReferenceGrant.yml
kubectl apply -f k8/routes.yml

# DTX apps
kubectl apply -f k8/dtx-deployment.yml
kubectl apply -f k8/dtx-routes.yml
kubectl apply -f k8/dtx-monitoring.yml

# Expose Grafana externally through NGF
kubectl apply -f k8/grafana-route.yml

kubectl get pods -w
```

---

## 6. Deploy Loki, Fluent Bit, and Tempo

```bash
kubectl apply -f k8/dtx-loki-stack.yml

kubectl -n monitoring get pods -l app=loki
kubectl -n monitoring get pods -l app=fluent-bit
kubectl -n monitoring get pods -l app=tempo
```

---

## 7. Access the Apps

Get the NGF LoadBalancer hostname:

```bash
kubectl get svc -n nginx-gateway
```

### Cafe Apps (existing)

```bash
curl -H "Host: cafe.example.com" http://<ELB-HOSTNAME>/coffee
curl -H "Host: cafe.example.com" http://<ELB-HOSTNAME>/tea
```

### DTX Apps

```bash
# Working app
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /data
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /health
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /journey?steps=5
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /ui

# Broken app
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /broken
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /broken/data
curl -H "Host: dtx.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /broken/chaos?steps=6&failure_rate=0.5
```
---
dig +short ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com | head -1


```bash
sudo sh -c 'echo "18.208.123.72 grafana.example.com dtx.example.com" >> /etc/hosts'
```
---

## 8. Access Grafana & Monitoring

### Grafana (external via ELB)

Grafana is exposed through the NGF gateway at `grafana.example.com`:

```bash
# Open in browser or curl
curl -H "Host: grafana.example.com" http://ae357ff4a85f24c229107a24709c0598-201282752.us-east-1.elb.amazonaws.com /
```

Login: `admin` / password from Secrets Manager:

```bash
aws secretsmanager get-secret-value --secret-id eks/demo-dtx/grafana-admin --query SecretString --output text | jq -r .password
```

### Port-forward (optional alternatives)

```bash
# Prometheus
kubectl -n monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090:9090

# Loki (debug)
kubectl -n monitoring port-forward svc/loki 3100:3100

# Tempo (debug)
kubectl -n monitoring port-forward svc/tempo 3200:3200
```

---

## 9. Verify the Stack

### Prometheus Metrics

Open http://localhost:9090 and query:
- `flask_http_request_total`

### Loki Logs (in Grafana → Explore → Loki)

- `{kubernetes_labels_app="dtx-app"}`
- `{kubernetes_labels_app="dtx-app-broken"}`

### Tempo Traces (in Grafana → Explore → Tempo)

Filter by service name: `dtx-app` or `dtx-app-broken`

Generate traffic to create traces:

```bash
ELB=$(kubectl get svc -n nginx-gateway -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}')
for i in $(seq 1 20); do
  curl -s -H "Host: dtx.example.com" http://$ELB/ > /dev/null
  curl -s -H "Host: dtx.example.com" http://$ELB/data > /dev/null
  curl -s -H "Host: dtx.example.com" http://$ELB/broken > /dev/null
done
```

---

## 10. Rebuild Workflow After App Changes

```bash
docker build -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app:v1 ../dtx-yiz-nd-will/app
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app:v1

docker build -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app-broken:v1 ../dtx-yiz-nd-will/app-broken
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/dtx-app-broken:v1

kubectl rollout restart deployment dtx-app dtx-app-broken
```

---

## 11. AI Monitor Agent (Claude-powered anomaly detection)

The AI monitor agent runs as a CronJob every 5 minutes. It queries Prometheus, Loki, and Tempo, sends all signals to Claude for analysis, and posts results as Grafana annotations.

### Build and push the agent image

```bash
docker build --platform linux/amd64 -t $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/ai-monitor:v1 ai-monitor/
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/ai-monitor:v1
```

### Create the secrets

Get the Grafana password and set your Anthropic API key:

```bash
GRAFANA_PW=$(aws secretsmanager get-secret-value --secret-id eks/demo-dtx/grafana-admin --query SecretString --output text | jq -r .password)

kubectl create secret generic ai-monitor-secrets -n monitoring \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-your-key-here \
  --from-literal=GRAFANA_PASSWORD=$GRAFANA_PW
```

### Deploy the CronJob

```bash
sed -i '' "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" k8/ai-monitor.yml
kubectl apply -f k8/ai-monitor.yml
```

### Test it manually (trigger a one-off run)

```bash
kubectl create job ai-monitor-test --from=cronjob/ai-monitor -n monitoring
kubectl -n monitoring logs -f job/ai-monitor-test
```

### View results in Grafana

Open Grafana → any dashboard → annotations will appear with tags `ai-monitor` + `healthy`/`degraded`/`critical`.

Or query annotations via API:

```bash
curl -u admin:$GRAFANA_PW "http://grafana.example.com/api/annotations?tags=ai-monitor&limit=5"
```

---

## Network Traffic Flow

```
Your browser / curl
        │
        │  HTTP request: dtx.example.com/
        │  Host header: dtx.example.com
        ▼
DNS resolves → AWS ELB hostname
        │
        ▼
AWS Application Load Balancer (ELB)
  - Forwards to EKS nodes
        │
        ▼
NGF NGINX Pod (nginx-gateway namespace)
  - Matches Host: dtx.example.com
  - Routes /         → dtx-app-service
  - Routes /broken   → dtx-app-broken-service
        │
        ▼
DTX App Pod (default namespace)
  - Flask handles request
  - Exports traces → Tempo (OTLP)
  - Exposes /metrics → Prometheus scrapes
  - stdout/stderr → Fluent Bit → Loki
```
