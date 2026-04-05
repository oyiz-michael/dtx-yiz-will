https://kind.sigs.k8s.io/docs/user/quick-start/

# Build app 
docker build -t dtx-app:v2 .     

# Load image into kind cluster
kind load docker-image dtx-app:v1 --name kind

# Deploy
kubectl apply -f deployment.yml

# Watch pods come up
kubectl get pods -w

kubectl port-forward service/dtx-app-broken-service 8085:80