resource "aws_ecr_repository" "foo" {
  name                 = var.name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "dtx_app" {
  name                 = "dtx-app"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "dtx_app_broken" {
  name                 = "dtx-app-broken"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

output "dtx_app_ecr_url" {
  value = aws_ecr_repository.dtx_app.repository_url
}

output "dtx_app_broken_ecr_url" {
  value = aws_ecr_repository.dtx_app_broken.repository_url
}

resource "aws_ecr_repository" "ai_monitor" {
  name                 = "ai-monitor"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

output "ai_monitor_ecr_url" {
  value = aws_ecr_repository.ai_monitor.repository_url
}

resource "aws_ecr_repository" "ai_observability_agent" {
  name                 = "ai-observability-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

output "ai_observability_agent_ecr_url" {
  value = aws_ecr_repository.ai_observability_agent.repository_url
}