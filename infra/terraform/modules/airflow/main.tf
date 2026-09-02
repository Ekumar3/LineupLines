data "aws_caller_identity" "current" {}

# CloudWatch log group for the scheduler's output
resource "aws_cloudwatch_log_group" "airflow" {
  name              = "/ecs/${var.project}-airflow"
  retention_in_days = 30
  tags              = { Name = "${var.project}-airflow-logs" }
}

# Security group: scheduler only, no listener — zero inbound, full outbound
# (DraftSharks scrape, Sleeper API, Slack webhook, S3, ECR pull).
resource "aws_security_group" "airflow" {
  name        = "${var.project}-airflow-sg"
  description = "Airflow scheduler task - no inbound; outbound only (DraftSharks, Sleeper API, Slack, S3, ECR)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-airflow-sg" }
}

# EFS security group: NFS from the Airflow task only
resource "aws_security_group" "efs" {
  name        = "${var.project}-airflow-efs-sg"
  description = "Allow NFS from the Airflow ECS task only"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.airflow.id]
    description     = "NFS from Airflow scheduler task"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-airflow-efs-sg" }
}

# EFS holds the SQLite metadata DB so it survives Fargate task restarts/redeploys.
resource "aws_efs_file_system" "airflow_db" {
  encrypted = true
  tags      = { Name = "${var.project}-airflow-db" }
}

resource "aws_efs_mount_target" "airflow_db" {
  count           = length(var.private_subnet_ids)
  file_system_id  = aws_efs_file_system.airflow_db.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

# astro-runtime images run as uid=50000/gid=50000 ("astro"), not root — verified
# via `docker run --rm quay.io/astronomer/astro-runtime:13.8.0 id`. The access
# point's POSIX user/root-directory must match, or the container can't write
# airflow.db.
resource "aws_efs_access_point" "airflow_db" {
  file_system_id = aws_efs_file_system.airflow_db.id

  posix_user {
    uid = 50000
    gid = 50000
  }

  root_directory {
    path = "/airflow-db"
    creation_info {
      owner_uid   = 50000
      owner_gid   = 50000
      permissions = "755"
    }
  }

  tags = { Name = "${var.project}-airflow-db-ap" }
}

# IAM: ECS task execution role (allows ECS to pull images, write logs) — same
# shape as compute's, but a separate role since this is a separate service.
resource "aws_iam_role" "airflow_execution" {
  name = "${var.project}-airflow-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project}-airflow-execution-role" }
}

resource "aws_iam_role_policy_attachment" "airflow_execution_managed" {
  role       = aws_iam_role.airflow_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# IAM: ECS task role — not shared with the API's task role. Write access to
# the player-data bucket (write_s3 task calls put_object; get/list included
# for idempotency checks), scoped the same two-resource-entry way as
# data_storage's ecs_task_s3_read policy for the API task role.
resource "aws_iam_role" "airflow_task" {
  name = "${var.project}-airflow-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project}-airflow-task-role" }
}

resource "aws_iam_role_policy" "airflow_task_s3_write" {
  name = "${var.project}-airflow-task-s3-write"
  role = aws_iam_role.airflow_task.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WritePlayerData"
      Effect = "Allow"
      Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
      Resource = [
        var.adp_s3_bucket_arn,
        "${var.adp_s3_bucket_arn}/*",
      ]
    }]
  })
}

# Required on the task role (not the execution role) for `aws ecs
# execute-command` to open a shell into the running task via SSM.
resource "aws_iam_role_policy" "airflow_task_exec" {
  name = "${var.project}-airflow-task-exec"
  role = aws_iam_role.airflow_task.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ECSExec"
      Effect = "Allow"
      Action = [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
      ]
      Resource = "*"
    }]
  })
}

