mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}

variables {
  oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  state_bucket_name = "cloudguard-test-state"
}

run "repository_scoped_oidc" {
  command = plan

  assert {
    condition     = toset(jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == toset(["repo:ahvnavs/CloudGuard:pull_request", "repo:ahvnavs/CloudGuard:ref:refs/heads/main"])
    error_message = "The planning role may trust only this repository's PR and main-branch subjects."
  }
  assert {
    condition     = jsondecode(aws_iam_role.shutdown.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:ahvnavs/CloudGuard:ref:refs/heads/main"
    error_message = "Shutdown must trust only this repository's main branch."
  }
  assert {
    condition     = jsondecode(aws_iam_role.plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" && jsondecode(aws_iam_role.shutdown.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "Both roles must require the STS audience."
  }
}

run "least_privilege_permissions" {
  command = plan

  assert {
    condition     = alltrue([for action in jsondecode(aws_iam_role_policy.plan.policy).Statement[0].Action : startswith(action, "ec2:Describe") && !strcontains(action, "*")])
    error_message = "EC2 planning access must enumerate only read APIs."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.plan.policy).Statement[3].Resource == "arn:aws:s3:::cloudguard-test-state/demo/terraform.tfstate" && jsondecode(aws_iam_role_policy.plan.policy).Statement[3].Action == ["s3:GetObject"]
    error_message = "The planner may read, but never write, the exact deployed state object."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.plan.policy).Statement[4].Resource == "arn:aws:s3:::cloudguard-test-state/demo/terraform.tfstate.tflock"
    error_message = "State writes must target only the exact native S3 lock object."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.shutdown.policy).Statement[1].Action == ["ec2:StopInstances"] && jsondecode(aws_iam_role_policy.shutdown.policy).Statement[1].Resource == "arn:aws:ec2:ap-south-1:123456789012:instance/*"
    error_message = "Shutdown may stop only instance resources in the configured account and region."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.shutdown.policy).Statement[1].Condition.StringEquals == { "ec2:ResourceTag/Project" = "CloudGuard", "ec2:ResourceTag/Environment" = "demo", "ec2:ResourceTag/AutoStop" = "true" }
    error_message = "All three opt-in resource tags must be required by IAM."
  }
}

run "reject_wildcard_repository" {
  command = plan
  variables {
    github_repository = "ahvnavs/*"
  }
  expect_failures = [var.github_repository]
}

run "reject_wildcard_state_key" {
  command = plan
  variables {
    state_key = "demo/*"
  }
  expect_failures = [var.state_key]
}
