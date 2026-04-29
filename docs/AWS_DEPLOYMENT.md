# AWS Deployment Plan — LineupLines Beta

## Context

LineupLines (FastAPI backend + React frontend) is ready for beta testing with friends. This document
covers the full deployment architecture, infrastructure decisions, and step-by-step deployment guide.

Your existing `docs/DEPLOYMENT.md` mentions Lambda + API Gateway as a deployment option. **This
plan deliberately rejects that approach** and explains why below.

---

## Decision 1: ECS Fargate, not Lambda

### Why Lambda was ruled out

Your backend uses **Server-Sent Events (SSE)** — the `GET /api/v1/drafts/{draft_id}/stream`
endpoint keeps an HTTP connection open indefinitely, pushing events to the browser as they happen.
Lambda's execution model is fundamentally incompatible with this:

| Constraint | Impact on SSE |
|------------|---------------|
| **API Gateway REST/HTTP timeout: 29–30s** | An SSE connection that outlasts 30s gets hard-terminated by API Gateway — the browser reconnects, creating a polling loop instead of a stream |
| **Lambda charges per 1ms of duration** | One user watching a 60-minute draft = one Lambda invocation running for 3,600,000ms = ~$0.06 per user per draft. With 20 friends watching = $1.20/draft. Unacceptable. |
| **Lambda invocations are isolated processes** | Your `DraftBroadcaster` uses in-memory asyncio queues shared across all connections to the same draft. In Lambda, each invocation is a separate process — the broadcaster can't exist. You'd need a completely different architecture (Redis, EventBridge, SQS) |
| **Cold starts disconnect clients** | Lambda scales by spawning new invocations. A cold start on an SSE handler tears down the connection, requiring browser reconnect |

> **Lambda Function URLs** (a newer feature) do support HTTP response streaming and could
> technically serve SSE — but they don't solve the billing problem or the in-memory broadcaster
> isolation problem. You'd also need to rebuild the broadcaster around Redis anyway, which is
> a bigger change than simply using ECS.

### Why ECS Fargate was chosen

ECS Fargate runs your existing Docker container as a persistent process — the same model as
running `uvicorn` locally, just managed by AWS. Key properties:

- **Persistent process**: SSE connections stay alive as long as the task runs. No timeouts imposed by the compute layer.
- **Your code is unchanged**: The `DraftBroadcaster` with its asyncio queues works exactly as it does locally.
- **ALB idle timeout is configurable**: Set to 3600s — an SSE connection can stay open for an hour before the ALB closes it (browsers reconnect automatically anyway).
- **No server management**: AWS manages the underlying EC2 host. You just define CPU/memory and a Docker image.
- **Familiar Docker workflow**: Your Dockerfile already exists. Push to ECR, point the task definition at it, done.

### Why not App Runner (simpler managed container service)?

AWS App Runner is worth considering — it's simpler than ECS (no VPC, no ALB to configure, just
point at your Docker image). **The reason it's rejected here is sticky sessions.** Your
`DraftBroadcaster` is in-memory. If you ever run 2 App Runner instances, a user could connect to
instance A while the broadcaster on instance B is the one polling for their draft. App Runner has
no native sticky session support. ECS + ALB has sticky sessions as a built-in feature (one
checkbox in Terraform). Since sticky sessions are the beta-scale solution for the broadcaster,
ALB is required.

---

## Decision 2: S3 + CloudFront for the frontend (not serving from FastAPI)

Your React app builds to a `dist/` directory of static HTML/JS/CSS files. Two options exist:

**Option A — FastAPI serves the frontend** (mount `StaticFiles` in main.py):
- Single Docker image, single deployment unit
- ❌ Mixes frontend and backend concerns — a CSS tweak forces a full backend redeploy
- ❌ FastAPI serves static files sequentially; CloudFront caches them globally at edge
- ❌ No cache busting control (Vite generates content-hashed filenames, CloudFront handles this automatically)

**Option B — S3 + CloudFront** (this plan):
- S3 stores the static build; CloudFront serves it from 400+ edge locations globally
- ✅ Frontend deploys are ~20s (S3 sync + cache invalidation) with no backend disruption
- ✅ Near-zero cost (S3 + CloudFront free tier covers most beta traffic)
- ✅ CloudFront routes `/api/*` to the ALB — the browser never sees a CORS issue because both the frontend and backend share the same domain
- ✅ Independent pipelines: changing a Tailwind class doesn't redeploy the backend

