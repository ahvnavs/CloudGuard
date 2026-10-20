output "budget_name" {
  description = "Name of the account-wide monthly cost budget."
  value       = aws_budgets_budget.this.name
}

output "budget_arn" {
  description = "Budget ARN."
  value       = aws_budgets_budget.this.arn
}
