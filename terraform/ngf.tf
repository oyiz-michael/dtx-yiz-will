# Install Gateway API CRDs (standard channel)
resource "terraform_data" "gateway_api_crds" {
  triggers_replace = ["v2.4.2"]

  provisioner "local-exec" {
    command = "aws eks update-kubeconfig --region us-east-1 --name ${var.name} && kubectl kustomize 'https://github.com/nginx/nginx-gateway-fabric/config/crd/gateway-api/standard?ref=v2.4.2' | kubectl apply --validate=false -f -"
  }

  depends_on = [aws_eks_node_group.node_group]
}

# Install NGINX Gateway Fabric via Helm
resource "helm_release" "ngf" {
  name             = "ngf"
  repository       = "oci://ghcr.io/nginx/charts"
  chart            = "nginx-gateway-fabric"
  namespace        = "nginx-gateway"
  create_namespace = true
  version          = "2.4.2"

  cleanup_on_fail = true
  force_update = true
  recreate_pods = true


  set = [
    {
      name  = "cluster.enabled"
      value = "true"
    },
    {
      name  = "metrics.enabled"
      value = "true"
    },
    {
      name  = "nginx.service.type"
      value = "LoadBalancer"
    }
  ]

  values = [
    yamlencode({
      nginx = {
        service = {
          type = "LoadBalancer"
          nodePorts = [
            { port = 31437, listenerPort = 80 },
            { port = 30478, listenerPort = 8443 }
          ]
        }
      }
    })
  ]

  depends_on = [terraform_data.gateway_api_crds]
}
