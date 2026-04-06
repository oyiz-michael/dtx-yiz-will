https://kind.sigs.k8s.io/docs/user/quick-start/

# create kind cluster
kind create cluster --config kind-config.yaml

# Build app 
docker build -t dtx-app:v1 .     

# Load image into kind cluster
kind load docker-image dtx-app:v1 --name kind

# Deploy
kubectl apply -f deployment.yml

kubectl apply -f monitoring.yml

# Watch pods come up
kubectl get pods -w


kubectl port-forward service/dtx-app-service 8084:80
kubectl port-forward service/dtx-app-broken-service 8085:80


helm repo add prometheus-community https://prometheus-community.github.io/helm-charts && helm repo update


helm install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set grafana.adminPassword=admin


kubectl -n monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090:9090

kubectl -n monitoring port-forward svc/kube-prometheus-grafana 3000:80



kubectl -n monitoring port-forward svc/loki 3100:3100


helm repo add grafana https://grafana.github.io/helm-charts && helm repo update

helm repo add grafana https://grafana.github.io/helm-charts && helm repo update


helm install tempo grafana/tempo \
  --namespace monitoring

helm install loki grafana/loki-stack \
>   --namespace monitoring \
>   --set loki.persistence.enabled=false \
>   --set promtail.enabled=true \
>   --set grafana.enabled=false


kubectl -n monitoring get pods -l "app in (loki,promtail,tempo)" -o wide

helm upgrade kube-prometheus prometheus-community/kube-prometheus-stack \\n  --namespace monitoring \\n  --set grafana.adminPassword=admin \\n  --set grafana.additionalDataSources[0].name=Loki \\n  --set grafana.additionalDataSources[0].type=loki \\n  --set grafana.additionalDataSources[0].url=http://loki:3100 \\n  --set grafana.additionalDataSources[0].access=proxy \\n  --set grafana.additionalDataSources[1].name=Tempo \\n  --set grafana.additionalDataSources[1].type=tempo \\n  --set grafana.additionalDataSources[1].url=http://tempo:3100 \\n  --set grafana.additionalDataSources[1].access=proxy


In Grafana:
Explore > Loki — query logs with {app="dtx-app"} or {app="dtx-app-broken"} to see logs from each app
Explore > Prometheus — query metrics like flask_http_request_total to see request counts, error rates, etc.
Explore > Tempo — view traces (apps would need OpenTelemetry SDK to send traces; Loki + Prometheus are working out of the box)



## Monitoring Component, Purpose, What it does:
Prometheus	Metrics	Scrapes /metrics from both dtx-app and dtx-app-broken pods
Loki + Promtail	Logs	Promtail collects stdout/stderr logs from all pods and sends to Loki
Tempo	Traces	Ready to receive distributed traces
Grafana	Dashboards	All three are configured as data sources




add loki data source to grafana as annotations:
http://loki.monitoring.svc.cluster.local:3100


Loki's root path returns 404 — that's normal. It doesn't have a web UI. Try these endpoints instead:

http://localhost:3100/ready — should return ready
http://localhost:3100/loki/api/v1/labels — should return log labels
http://localhost:3100/loki/api/v1/query?query={app="dtx-app"} — actual log query


helm upgrade loki grafana/loki-stack \
  --namespace monitoring \
  --set loki.persistence.enabled=false \
  --set promtail.enabled=true \
  --set grafana.enabled=false \
  --set loki.image.tag=3.1.0