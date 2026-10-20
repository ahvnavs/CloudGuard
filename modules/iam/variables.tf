variable "project_name" {
  description = "Project name and required stop-permission resource tag."
  type        = string
  default     = "CloudGuard"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,24}$", var.project_name))
    error_message = "Use 1-24 letters, numbers, underscores or hyphens for project_name."
  }
}

variable "environment" {
  description = "Environment name and required stop-permission resource tag."
  type        = string
  default     = "demo"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,12}$", var.environment))
    error_message = "Use 1-12 letters, numbers, underscores or hyphens for environment."
  }
}

variable "aws_region" {
  description = "AWS region in which the roles may read EC2 or stop opted-in instances."
  type        = string
  default     = "ap-south-1"
}

variable "github_repository" {
  description = "Exact GitHub owner/repository allowed to assume these roles."
  type        = string
  default     = "ahvnavs/CloudGuard"
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use an exact owner/repository, without wildcards."
  }
}

variable "github_branch" {
  description = "Default branch used by manual and scheduled workflows."
  type        = string
  default     = "main"
}

variable "oidc_provider_arn" {
  description = "GitHub token.actions.githubusercontent.com OIDC provider ARN in this account."
  type        = string
  validation {
    condition     = can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.oidc_provider_arn))
    error_message = "Provide the GitHub Actions OIDC provider ARN in this AWS account."
  }
}

variable "state_bucket_name" {
  description = "Existing S3 bucket holding only this demo's backend state and lock."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "Provide an exact S3 bucket name without wildcard characters."
  }
}

variable "state_key" {
  description = "Exact default-workspace S3 state object key."
  type        = string
  default     = "demo/terraform.tfstate"
  validation {
    condition     = can(regex("^[A-Za-z0-9/_=.-]+$", var.state_key)) && !startswith(var.state_key, "/")
    error_message = "Use a relative state object key without wildcard characters."
  }
}

variable "tags" {
  description = "Additional tags; reserved tags take precedence."
  type        = map(string)
  default     = {}
}
