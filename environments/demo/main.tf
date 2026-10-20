locals {
  name = "${var.project_name}-${var.environment}"
  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
    AutoStop    = tostring(var.auto_stop)
  })
}

data "aws_availability_zones" "available" {
  state = "available"
  filter {
    name   = "zone-type"
    values = ["availability-zone"]
  }
}

module "vpc" {
  source = "../../modules/vpc"

  project_name         = var.project_name
  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  private_subnet_cidrs = var.private_subnet_cidrs
  availability_zones   = slice(data.aws_availability_zones.available.names, 0, 2)
  tags                 = var.tags
}

module "budget" {
  source = "../../modules/budget"

  project_name       = var.project_name
  environment        = var.environment
  monthly_budget_usd = var.monthly_budget_usd
  budget_email       = var.budget_email
  tags               = var.tags
}

data "aws_ami" "amazon_linux" {
  count = var.enable_demo_instance && var.ami_id == null ? 1 : 0

  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-6.1-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "demo" {
  count = var.enable_demo_instance ? 1 : 0

  ami                         = var.ami_id != null ? var.ami_id : data.aws_ami.amazon_linux[0].id
  instance_type               = var.instance_type
  subnet_id                   = module.vpc.private_subnet_ids[0]
  vpc_security_group_ids      = [module.vpc.default_security_group_id]
  associate_public_ip_address = false
  monitoring                  = false

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    encrypted             = true
    volume_type           = "gp3"
    volume_size           = 8
    delete_on_termination = true
    tags                  = local.tags
  }

  # All ingress/egress is denied by the VPC's managed default security group.
  # No SSH key, instance profile, public IP, NAT or paid network endpoints.
  tags = merge(local.tags, { Name = "${local.name}-idle-demo" })
}
