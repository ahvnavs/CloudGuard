locals {
  name = "${var.project_name}-${var.environment}"
  tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  })
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = local.name })
}

# Explicit empty rules remove AWS's default self-ingress and allow-all egress.
resource "aws_default_security_group" "this" {
  vpc_id  = aws_vpc.this.id
  ingress = []
  egress  = []
  tags    = merge(local.tags, { Name = "${local.name}-default-deny" })
}

resource "aws_subnet" "private" {
  for_each = { for index, cidr in var.private_subnet_cidrs : tostring(index) => cidr }

  vpc_id                  = aws_vpc.this.id
  cidr_block              = each.value
  availability_zone       = var.availability_zones[tonumber(each.key)]
  map_public_ip_on_launch = false
  tags                    = merge(local.tags, { Name = "${local.name}-private-${tonumber(each.key) + 1}" })
}

# Only AWS's implicit local route exists: no IGW, NAT gateway or internet route.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  route  = []
  tags   = merge(local.tags, { Name = "${local.name}-isolated" })
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}
