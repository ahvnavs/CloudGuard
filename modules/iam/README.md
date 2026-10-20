# GitHub workflow IAM module

Creates two GitHub OIDC roles: one for Terraform plans and drift checks, and one for idle-instance shutdown. [Bootstrap](../../bootstrap/) creates the S3 state bucket and creates or reuses the GitHub OIDC provider before calling this module.

From a root configuration with an AWS provider:

```hcl
module "iam" {
  source            = "./modules/iam"
  github_repository = "ahvnavs/CloudGuard"
  oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  state_bucket_name = "your-cloudguard-state-bucket"
}
```

| Input | Default / purpose |
| --- | --- |
| `oidc_provider_arn` | Required: GitHub OIDC provider in the same AWS account |
| `state_bucket_name` | Required: exact existing S3 bucket name |
| `state_key` | `demo/terraform.tfstate`; default workspace only |
| `github_repository`, `github_branch` | `ahvnavs/CloudGuard`, `main`; exact repository and scheduled-workflow branch |
| `aws_region` | `ap-south-1`; region for EC2 reads and stops |
| `project_name`, `environment` | `CloudGuard`, `demo`; budget name and required stop-permission tags |
| `tags` | Extra role tags; reserved tags take precedence |

Outputs: `plan_role_arn` and `shutdown_role_arn`.

The plan role trusts the repository's pull-request subject and configured branch. It grants enumerated AWS reads, access to the exact state object, and writes only to its `.tflock` object. It cannot apply Terraform changes. Workflow checks must still restrict which pull requests receive AWS credentials.

The shutdown role trusts only the configured branch. It can read instance/CPU data and stop instances in the configured account and region only when all three tags match: `Project`, `Environment`, and `AutoStop=true`. Idle detection and dry-run behavior belong to the shutdown script.
