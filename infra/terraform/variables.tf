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

variable "analytics_admin_token" {
  description = "Bearer token required to read GET /api/v1/summary (usage analytics dashboard)"
  type        = string
  sensitive   = true
}

variable "airflow_image_tag" {
  description = "Docker image tag to deploy for the Airflow scheduler (e.g. a git SHA). Defaults to 'latest' — override in CI/CD."
  type        = string
  default     = "latest"
}

variable "airflow_fargate_cpu" {
  description = "ECS Fargate task CPU units for the Airflow scheduler (heavier than the API — bundles headless Chromium for Selenium scraping)"
  type        = number
  default     = 1024
}

variable "airflow_fargate_memory" {
  description = "ECS Fargate task memory in MB for the Airflow scheduler"
  type        = number
  default     = 2048
}

variable "adp_pipeline_end_date" {
  description = "Date the daily ADP scrape DAG auto-pauses (Airflow Variable ADP_PIPELINE_END_DATE) — no live drafts happen after the NFL season starts"
  type        = string
  default     = "2026-09-01"
}

variable "slack_webhook_url" {
  description = "Slack incoming webhook URL for the adp_scrape_dag on_failure alerts (slack_adp_alerts connection). Optional — if left empty, scripts/start.sh skips registering the connection and task failures just go unnotified instead of to Slack."
  type        = string
  sensitive   = true
  default     = ""
}
