# Budget module

Creates an account-wide monthly cost budget with email notifications when actual spending exceeds 80% and 100% of the configured amount. It needs no cost-allocation tag setup.

From a root configuration with an AWS provider:

```hcl
module "budget" {
  source             = "./modules/budget"
  budget_email       = "you@example.com"
  monthly_budget_usd = 5
}
```

| Input | Default / purpose |
| --- | --- |
| `budget_email` | Required: notification recipient |
| `monthly_budget_usd` | `5`; must be positive |
| `project_name`, `environment` | `CloudGuard`, `demo`; used in the budget name and tags |
| `tags` | Extra tags; reserved project, environment, and management tags take precedence |

Outputs: `budget_name` and `budget_arn`.

This budget includes spending elsewhere in the account. Alerts depend on AWS billing updates and do not cap spending or stop resources.
