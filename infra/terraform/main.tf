# Root module — wires all child modules together.
# Dependency order: dns_tls → networking → registry → compute → cdn → data_storage → feedback

module "dns_tls" {
  source      = "./modules/dns_tls"
  domain_name = var.domain_name
  project     = var.project
  # cloudfront_domain is wired in after cdn module is created — see dns_tls module for details
  cloudfront_domain = module.cdn.cloudfront_domain
}

module "networking" {
  source  = "./modules/networking"
  project = var.project
  region  = var.region
  azs     = var.azs
}

module "registry" {
  source  = "./modules/registry"
  project = var.project
}

module "compute" {
  source             = "./modules/compute"
  project            = var.project
  region             = var.region
  vpc_id             = module.networking.vpc_id
  public_subnet_ids  = module.networking.public_subnet_ids
  private_subnet_ids = module.networking.private_subnet_ids
  alb_sg_id          = module.networking.alb_sg_id
  ecs_sg_id          = module.networking.ecs_sg_id
  ecr_repo_url       = module.registry.repository_url
  image_tag          = var.backend_image_tag
  certificate_arn    = module.dns_tls.certificate_arn
  fargate_cpu        = var.fargate_cpu
  fargate_memory     = var.fargate_memory
  desired_count      = var.desired_count
  frontend_url       = "https://${var.domain_name}"
  ses_from_email     = var.ses_from_email
  ses_to_email       = var.ses_to_email
  # Deterministic name (not module.analytics.table_name) — avoids a
  # compute <-> analytics circular dependency, since the analytics module
  # already depends on compute for the ECS task role.
  analytics_table_name  = "${var.project}-analytics-events"
  analytics_admin_token = var.analytics_admin_token
}

module "cdn" {
  source          = "./modules/cdn"
  project         = var.project
  alb_dns_name    = module.compute.alb_dns_name
  certificate_arn = module.dns_tls.certificate_arn
  domain_name     = var.domain_name
}

module "data_storage" {
  source            = "./modules/data_storage"
  project           = var.project
  ecs_task_role_arn = module.compute.ecs_task_role_arn
}

module "feedback" {
  source             = "./modules/feedback"
  project            = var.project
  domain_name        = var.domain_name
  zone_id            = module.dns_tls.zone_id
  ecs_task_role_name = module.compute.ecs_task_role_name
  ses_from_email     = var.ses_from_email
}

module "analytics" {
  source             = "./modules/analytics"
  project            = var.project
  ecs_task_role_name = module.compute.ecs_task_role_name
}
