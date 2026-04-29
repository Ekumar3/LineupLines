variable "project" { type = string }
variable "ecs_task_role_arn" { type = string }

# S3 bucket for player ADP data (currently baked into Docker image;
# this bucket is ready for a future migration where the container loads data from S3 at startup)
resource "aws_s3_bucket" "player_data" {
  bucket = "${var.project}-player-data-prod"
  tags   = { Name = "${var.project}-player-data" }
}

resource "aws_s3_bucket_versioning" "player_data" {
  bucket = aws_s3_bucket.player_data.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "player_data" {
  bucket                  = aws_s3_bucket.player_data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Allow the ECS task role to read data files from this bucket
resource "aws_iam_role_policy" "ecs_task_s3_read" {
  name = "${var.project}-ecs-task-s3-read"

  # We can't use role_name here since we only have the ARN.
  # Extract the role name from the ARN: arn:aws:iam::<acct>:role/<name>
  role = element(split("/", var.ecs_task_role_arn), length(split("/", var.ecs_task_role_arn)) - 1)

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadPlayerData"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.player_data.arn,
        "${aws_s3_bucket.player_data.arn}/*",
      ]
    }]
  })
}
