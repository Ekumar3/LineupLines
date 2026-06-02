# deploy_frontend.ps1 — Build the React app, sync to S3, invalidate CloudFront cache.
#
# Usage:
#   .\scripts\deploy_frontend.ps1

$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────────────────
$REGION                    = "us-east-1"
$S3_BUCKET                 = "lineuplines-frontend-prod"
$CLOUDFRONT_DISTRIBUTION_ID = "E1MV0CAL2CVVA5"
# ─────────────────────────────────────────────────────────────────────────────

# Resolve repo root (script lives in scripts/, repo root is one level up)
$REPO_ROOT    = Split-Path -Parent $PSScriptRoot
$FRONTEND_DIR = Join-Path $REPO_ROOT "frontend"
$DIST_DIR     = Join-Path $FRONTEND_DIR "dist"

Write-Host ""
Write-Host "==> Installing dependencies..." -ForegroundColor Cyan
Push-Location $FRONTEND_DIR
try {
    npm ci

    Write-Host ""
    Write-Host "==> Building production bundle..." -ForegroundColor Cyan
    npm run build
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "==> Syncing dist/ to s3://$S3_BUCKET ..." -ForegroundColor Cyan
# Hashed assets (JS/CSS) get long cache; index.html gets no-cache so updates land immediately.
aws s3 sync $DIST_DIR "s3://$S3_BUCKET/" `
    --delete `
    --cache-control "public, max-age=31536000, immutable" `
    --region $REGION

aws s3 cp (Join-Path $DIST_DIR "index.html") "s3://$S3_BUCKET/index.html" `
    --cache-control "no-cache, no-store, must-revalidate" `
    --region $REGION

Write-Host ""
Write-Host "==> Invalidating CloudFront cache..." -ForegroundColor Cyan
$invalidation = aws cloudfront create-invalidation `
    --distribution-id $CLOUDFRONT_DISTRIBUTION_ID `
    --paths "/*" `
    --query "Invalidation.Id" `
    --output text

Write-Host ""
Write-Host "Frontend deployed. CloudFront invalidation: $invalidation" -ForegroundColor Green
Write-Host "Changes typically live within ~60 seconds." -ForegroundColor DarkGray
