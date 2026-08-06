output "cloudfront_domain" {
  description = "CloudFront distribution domain (use this before DNS is fully set up)"
  value       = module.cdn.cloudfront_domain
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID — needed by the GitHub Actions frontend pipeline"
  value       = module.cdn.cloudfront_distribution_id
}

output "frontend_bucket_name" {
  description = "S3 bucket name for the React frontend build — needed by the GitHub Actions frontend pipeline"
  value       = module.cdn.frontend_bucket_name
}

output "ecr_repository_url" {
  description = "Full ECR repository URL for pushing Docker images"
  value       = module.registry.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name — needed by the GitHub Actions backend pipeline"
  value       = module.compute.ecs_cluster_name
}

output "ecs_service_name" {
  description = "ECS service name — needed by the GitHub Actions backend pipeline"
  value       = module.compute.ecs_service_name
}

output "alb_dns_name" {
  description = "ALB DNS name (for debugging; traffic goes through CloudFront in normal operation)"
  value       = module.compute.alb_dns_name
}

output "route53_nameservers" {
  description = "Nameservers to enter at your domain registrar (if not using Route 53 as registrar)"
  value       = module.dns_tls.nameservers
}

output "airflow_ecr_repository_url" {
  description = "Full ECR repository URL for pushing the Airflow image — needed by the GitHub Actions airflow pipeline"
  value       = module.registry.airflow_repository_url
}

output "airflow_ecs_service_name" {
  description = "Airflow ECS service name — needed by the GitHub Actions airflow pipeline"
  value       = module.airflow.ecs_service_name
}
