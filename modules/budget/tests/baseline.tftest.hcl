mock_provider "aws" {}

variables {
  budget_email = "owner@example.com"
}

run "monthly_budget_and_alerts" {
  command = plan

  assert {
    condition     = aws_budgets_budget.this.limit_amount == "5" && aws_budgets_budget.this.limit_unit == "USD" && aws_budgets_budget.this.time_unit == "MONTHLY"
    error_message = "The default budget must notify on a USD 5 monthly limit."
  }
  assert {
    condition     = toset([for alert in aws_budgets_budget.this.notification : alert.threshold]) == toset([80, 100])
    error_message = "Configure both 80% and 100% alerts."
  }
  assert {
    condition     = alltrue([for alert in aws_budgets_budget.this.notification : alert.notification_type == "ACTUAL" && alert.threshold_type == "PERCENTAGE" && contains(alert.subscriber_email_addresses, "owner@example.com")])
    error_message = "Alerts must notify the configured email about actual spend percentages."
  }
}

run "reject_invalid_email" {
  command = plan
  variables {
    budget_email = "not-an-email"
  }
  expect_failures = [var.budget_email]
}

run "reject_nonpositive_budget" {
  command = plan
  variables {
    monthly_budget_usd = 0
  }
  expect_failures = [var.monthly_budget_usd]
}
