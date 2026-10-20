output "plan_role_arn" {
  description = "OIDC role for planning and drift checks; no apply permission."
  value       = aws_iam_role.plan.arn
}

output "shutdown_role_arn" {
  description = "OIDC role restricted to stopping tagged demo instances."
  value       = aws_iam_role.shutdown.arn
}