---

## Decision 3: ALB sticky sessions (not Redis) for the SSE broadcaster

The `DraftBroadcaster` is in-memory. If you run 2 ECS tasks:
- Task A has its own broadcaster polling draft X
- Task B has its own broadcaster polling draft X
- Result: 2 Sleeper poll loops per draft instead of 1 (doubles API usage)
- A user connected to Task A doesn't "see" picks that Task B notified about (they both poll independently so both get all picks — correctness is maintained, efficiency is not)

**The proper fix** is to replace asyncio queues with **Redis Pub/Sub**: one polling loop publishes
events to a Redis channel; all ECS tasks subscribe and forward to their connected clients. This
is a meaningful code change and adds ElastiCache (~$15–20/month) to the stack.

**For beta with friends, this is overkill.** The plan uses **ALB sticky sessions** instead:
the ALB pins each browser session to the same ECS task (via a cookie). All your friends hit the
same task. The broadcaster works as designed. When you outgrow 1 task, add Redis.

---

## Decision 4: Single region (us-east-1) for beta

CloudFront already makes the **frontend** global — your friends in California get HTML/CSS/JS from
an LA edge node, not a Virginia server. The only latency difference between regions is for
**API calls** (draft data, roster data), which are already network-bound by Sleeper's API.

Adding a second ECS cluster in us-west-2 adds:
- $26–30/month in additional infrastructure
- A second ALB, second NAT Gateway, second ECS service
- Terraform complexity (multi-provider configs, Route 53 latency routing)
- The in-memory broadcaster problem becomes multi-region (needs Redis to share state)

**Decision: start in us-east-1. The Terraform modules use `var.region` everywhere so adding
us-west-2 later requires no structural changes — just a new environment directory and Route 53
latency routing records.**

---

## Decision 5: SES email for beta feedback (not a database)

Feedback persistence (DynamoDB) adds Terraform resources, IAM policies, and a read interface
you don't have time to build before beta. For a small group of friends, **email is sufficient** —
you'll read every submission personally anyway.

SES sends email from your verified domain. The `POST /api/v1/feedback` endpoint formats the
submission and calls `boto3.client('ses').send_email()`. No new AWS service beyond SES is needed,
and SES is free for the first 62,000 emails/month.

---

## AWS Architecture

```
Internet
   │
   ├── Route 53 — lineuplines.com (register + hosted zone)
   │       ├── A alias → CloudFront distribution
   │       └── www CNAME → CloudFront distribution
   │
   ├── ACM Certificate — lineuplines.com + www.lineuplines.com (DNS validated, us-east-1)
   │
   ├── CloudFront Distribution
   │       ├── Origin 1: S3 bucket (frontend) — default behavior /*
   │       │       └── OAC — bucket is private, only CloudFront can read it
   │       └── Origin 2: ALB (backend)         — behavior /api/*
   │               └── No caching, forward all headers, allow all methods
   │
   ├── ALB (Application Load Balancer)
   │       ├── HTTPS listener (port 443) → target group
   │       ├── HTTP listener (port 80) → redirect to HTTPS
   │       └── Target Group: ECS Fargate tasks
   │               ├── sticky sessions: enabled (LB cookie, 86400s duration)
   │               └── idle timeout: 3600s (for SSE connections)
   │
   ├── ECS Fargate
   │       ├── Cluster: lineuplines
   │       └── Service: lineuplines-api
   │               ├── Task: 0.5 vCPU, 1GB memory
   │               ├── Image: ECR → lineuplines-api:<sha>
   │               ├── Port: 8000
   │               └── Env vars: FRONTEND_URL, SES_FROM_EMAIL, SES_TO_EMAIL
   │
   ├── S3: lineuplines-frontend-prod     — static React build (private)
   ├── S3: lineuplines-player-data-prod  — ADP data files (private, ECS task role access)
   ├── ECR: lineuplines-api              — Docker images
   │
   └── SES: lineuplines.com domain identity
           └── IAM: ECS task role has ses:SendEmail permission
```

