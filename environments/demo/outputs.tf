output "vpc_id" {
  description = "Isolated VPC ID."
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnets in two availability zones."
  value       = module.vpc.private_subnet_ids
}

output "default_security_group_id" {
  description = "Security group with no ingress or egress."
  value       = module.vpc.default_security_group_id
}

output "budget_name" {
  description = "Account-wide monthly cost budget."
  value       = module.budget.budget_name
}

output "demo_instance_id" {
  description = "Optional instance ID, or null when disabled."
  value       = one(aws_instance.demo[*].id)
}
