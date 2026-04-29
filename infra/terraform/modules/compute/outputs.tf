output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "ALB DNS name — used as CloudFront backend origin"
}

output "ecs_task_role_arn" {
  value       = aws_iam_role.ecs_task.arn
  description = "ARN of the ECS task role — data_storage module attaches an S3 policy to it"
}

output "ecs_task_role_name" {
  value       = aws_iam_role.ecs_task.name
  description = "Name of the ECS task role — feedback module attaches an SES policy to it"
}

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "IAM role ARN for GitHub Actions OIDC — paste into GitHub Actions workflow"
}
