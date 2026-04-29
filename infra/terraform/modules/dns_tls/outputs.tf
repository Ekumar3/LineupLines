output "zone_id" {
  value       = aws_route53_zone.main.zone_id
  description = "Route 53 hosted zone ID — used by the feedback module to add SES DNS records"
}

output "certificate_arn" {
  value       = aws_acm_certificate_validation.main.certificate_arn
  description = "Validated ACM certificate ARN — used by CloudFront and ALB HTTPS listeners"
}

output "nameservers" {
  value       = aws_route53_zone.main.name_servers
  description = "Nameservers to enter at your domain registrar (only needed if Route 53 is not the registrar)"
}
