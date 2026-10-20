variable "project_name" {
  description = "Project tag and resource-name prefix."
  type        = string
  default     = "CloudGuard"
}

variable "environment" {
  description = "Environment tag and resource-name suffix."
  type        = string
  default     = "demo"
}

variable "vpc_cidr" {
  description = "IPv4 CIDR for the isolated VPC."
  type        = string
  default     = "10.42.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR."
  }
}

variable "private_subnet_cidrs" {
  description = "Two distinct IPv4 CIDRs within the VPC, one per availability zone."
  type        = list(string)
  default     = ["10.42.1.0/24", "10.42.2.0/24"]
  validation {
    condition     = length(var.private_subnet_cidrs) == 2 && length(distinct(var.private_subnet_cidrs)) == 2 && alltrue([for cidr in var.private_subnet_cidrs : can(cidrnetmask(cidr))])
    error_message = "Provide two distinct valid IPv4 subnet CIDRs."
  }
}

variable "availability_zones" {
  description = "Two distinct availability zones in the provider region."
  type        = list(string)
  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Provide exactly two distinct availability zones."
  }
}

variable "tags" {
  description = "Additional tags; reserved project, environment and management tags take precedence."
  type        = map(string)
  default     = {}
}
