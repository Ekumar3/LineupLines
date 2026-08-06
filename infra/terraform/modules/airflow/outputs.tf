output "ecs_service_name" {
  value = aws_ecs_service.airflow.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.airflow.name
}
