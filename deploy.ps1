# ============================================================
# AWS Agri Chatbot Deployment Script (PowerShell)
# ============================================================

param(
    [string]$Stage = "prod",
    [string]$Region = "ap-southeast-2",
    [switch]$SkipBuild,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Agricultural Price Chatbot Deployment" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Stage: $Stage" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host ""

# Get AWS Account ID
$AccountId = (aws sts get-caller-identity --query Account --output text)
Write-Host "AWS Account ID: $AccountId" -ForegroundColor Green

# Stack Name
$StackName = "agri-chatbot-$Stage"

# ============================================================
# 1. Build SAM Application
# ============================================================
if (-not $SkipBuild -and -not $FrontendOnly) {
    Write-Host ""
    Write-Host "[1/4] Building SAM application..." -ForegroundColor Cyan

    sam build --template template.yaml --region $Region

    if ($LASTEXITCODE -ne 0) {
        Write-Host "SAM build failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "Build completed!" -ForegroundColor Green
}

# ============================================================
# 2. Deploy SAM Stack
# ============================================================
if (-not $FrontendOnly) {
    Write-Host ""
    Write-Host "[2/4] Deploying SAM stack..." -ForegroundColor Cyan

    sam deploy `
        --template-file .aws-sam/build/template.yaml `
        --stack-name $StackName `
        --capabilities CAPABILITY_IAM `
        --region $Region `
        --parameter-overrides Stage=$Stage `
        --no-confirm-changeset `
        --no-fail-on-empty-changeset

    if ($LASTEXITCODE -ne 0) {
        Write-Host "SAM deploy failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "Stack deployed!" -ForegroundColor Green
}

# ============================================================
# 3. Get Stack Outputs
# ============================================================
Write-Host ""
Write-Host "[3/4] Getting stack outputs..." -ForegroundColor Cyan

$Outputs = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query "Stacks[0].Outputs" `
    --output json | ConvertFrom-Json

$FrontendBucketName = ($Outputs | Where-Object { $_.OutputKey -eq "FrontendBucketName" }).OutputValue
$CloudFrontURL = ($Outputs | Where-Object { $_.OutputKey -eq "CloudFrontURL" }).OutputValue
$ApiGatewayURL = ($Outputs | Where-Object { $_.OutputKey -eq "ApiGatewayURL" }).OutputValue

Write-Host "Frontend Bucket: $FrontendBucketName" -ForegroundColor Yellow
Write-Host "CloudFront URL: $CloudFrontURL" -ForegroundColor Yellow
Write-Host "API Gateway URL: $ApiGatewayURL" -ForegroundColor Yellow

# ============================================================
# 4. Deploy Frontend to S3
# ============================================================
Write-Host ""
Write-Host "[4/4] Deploying frontend to S3..." -ForegroundColor Cyan

# Update API endpoint in HTML
$HtmlContent = Get-Content -Path "frontend/index.html" -Raw
$HtmlContent = $HtmlContent -replace "const API_ENDPOINT = window.API_ENDPOINT \|\| '/api/query';", "const API_ENDPOINT = '/api/query';"
Set-Content -Path "frontend/index.html" -Value $HtmlContent

# Upload to S3
aws s3 sync frontend/ "s3://$FrontendBucketName/" `
    --region $Region `
    --delete `
    --cache-control "max-age=31536000"

# Set correct content types
aws s3 cp "s3://$FrontendBucketName/index.html" "s3://$FrontendBucketName/index.html" `
    --region $Region `
    --content-type "text/html; charset=utf-8" `
    --cache-control "no-cache" `
    --metadata-directive REPLACE

if ($LASTEXITCODE -ne 0) {
    Write-Host "Frontend deployment failed!" -ForegroundColor Red
    exit 1
}
Write-Host "Frontend deployed!" -ForegroundColor Green

# ============================================================
# Invalidate CloudFront Cache
# ============================================================
Write-Host ""
Write-Host "Invalidating CloudFront cache..." -ForegroundColor Cyan

$DistributionId = aws cloudformation describe-stack-resource `
    --stack-name $StackName `
    --logical-resource-id CloudFrontDistribution `
    --region $Region `
    --query "StackResourceDetail.PhysicalResourceId" `
    --output text

aws cloudfront create-invalidation `
    --distribution-id $DistributionId `
    --paths "/*" | Out-Null

Write-Host "Cache invalidation started!" -ForegroundColor Green

# ============================================================
# Done!
# ============================================================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Deployment Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Access your chatbot at:" -ForegroundColor Cyan
Write-Host "$CloudFrontURL" -ForegroundColor Yellow
Write-Host ""
Write-Host "API Endpoint:" -ForegroundColor Cyan
Write-Host "$ApiGatewayURL" -ForegroundColor Yellow
Write-Host ""
