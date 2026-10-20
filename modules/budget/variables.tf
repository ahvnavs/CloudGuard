variable "project_name" {
  description = "Project tag and budget-name prefix."
  type        = string
  default     = "CloudGuard"
}

variable "environment" {
  description = "Environment tag and budget-name suffix."
  type        = string
  default     = "demo"
}

variable "monthly_budget_usd" {
  description = "Monthly account-wide cost notification threshold in USD; this does not cap spending."
  type        = number
  default     = 5
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than zero."
  }
}

variable "budget_email" {
  description = "Email address that receives actual-spend alerts at 80% and 100%."
  type        = string
  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "Provide a valid notification email address."
  }
}

variable "tags" {
  description = "Additional tags; reserved tags take precedence."
  type        = map(string)
  default     = {}
}
