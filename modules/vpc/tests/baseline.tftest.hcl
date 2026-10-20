mock_provider "aws" {}

variables {
  availability_zones = ["ap-south-1a", "ap-south-1b"]
  tags = {
    Project     = "cannot-override"
    Environment = "cannot-override"
    ManagedBy   = "cannot-override"
    Owner       = "portfolio"
  }
}

run "isolated_network" {
  command = plan

  assert {
    condition     = length(aws_subnet.private) == 2 && alltrue([for subnet in aws_subnet.private : !subnet.map_public_ip_on_launch])
    error_message = "Both private subnets must disable automatic public IPv4 assignment."
  }
  assert {
    condition     = length(aws_default_security_group.this.ingress) == 0 && length(aws_default_security_group.this.egress) == 0
    error_message = "The default security group must have no ingress or egress rules."
  }
  assert {
    condition     = length(aws_route_table.private.route) == 0
    error_message = "Private subnets must have no configured internet routes."
  }
  assert {
    condition     = aws_vpc.this.tags.Project == "CloudGuard" && aws_vpc.this.tags.Environment == "demo" && aws_vpc.this.tags.ManagedBy == "Terraform" && aws_vpc.this.tags.Owner == "portfolio"
    error_message = "Reserved tags must win while preserving additional tags."
  }
  assert {
    condition     = toset([for subnet in aws_subnet.private : subnet.availability_zone]) == toset(["ap-south-1a", "ap-south-1b"])
    error_message = "The private subnets must use distinct availability zones."
  }
}

run "reject_repeated_availability_zone" {
  command = plan
  variables {
    availability_zones = ["ap-south-1a", "ap-south-1a"]
  }
  expect_failures = [var.availability_zones]
}
