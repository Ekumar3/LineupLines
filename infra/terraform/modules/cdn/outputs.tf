output "cloudfront_domain" {
  value       = aws_cloudfront_distribution.main.domain_name
  description = "CloudFront domain (e.g. d1234abcd.cloudfront.net) — used by dns_tls module as the A record alias"
}

output "cloudfront_distribution_id" {
  value       = aws_cloudfront_distribution.main.id
  description = "CloudFront distribution ID — used by GitHub Actions to invalidate the cache after frontend deploys"
}

output "frontend_bucket_name" {
  value       = aws_s3_bucket.frontend.bucket
  description = "S3 bucket name — used by GitHub Actions to sync the React build"
}

output "frontend_bucket_arn" {
  value = aws_s3_bucket.frontend.arn
}
