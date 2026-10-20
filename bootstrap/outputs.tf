output "state_bucket_name" {
  description = "Use as bucket in the demo's backend.hcl."
  value       = aws_s3_bucket.state.id
}

output "state_key" {
  description = "Use as key in the demo's backend.hcl."
  value       = local.state_key
}

output "aws_region" {
  description = "Region for backend and workflow configuration."
  value       = var.aws_region
}

output "oidc_provider_arn" {
  description = "Created or reused GitHub OIDC provider."
  value       = local.oidc_provider_arn
}

output "plan_role_arn" {
  description = "GitHub Actions role for planning and drift; never apply."
  value       = module.iam.plan_role_arn
}

output "shutdown_role_arn" {
  description = "GitHub Actions role for tagged-instance idle shutdown."
  value       = module.iam.shutdown_role_arn
}
