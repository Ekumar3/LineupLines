# Run this ONCE, locally, before any other Terraform work.
# It creates the S3 bucket and DynamoDB table that all other modules use for remote state.
#
# Usage:
#   cd infra/terraform/state_bootstrap
#   terraform init
#   terraform apply
#
# After apply, copy the bucket name into infra/terraform/backend.tf

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.6"
}

provider "aws" {
  region = var.region
}

variable "region" {
  description = "AWS region for the state bucket"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name prefix for resource names"
  type        = string
  default     = "lineuplines"
}

# S3 bucket for Terraform state files
resource "aws_s3_bucket" "tf_state" {
  bucket = "${var.project}-terraform-state-${data.aws_caller_identity.current.account_id}"

  # Prevent accidental deletion of this bucket (it holds your entire infra state)
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${var.project}-terraform-state"
    Project = var.project
    Purpose = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# DynamoDB table for state locking (prevents concurrent applies)
resource "aws_dynamodb_table" "tf_lock" {
  name         = "${var.project}-terraform-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${var.project}-terraform-locks"
    Project = var.project
    Purpose = "terraform-state-lock"
  }
}

data "aws_caller_identity" "current" {}

output "state_bucket_name" {
  value       = aws_s3_bucket.tf_state.bucket
  description = "Paste this into infra/terraform/backend.tf as the bucket value"
}

output "dynamodb_table_name" {
  value       = aws_dynamodb_table.tf_lock.name
  description = "Paste this into infra/terraform/backend.tf as the dynamodb_table value"
}
