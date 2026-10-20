# VPC module

Creates one isolated VPC, two private subnets in different availability zones, and a shared route table. It removes all ingress and egress rules from the VPC's default security group. There is no internet gateway, NAT gateway, or public IP assignment.

From a root configuration with an AWS provider:

```hcl
module "vpc" {
  source             = "./modules/vpc"
  availability_zones = ["ap-south-1a", "ap-south-1b"]
}
```

| Input | Default / purpose |
| --- | --- |
| `availability_zones` | Required: two distinct zones in the provider region |
| `vpc_cidr` | `10.42.0.0/16` |
| `private_subnet_cidrs` | `10.42.1.0/24`, `10.42.2.0/24`; use nonoverlapping CIDRs inside the VPC |
| `project_name`, `environment` | `CloudGuard`, `demo` |
| `tags` | Extra tags; `Project`, `Environment`, and `ManagedBy` take precedence |

Outputs: `vpc_id`, `private_subnet_ids` (in input order), `private_route_table_id`, and `default_security_group_id`.

The optional demo instance deliberately uses the restricted default security group. Add explicit rules and networking before using this module for an application.