**VPC layout:**
- 1 VPC (`10.0.0.0/16`), 2 availability zones (us-east-1a, us-east-1b)
- 2 public subnets — ALB lives here
- 2 private subnets — ECS tasks live here (no public IP)
- 1 NAT Gateway (public subnet, us-east-1a) — ECS tasks route outbound traffic through it
  - *Single NAT GW saves ~$32/month vs. HA pair. Acceptable for beta.*

---

## Terraform Module Structure

```
infra/
  terraform/
    state_bootstrap/         # Run ONCE locally before anything else
      main.tf                #   Creates S3 bucket + DynamoDB table for remote state

    backend.tf               # Points Terraform at the S3 remote state bucket
    providers.tf             # AWS provider, region = var.region
    main.tf                  # Root: calls all modules, wires outputs → inputs
    variables.tf             # domain_name, ses_from_email, ses_to_email, region, etc.
    outputs.tf               # CloudFront URL, ALB DNS, ECR repo URL
    terraform.tfvars         # Your values (gitignored — never commit)
    terraform.tfvars.example # Template to copy from

    modules/
      networking/            # VPC, subnets, IGW, NAT GW, route tables, security groups
      registry/              # ECR repository + lifecycle policy (keep last 10 images)
      dns_tls/               # Route 53 hosted zone, ACM cert (DNS validated), A + CNAME records
      compute/               # ECS cluster, task def, Fargate service, ALB, GitHub OIDC IAM role
      cdn/                   # S3 frontend bucket + CloudFront distribution
      data_storage/          # S3 player-data bucket, read policy on ECS task role
      feedback/              # SES domain identity, DKIM records, send policy on ECS task role
```

---

## CI/CD — GitHub Actions

### Backend pipeline (`.github/workflows/backend.yml`)

Triggers: push to `main` affecting `src/**`, `tests/**`, `Dockerfile`, `requirements.txt`

```
1. Run pytest (fail if tests fail)
2. Configure AWS credentials via GitHub OIDC (no long-lived keys stored as secrets)
3. Build Docker image
4. Push to ECR tagged with git SHA + :latest
5. Register new ECS task definition revision with updated image tag
6. aws ecs update-service → rolling deploy
7. aws ecs wait services-stable → pipeline waits for completion
```

### Frontend pipeline (`.github/workflows/frontend.yml`)

Triggers: push to `main` affecting `frontend/**`

```
1. npm ci + npm run build
2. Configure AWS credentials via GitHub OIDC
3. aws s3 sync frontend/dist/ → S3 bucket (with correct cache-control headers)
4. aws cloudfront create-invalidation → cache busted within ~60s
```

### GitHub secrets to add

| Secret | Where to get it |
|--------|-----------------|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | `terraform output` → `github_actions_role_arn` (from compute module) |
| `ECR_REPOSITORY` | `terraform output` → `ecr_repository_url` |
| `ECS_CLUSTER` | `terraform output` → `ecs_cluster_name` |
| `ECS_SERVICE` | `terraform output` → `ecs_service_name` |
| `FRONTEND_S3_BUCKET` | `terraform output` → `frontend_bucket_name` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `terraform output` → `cloudfront_distribution_id` |

---

## Monthly Cost Estimate (beta scale, 1 ECS task)

| Service | ~Cost/month | Notes |
|---------|-------------|-------|
| ECS Fargate (0.5 vCPU, 1GB) | ~$15 | Running 24/7 |
| ALB | ~$16 | Fixed base cost regardless of traffic |
| NAT Gateway | ~$32 | Fixed + $0.045/GB data processed |
| S3 (frontend + data) | ~$1 | |
| CloudFront | ~$0 | Free tier: 1TB transfer + 10M requests/month |
| ECR | ~$0.10 | |
| Route 53 | ~$0.50/month + ~$13/yr domain | |
| SES | ~$0 | Free for <62k emails/month |
| **Total** | **~$65/month** | |

> ⚠️ **NAT Gateway is the surprise cost.** At $32/month it's the second biggest line item.
> Alternative: put ECS tasks in public subnets with a public IP (no NAT Gateway needed).
> Less secure but acceptable for beta — security groups still restrict inbound to ALB only.
> This drops the bill to ~$33/month. The Terraform uses private subnets (best practice) but
> you can change `assign_public_ip = true` and remove the NAT GW resources to save money.

