resource "aws_eks_node_group" "node_group" {
  cluster_name    = aws_eks_cluster.cluster.name
  node_group_name = "eks-node-group-${var.name}"
  node_role_arn   = aws_iam_role.node_group_role.arn
  subnet_ids      = ["subnet-0c5b02e7c6a19f5cb", "subnet-0ed49f7a9d1a88e06"]
  region          = var.region

  capacity_type  = "SPOT"
  instance_types = ["t3.medium"]
  disk_size      = 20

  scaling_config {
    desired_size = 2
    max_size     = 3
    min_size     = 1
  }

  update_config {
    max_unavailable = 1
  }

  # Ensure that IAM Role permissions are created before and deleted after EKS Node Group handling.
  # Otherwise, EKS will not be able to properly delete EC2 Instances and Elastic Network Interfaces.
  depends_on = [
    aws_iam_role_policy_attachment.node_group_AmazonEKSWorkerNodePolicy,
    aws_iam_role_policy_attachment.node_group_AmazonEKS_CNI_Policy,
    aws_iam_role_policy_attachment.node_group_AmazonEC2ContainerRegistryReadOnly,
  ]
}

resource "aws_iam_role" "node_group_role" {
  name = "eks-node-group-${var.name}"

  assume_role_policy = jsonencode({
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
    Version = "2012-10-17"
  })
}

resource "aws_iam_role_policy_attachment" "node_group_AmazonEKSWorkerNodePolicy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.node_group_role.name
}

resource "aws_iam_role_policy_attachment" "node_group_AmazonEKS_CNI_Policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.node_group_role.name
}

resource "aws_iam_role_policy_attachment" "node_group_AmazonEC2ContainerRegistryReadOnly" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.node_group_role.name
}

data "aws_availability_zones" "available" {
  state = "available"
}

# ---------------------------------------------------------------
# IRSA Example: Give a pod S3 read access without any credentials
# ---------------------------------------------------------------

# 1. IAM role that trusts the OIDC provider
resource "aws_iam_role" "s3_reader_role" {
  name = "eks-s3-reader-${var.name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.cluster.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${aws_iam_openid_connect_provider.cluster.url}:sub" = "system:serviceaccount:dev:s3-reader"
        }
      }
    }]
  })
}

# 2. Attach S3 read policy to the role
resource "aws_iam_role_policy_attachment" "s3_reader_policy" {
  role       = aws_iam_role.s3_reader_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}