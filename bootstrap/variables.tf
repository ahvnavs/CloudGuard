variable "aws_region" {
  description = "Region for state storage and the demo."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Project tag and resource-name prefix."
  type        = string
  default     = "CloudGuard"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,24}$", var.project_name))
    error_message = "Use 1-24 letters, numbers, underscores or hyphens for project_name."
  }
}

variable "environment" {
  description = "Environment tag and resource-name suffix."
  type        = string
  default     = "demo"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,12}$", var.environment))
    error_message = "Use 1-12 letters, numbers, underscores or hyphens for environment."
  }
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name. Keep bootstrap state local and backed up."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "Use a valid, globally unique S3 bucket name."
  }
}

variable "github_repository" {
  description = "GitHub owner/repository trusted by the workflow roles."
  type        = string
  default     = "ahvnavs/CloudGuard"
}

variable "existing_oidc_provider_arn" {
  description = "Reuse an existing GitHub OIDC provider in this account; null creates one."
  type        = string
  default     = null
  validation {
    condition     = var.existing_oidc_provider_arn == null ? true : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:oidc-provider/token\\.actions\\.githubusercontent\\.com$", var.existing_oidc_provider_arn))
    error_message = "Provide a GitHub Actions OIDC provider ARN or null."
  }
}

variable "tags" {
  description = "Additional tags; reserved tags take precedence."
  type        = map(string)
  default     = {}
}
