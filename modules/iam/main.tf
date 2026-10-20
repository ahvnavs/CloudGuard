data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name = "${var.project_name}-${var.environment}"
  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  })
  main_subject = "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}"
  state_arn    = "arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}/${var.state_key}"
}

resource "aws_iam_role" "plan" {
  name                 = "${local.name}-github-plan"
  description          = "CloudGuard read-only Terraform planning and drift checks."
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = var.oidc_provider_arn }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = [local.main_subject, "repo:${var.github_repository}:pull_request"]
        }
      }
    }]
  })
  tags = local.tags
}

# Regional read APIs are enumerated; no infrastructure create/update/delete
# API is granted. Some of these Describe APIs require a wildcard resource.
resource "aws_iam_role_policy" "plan" {
  name = "terraform-plan-and-state-lock"
  role = aws_iam_role.plan.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadDemoInfrastructure"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceAttribute",
          "ec2:DescribeInstanceCreditSpecifications",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeRouteTables",
          "ec2:DescribeSecurityGroupRules",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeTags",
          "ec2:DescribeVolumes",
          "ec2:DescribeVpcAttribute",
          "ec2:DescribeVpcs"
        ]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = var.aws_region } }
      },
      {
        Sid      = "ReadDemoBudget"
        Effect   = "Allow"
        Action   = ["budgets:ViewBudget", "budgets:ListTagsForResource"]
        Resource = "arn:${data.aws_partition.current.partition}:budgets::${data.aws_caller_identity.current.account_id}:budget/${local.name}-monthly"
      },
      {
        Sid      = "ListBackendWorkspace"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}"
        Condition = {
          StringLike = { "s3:prefix" = [var.state_key, "${var.state_key}.tflock", "env:/"] }
        }
      },
      {
        Sid      = "ReadState"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = local.state_arn
      },
      {
        Sid      = "ManageExactStateLock"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${local.state_arn}.tflock"
      }
    ]
  })
}

resource "aws_iam_role" "shutdown" {
  name                 = "${local.name}-github-shutdown"
  description          = "CloudGuard shutdown of explicitly tagged demo instances."
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = var.oidc_provider_arn }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.main_subject
        }
      }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "shutdown" {
  name = "stop-opted-in-demo-instances"
  role = aws_iam_role.shutdown.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ReadInstancesAndCpu"
        Effect    = "Allow"
        Action    = ["ec2:DescribeInstances", "cloudwatch:GetMetricData"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = var.aws_region } }
      },
      {
        Sid      = "StopOnlyOptedInDemoInstances"
        Effect   = "Allow"
        Action   = ["ec2:StopInstances"]
        Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/Project"     = var.project_name
            "ec2:ResourceTag/Environment" = var.environment
            "ec2:ResourceTag/AutoStop"    = "true"
          }
        }
      }
    ]
  })
}
