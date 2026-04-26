# =============================================================================
# Monitoring namespace
# =============================================================================
resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }

  depends_on = [aws_eks_node_group.node_group]
}

# =============================================================================
# Grafana admin password → random + stored in Secrets Manager
# =============================================================================
resource "random_password" "grafana" {
  length           = 24
  special          = true
  override_special = "!@#$%^&*"
}

resource "aws_secretsmanager_secret" "grafana" {
  name                    = "eks/${var.name}/grafana-admin"
  description             = "Grafana admin password for EKS cluster ${var.name}"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "grafana" {
  secret_id = aws_secretsmanager_secret.grafana.id
  secret_string = jsonencode({
    username = "admin"
    password = random_password.grafana.result
  })
}

# =============================================================================
# kube-prometheus-stack (Prometheus + Grafana)
# =============================================================================
resource "helm_release" "kube_prometheus" {
  name             = "kube-prometheus"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  namespace        = "monitoring"
  create_namespace = false
  version          = "72.6.2"

  cleanup_on_fail = true

  set = [
    {
      name  = "grafana.adminPassword"
      value = random_password.grafana.result
    },
    # Auto-discover Loki and Tempo datasources via sidecar
    {
      name  = "grafana.sidecar.datasources.enabled"
      value = "true"
    },
    {
      name  = "grafana.sidecar.datasources.searchNamespace"
      value = "monitoring"
    },
  ]

  depends_on = [kubernetes_namespace.monitoring]
}

# =============================================================================
# AI Monitor Agent - Anthropic API key stored in Secrets Manager
# =============================================================================
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "eks/${var.name}/anthropic-api-key"
  description             = "Anthropic API key for AI monitor agent"
  recovery_window_in_days = 7
}

# Placeholder - you must set the actual key after terraform apply:
#   aws secretsmanager put-secret-value --secret-id eks/cityaura/anthropic-api-key --secret-string '{"api_key":"sk-ant-..."}'
resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = jsonencode({
    api_key = "REPLACE_ME"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
