output "repository_url" {
  value       = aws_ecr_repository.api.repository_url
  description = "Full ECR URL: <account_id>.dkr.ecr.<region>.amazonaws.com/<project>-api"
}

output "repository_name" {
  value = aws_ecr_repository.api.name
}

output "airflow_repository_url" {
  value       = aws_ecr_repository.airflow.repository_url
  description = "Full ECR URL: <account_id>.dkr.ecr.<region>.amazonaws.com/<project>-airflow"
}

output "airflow_repository_name" {
  value = aws_ecr_repository.airflow.name
}
