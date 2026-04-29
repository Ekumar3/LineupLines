variable "project" { type = string }
variable "domain_name" { type = string }
variable "cloudfront_domain" { type = string }

# Route 53 hosted zone for the domain.
# If you registered the domain outside of Route 53, point your registrar's nameservers
# at the values output by this module before running subsequent modules.
resource "aws_route53_zone" "main" {
  name = var.domain_name
  tags = { Name = "${var.project}-zone" }
}

# ACM certificate for the apex domain + www subdomain.
# Must be in us-east-1 for CloudFront compatibility (CloudFront only accepts us-east-1 certs).
resource "aws_acm_certificate" "main" {
  domain_name               = var.domain_name
  subject_alternative_names = ["www.${var.domain_name}"]
  validation_method         = "DNS"

  # Recreate before destroying to ensure no downtime during cert renewal
  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.project}-cert" }
}

# Automatically create the DNS validation records in Route 53
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = aws_route53_zone.main.zone_id
}

# Wait for ACM to verify the certificate before proceeding
resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# DNS A record: apex domain → CloudFront
resource "aws_route53_record" "apex" {
  zone_id = aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = var.cloudfront_domain
    zone_id                = "Z2FDTNDATAQYW2" # CloudFront's fixed hosted zone ID
    evaluate_target_health = false
  }
}

# DNS CNAME: www → apex
resource "aws_route53_record" "www" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "www.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = [var.domain_name]
}
