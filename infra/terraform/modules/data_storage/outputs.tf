output "player_data_bucket_name" {
  value       = aws_s3_bucket.player_data.bucket
  description = "S3 bucket for player ADP data files"
}

output "player_data_bucket_arn" {
  value = aws_s3_bucket.player_data.arn
}