# ECS Task Definition — scheduler only, LocalExecutor + SQLite on EFS.
# No command/entrypoint override: the image's own CMD (bash scripts/start.sh)
# runs `airflow db migrate` then execs `airflow scheduler`.
resource "aws_ecs_task_definition" "airflow" {
  family                   = "${var.project}-airflow"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.airflow_execution.arn
  task_role_arn            = aws_iam_role.airflow_task.arn

  volume {
    name = "airflow-db"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.airflow_db.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.airflow_db.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "${var.project}-airflow"
      image     = "${var.ecr_repo_url}:${var.image_tag}"
      essential = true

      # Mounted as a subdirectory (not /usr/local/airflow itself) so it
      # doesn't shadow the image's baked-in dags/, plugins/, include/.
      mountPoints = [{
        sourceVolume  = "airflow-db"
        containerPath = "/usr/local/airflow/db"
        readOnly      = false
      }]

      # AIRFLOW__CORE__EXECUTOR=SequentialExecutor, not LocalExecutor: Airflow
      # hard-rejects LocalExecutor+SQLite ("cannot use SQLite with the
      # LocalExecutor") — confirmed by running `airflow db migrate` against
      # this image locally. SequentialExecutor is SQLite's only supported
      # executor; fully serial task execution is fine for a once-daily batch
      # of ~52 short tasks with no urgency, and keeps SQLite/no-RDS cost.
      #
      # AIRFLOW__DATABASE__SQL_ALCHEMY_CONN is deliberately NOT set here —
      # see scripts/start.sh for why (astro-runtime's own entrypoint hangs
      # forever trying to netcat-connect to a SQLite URI's empty host:port).
      environment = [
        { name = "AIRFLOW__CORE__EXECUTOR", value = "SequentialExecutor" },
        { name = "AIRFLOW_VAR_ADP_S3_BUCKET", value = var.adp_s3_bucket_name },
        { name = "AIRFLOW_VAR_ADP_PIPELINE_END_DATE", value = var.adp_pipeline_end_date },
        { name = "SLACK_WEBHOOK_URL", value = var.slack_webhook_url },
        { name = "AWS_REGION", value = var.region },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.airflow.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = { Name = "${var.project}-airflow-task" }
}

# ECS Service — single always-on scheduler task, no load balancer.
resource "aws_ecs_service" "airflow" {
  name            = "${var.project}-airflow"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.airflow.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # Lets `aws ecs execute-command` open a shell into the running task for
  # live debugging — task-instance logs live only on the container's local
  # filesystem (not on the EFS-mounted /usr/local/airflow/db path, and not
  # captured by the scheduler's stdout->CloudWatch log group), so this is
  # the only way to inspect them without adding remote task logging.
  enable_execute_command = true

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.airflow.id]
    assign_public_ip = false
  }

  # SQLite is single-writer, and EFS/NFS file locking is unreliable for it.
  # A normal rolling deploy (min healthy 100%, like the API service) would run
  # the old and new scheduler tasks against the same airflow.db at once and
  # risk corrupting it. Force the old task to fully stop before the new one
  # starts by allowing the running count to drop to 0 during deploys.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  depends_on = [
    aws_iam_role_policy_attachment.airflow_execution_managed,
    aws_efs_mount_target.airflow_db,
  ]

  # Ignore task definition changes from Terraform after initial deploy —
  # GitHub Actions manages the image tag via aws ecs update-service.
  lifecycle {
    ignore_changes = [task_definition]
  }

  tags = { Name = "${var.project}-airflow-service" }
}

# Additive grant on the existing GitHub Actions OIDC role: ECR push scoped to
# just this new repo. ecr:GetAuthorizationToken and the ecs:* / iam:PassRole
# grants on compute's github_actions policy are already Resource="*", so they
# already cover this service/task family with no changes needed there.
resource "aws_iam_role_policy" "github_actions_airflow_ecr_push" {
  name = "${var.project}-github-actions-airflow-ecr-push"
  role = var.github_actions_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ECRPushAirflow"
      Effect = "Allow"
      Action = [
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
      ]
      Resource = "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/${var.project}-airflow"
    }]
  })
}