---

## Scaling Limits & Upgrade Paths

| Current limit | Why acceptable for beta | Future fix |
|---------------|-------------------------|------------|
| In-memory `DraftBroadcaster` doesn't share state across ECS tasks | ALB sticky sessions pin each user to one task; 1 task is fine for friends | Replace `asyncio.Queue` with ElastiCache Redis Pub/Sub |
| `data/` ADP files baked into Docker image | Rebuild image on ADP refresh (~weekly) | Move `data/` to S3, load at container startup |
| Single NAT Gateway | Saves ~$32/month; ECS tasks lose outbound if that AZ goes down | Add second NAT GW in us-east-1b |
| No auto-scaling | 1 task handles all beta traffic | Add ECS Application Auto Scaling on CPU% |
| No database | Feedback via email only | DynamoDB for feedback; RDS when user accounts are needed |

---

## Step-by-Step Deployment Guide

> Run these steps in order. Each step depends on the previous one.

### Step 1: Bootstrap Terraform state (run once, locally)

```bash
cd infra/terraform/state_bootstrap
terraform init
terraform apply
# Note the output: state_bucket_name and dynamodb_table_name
```

### Step 2: Configure Terraform backend

Edit `infra/terraform/backend.tf` — replace `REPLACE_WITH_ACCOUNT_ID` with your AWS account ID
(shown in the step 1 output).

### Step 3: Create your tfvars file

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# Edit terraform.tfvars with your domain name and email addresses
```

### Step 4: Register your domain

Register `lineuplines.com` (or your chosen domain) through AWS Route 53 in the console, or
through another registrar. If using another registrar, you'll need to update nameservers after
step 5 completes.

### Step 5: Deploy all infrastructure

```bash
cd infra/terraform
terraform init
terraform apply
```

This takes ~10–15 minutes. ACM cert validation requires DNS propagation. If your domain was
registered outside Route 53, you'll see Terraform waiting on cert validation — update your
registrar's nameservers to the values from `terraform output route53_nameservers` and it will
proceed automatically.

### Step 6: Push your first Docker image

```bash
# Get the ECR URL
ECR_URL=$(terraform output -raw ecr_repository_url)

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin $ECR_URL

# Build and push
docker build -t $ECR_URL:latest .
docker push $ECR_URL:latest

# Force the ECS service to pick up the new image
aws ecs update-service \
  --cluster lineuplines \
  --service lineuplines-api \
  --force-new-deployment
```

### Step 7: Deploy the frontend

```bash
cd frontend
npm run build
aws s3 sync dist/ s3://$(cd ../infra/terraform && terraform output -raw frontend_bucket_name)/ --delete
```

### Step 8: Request SES production access

New AWS accounts are in SES sandbox mode — you can only send to verified email addresses.
Either:
- **Quick option**: Verify your personal email in SES console → it can receive feedback during beta
- **Proper option**: Submit an [AWS Support ticket](https://console.aws.amazon.com/support/) requesting "SES production access"

### Step 9: Add GitHub secrets

Get values from `terraform output` and add to your GitHub repo settings → Secrets and variables → Actions:

```bash
cd infra/terraform
terraform output  # shows all values you need
```

### Step 10: Verify

```bash
# Health check
curl -v https://lineuplines.com/health

# SSE stream (should see keepalive comments)
curl -N https://lineuplines.com/api/v1/drafts/test123/stream

# Submit feedback
curl -X POST https://lineuplines.com/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"message": "test feedback", "page": "/"}'
```

---

## Files Added/Modified by This Plan

| File | Change |
|------|--------|
| `Dockerfile` | Multi-stage build + HEALTHCHECK |
| `src/api/feedback.py` | **New** — SES feedback endpoint |
| `src/api/main.py` | Registers feedback router |
| `frontend/src/components/common/FeedbackWidget.jsx` | **New** — floating feedback button |
| `frontend/src/App.jsx` | Adds FeedbackWidget to layout |
| `infra/terraform/` | **New** — all Terraform modules |
| `.github/workflows/backend.yml` | **New** — backend CI/CD |
| `.github/workflows/frontend.yml` | **New** — frontend CI/CD |
| `.gitignore` | Terraform secrets excluded |
