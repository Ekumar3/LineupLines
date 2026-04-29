variable "project" { type = string }
variable "domain_name" { type = string }
variable "zone_id" { type = string }
variable "ecs_task_role_name" { type = string }
variable "ses_from_email" { type = string }

# SES domain identity — AWS needs to verify we own the domain before sending email from it
resource "aws_ses_domain_identity" "main" {
  domain = var.domain_name
}

# DNS TXT record for SES domain ownership verification
resource "aws_route53_record" "ses_verification" {
  zone_id = var.zone_id
  name    = "_amazonses.${var.domain_name}"
  type    = "TXT"
  ttl     = 300
  records = [aws_ses_domain_identity.main.verification_token]
}

resource "aws_ses_domain_identity_verification" "main" {
  domain     = aws_ses_domain_identity.main.id
  depends_on = [aws_route53_record.ses_verification]
}

# DKIM — improves deliverability by signing outgoing emails cryptographically
resource "aws_ses_domain_dkim" "main" {
  domain = aws_ses_domain_identity.main.domain
}

resource "aws_route53_record" "dkim" {
  count   = 3
  zone_id = var.zone_id
  name    = "${aws_ses_domain_dkim.main.dkim_tokens[count.index]}._domainkey.${var.domain_name}"
  type    = "CNAME"
  ttl     = 300
  records = ["${aws_ses_domain_dkim.main.dkim_tokens[count.index]}.dkim.amazonses.com"]
}

# Allow the ECS task role to send email via SES
resource "aws_iam_role_policy" "ecs_task_ses_send" {
  name = "${var.project}-ecs-task-ses-send"
  role = var.ecs_task_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SESSendEmail"
      Effect   = "Allow"
      Action   = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource = "*"
      Condition = {
        StringLike = {
          "ses:FromAddress" = var.ses_from_email
        }
      }
    }]
  })
}
