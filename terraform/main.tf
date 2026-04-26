resource "aws_eks_cluster" "cluster" {
  name     = var.name
  role_arn = aws_iam_role.cluster_role.arn
  version  = "1.35"

  # access_config {
  #   authentication_mode = "API"
  # }

  vpc_config {
    subnet_ids              = ["subnet-0c5b02e7c6a19f5cb", "subnet-0ed49f7a9d1a88e06", ]
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = ["0.0.0.0/0"]
  }

  # enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  encryption_config {
    provider {
      key_arn = aws_kms_key.eks.arn
    }
    resources = ["secrets"]
  }

  # Ensure that IAM Role permissions are created before and deleted
  # after EKS Cluster handling. Otherwise, EKS will not be able to
  # properly delete EKS managed EC2 infrastructure such as Security Groups.
  depends_on = [
    aws_iam_role_policy_attachment.cluster_AmazonEKSClusterPolicy,
    aws_cloudwatch_log_group.cluster
  ]
}


resource "aws_eks_addon" "vpc_cni" {
  cluster_name = aws_eks_cluster.cluster.name
  addon_name   = "vpc-cni"
  # addon_version = "v1.15.4-eksbuild.1"
}

# resource "aws_eks_addon" "ebs_csi_driver" {
#   cluster_name = aws_eks_cluster.cluster.name
#   addon_name   = "aws-ebs-csi-driver"
#   # addon_version = "v1.26.1-eksbuild.1"
# }

# resource "aws_eks_addon" "aws-efs-csi-driver" {
#   cluster_name = aws_eks_cluster.example.name
#   addon_name   = "aws-efs-csi-driver"
# }

resource "aws_iam_role" "cluster_role" {
  name = "eks-cluster-${var.name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
        Effect = "Allow"
        Principal = {
          Service = "eks.amazonaws.com"
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_AmazonEKSClusterPolicy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.cluster_role.name
}

resource "aws_kms_key" "eks" {
  description             = "EKS cluster encryption key ${var.name}"
  rotation_period_in_days = 90
  enable_key_rotation     = true
}

resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = 7
}

data "tls_certificate" "cluster" {
  url = aws_eks_cluster.cluster.identity[0].oidc[0].issuer
}

# Set up OIDC provider for pod-level IAM roles (IRSA) to
# let pods authenticate to AWS services without storing credentials:
resource "aws_iam_openid_connect_provider" "cluster" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.cluster.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.cluster.identity[0].oidc[0].issuer
}