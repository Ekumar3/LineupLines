variable "project" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "ecr_repo_url" { type = string }
variable "image_tag" { type = string }
variable "fargate_cpu" { type = number }
variable "fargate_memory" { type = number }
variable "ecs_cluster_id" { type = string }
variable "adp_s3_bucket_name" { type = string }
variable "adp_s3_bucket_arn" { type = string }
variable "adp_pipeline_end_date" { type = string }
variable "github_actions_role_name" { type = string }
variable "slack_webhook_url" {
  type      = string
  sensitive = true
}
