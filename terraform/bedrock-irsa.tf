# IAM role + policy for the AI observability agent (IRSA — Bedrock access).
#
# This file should live alongside the other EKS Terraform files in
# eks-ngf-gateway/ and be applied with `terraform apply` from that directory.
# The two variables (oidc_provider_arn, oidc_provider) must be sourced from
# your EKS cluster module outputs or populated in terraform.tfvars.

# ---------------------------------------------------------------------------
# IAM policy — allow invoking Claude on Bedrock
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "ai_agent_bedrock" {
  name        = "ai-observability-agent-bedrock"
  description = "Allow AI observability agent to invoke Claude on Amazon Bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:Converse",
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
          "arn:aws:bedrock:us-east-1:427613144745:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
          "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",
          "arn:aws:bedrock:us-east-1:427613144745:inference-profile/us.amazon.nova-pro-v1:0",
          "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
          "arn:aws:bedrock:us-east-1:427613144745:inference-profile/us.amazon.nova-lite-v1:0",
          "arn:aws:bedrock:*::foundation-model/meta.llama3-3-70b-instruct-v1:0",
          "arn:aws:bedrock:us-east-1:427613144745:inference-profile/us.meta.llama3-3-70b-instruct-v1:0",
          "arn:aws:bedrock:*::foundation-model/meta.llama3-1-70b-instruct-v1:0",
          "arn:aws:bedrock:us-east-1:427613144745:inference-profile/us.meta.llama3-1-70b-instruct-v1:0"
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# IAM role — trusted by the K8s service account via OIDC
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ai_agent" {
  name = "ai-observability-agent-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = var.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${var.oidc_provider}:sub" = "system:serviceaccount:monitoring:ai-observability-agent"
            "${var.oidc_provider}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ai_agent_bedrock" {
  role       = aws_iam_role.ai_agent.name
  policy_arn = aws_iam_policy.ai_agent_bedrock.arn
}

# ---------------------------------------------------------------------------
# Variables — wire these up to your EKS cluster module outputs
# ---------------------------------------------------------------------------
variable "oidc_provider_arn" {
  description = "ARN of the EKS cluster's OIDC provider. Typically output by the EKS module as `oidc_provider_arn`."
  type        = string
  # Example: "arn:aws:iam::427613144745:oidc-provider/oidc.eks.eu-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE"
}

variable "oidc_provider" {
  description = "OIDC provider URL without protocol prefix. Typically output by the EKS module as `oidc_provider`."
  type        = string
  # Example: "oidc.eks.eu-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE"
}
