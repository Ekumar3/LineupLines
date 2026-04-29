variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "azs" {
  description = "Availability zones to use within the region"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "project" {
  description = "Short project name used as a prefix for all resource names"
  type        = string
  default     = "lineuplines"
}

variable "domain_name" {
  description = "Primary domain name (e.g. lineuplines.com). Must be registered in Route 53."
  type        = string
}

variable "ses_from_email" {
  description = "Verified SES sender address for outbound feedback emails (e.g. feedback@lineuplines.com)"
  type        = string
}

variable "ses_to_email" {
  description = "Your personal inbox that receives feedback submissions"
  type        = string
}

variable "backend_image_tag" {
  description = "Docker image tag to deploy (e.g. a git SHA). Defaults to 'latest' — override in CI/CD."
  type        = string
  default     = "latest"
}

variable "fargate_cpu" {
  description = "ECS Fargate task CPU units (256 = 0.25 vCPU)"
  type        = number
  default     = 512
}

variable "fargate_memory" {
  description = "ECS Fargate task memory in MB"
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Desired number of running ECS tasks (1 for beta)"
  type        = number
  default     = 1
}
