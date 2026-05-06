# deploy_backend.ps1 — Build and push the backend Docker image to ECR, then deploy to ECS.
#
# Usage:
#   .\scripts\deploy_backend.ps1           # Build, push, deploy (no wait)
#   .\scripts\deploy_backend.ps1 -Wait     # Build, push, deploy, then wait for stable

param(
    [switch]$Wait
)

$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────────────────
$REGION      = "us-east-1"
$ECR_URL     = "942663256500.dkr.ecr.us-east-1.amazonaws.com/lineuplines-api"
$ECS_CLUSTER = "lineuplines"
$ECS_SERVICE = "lineuplines-api"
# ─────────────────────────────────────────────────────────────────────────────

# Resolve repo root (script lives in scripts/, repo root is one level up)
$REPO_ROOT = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "==> Logging in to ECR..." -ForegroundColor Cyan
$token = aws ecr get-login-password --region $REGION
docker login --username AWS --password $token ($ECR_URL -split "/" | Select-Object -First 1)

# Tag with git SHA + latest
$GIT_SHA = git -C $REPO_ROOT rev-parse --short HEAD
$IMAGE_SHA    = "${ECR_URL}:${GIT_SHA}"
$IMAGE_LATEST = "${ECR_URL}:latest"

Write-Host ""
Write-Host "==> Building image (git SHA: $GIT_SHA)..." -ForegroundColor Cyan
docker build -t $IMAGE_SHA -t $IMAGE_LATEST $REPO_ROOT

Write-Host ""
Write-Host "==> Pushing $IMAGE_SHA ..." -ForegroundColor Cyan
docker push $IMAGE_SHA

Write-Host "==> Pushing $IMAGE_LATEST ..." -ForegroundColor Cyan
docker push $IMAGE_LATEST

Write-Host ""
Write-Host "==> Triggering ECS rolling deploy..." -ForegroundColor Cyan
aws ecs update-service `
    --cluster $ECS_CLUSTER `
    --service $ECS_SERVICE `
    --force-new-deployment `
    --region $REGION | Out-Null

Write-Host "Deploy triggered. New task is starting with image: $GIT_SHA" -ForegroundColor Green

if ($Wait) {
    Write-Host ""
    Write-Host "==> Waiting for service to stabilize (this takes ~2-3 min)..." -ForegroundColor Cyan
    aws ecs wait services-stable `
        --cluster $ECS_CLUSTER `
        --services $ECS_SERVICE `
        --region $REGION
    Write-Host "Service is stable. Deploy complete." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Tip: run with -Wait to block until the new task is healthy." -ForegroundColor DarkGray
}
