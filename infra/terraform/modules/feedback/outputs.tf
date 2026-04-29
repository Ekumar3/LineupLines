output "ses_domain_identity_arn" {
  value       = aws_ses_domain_identity.main.arn
  description = "SES domain identity ARN"
}
