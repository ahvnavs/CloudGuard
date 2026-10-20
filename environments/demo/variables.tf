variable "aws_region" {
  description = "Single deployment region."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Project tag; keep consistent with bootstrap and shutdown configuration."
  type        = string
  default     = "CloudGuard"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,24}$", var.project_name))
    error_message = "Use 1-24 letters, numbers, underscores or hyphens for project_name."
  }
}

variable "environment" {
  description = "Environment tag; keep consistent with bootstrap and shutdown configuration."
  type        = string
  default     = "demo"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,12}$", var.environment))
    error_message = "Use 1-12 letters, numbers, underscores or hyphens for environment."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR for the isolated VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "Two distinct IPv4 CIDRs inside vpc_cidr."
  type        = list(string)
  default     = ["10.42.1.0/24", "10.42.2.0/24"]
}

variable "monthly_budget_usd" {
  description = "Account-wide monthly cost alert threshold, not a spending cap."
  type        = number
  default     = 5
}

variable "budget_email" {
  description = "Email address for actual-spend alerts at 80% and 100%."
  type        = string
}

variable "enable_demo_instance" {
  description = "Create an optional paid EC2 instance. Disabled by default."
  type        = bool
  default     = false
}

variable "auto_stop" {
  description = "Opt the optional instance into idle shutdown; also enable stopping in the workflow."
  type        = bool
  default     = false
}

variable "ami_id" {
  description = "Optional region-specific AMI override; otherwise look up Amazon Linux 2023 x86_64."
  type        = string
  default     = null
  validation {
    condition     = var.ami_id == null ? true : can(regex("^ami-([a-f0-9]{8}|[a-f0-9]{17})$", var.ami_id))
    error_message = "Provide a valid AMI ID or null."
  }
}

variable "instance_type" {
  description = "EC2 instance type; the default AMI requires an x86_64 type."
  type        = string
  default     = "t3.micro"
}

variable "tags" {
  description = "Additional tags; reserved Project, Environment, ManagedBy and AutoStop tags take precedence."
  type        = map(string)
  default     = {}
}
