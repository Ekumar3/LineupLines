variable "project" { type = string }
variable "ecs_task_role_name" { type = string }

# Usage-analytics event store — page views, draft completions, feature clicks.
# On-demand billing since traffic volume is low and unpredictable.
resource "aws_dynamodb_table" "events" {
  name         = "${var.project}-analytics-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  tags = { Name = "${var.project}-analytics-events" }
}

# Allow the ECS task role to write and read analytics events
resource "aws_iam_role_policy" "ecs_task_analytics" {
  name = "${var.project}-ecs-task-analytics"
  role = var.ecs_task_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AnalyticsEventsReadWrite"
      Effect = "Allow"
      Action = ["dynamodb:PutItem", "dynamodb:Query"]
      Resource = [
        aws_dynamodb_table.events.arn,
        "${aws_dynamodb_table.events.arn}/index/*",
      ]
    }]
  })
}
