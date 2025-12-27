# ============================================================
# AWS Agri Chatbot - Direct AWS CLI Deployment
# ============================================================

param(
    [string]$Stage = "prod",
    [string]$Region = "ap-southeast-2"
)

$ErrorActionPreference = "Stop"
$StackName = "agri-chatbot-$Stage"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Agricultural Price Chatbot Deployment" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Get AWS Account ID
$AccountId = (aws sts get-caller-identity --query Account --output text)
Write-Host "AWS Account: $AccountId" -ForegroundColor Green
Write-Host "Region: $Region" -ForegroundColor Green
Write-Host "Stack: $StackName" -ForegroundColor Green
Write-Host ""

# ============================================================
# 1. Create S3 Bucket for Frontend
# ============================================================
Write-Host "[1/5] Creating S3 bucket for frontend..." -ForegroundColor Cyan

$BucketName = "agri-chatbot-frontend-$AccountId-$Stage"

# Check if bucket exists
$BucketExists = aws s3api head-bucket --bucket $BucketName 2>&1
if ($LASTEXITCODE -ne 0) {
    aws s3api create-bucket `
        --bucket $BucketName `
        --region $Region `
        --create-bucket-configuration LocationConstraint=$Region

    # Enable static website hosting
    aws s3 website "s3://$BucketName" --index-document index.html --error-document index.html

    # Set bucket policy for public access
    $Policy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::$BucketName/*"
        }
    ]
}
"@
    $Policy | Out-File -FilePath "bucket-policy.json" -Encoding utf8

    # Disable block public access
    aws s3api put-public-access-block `
        --bucket $BucketName `
        --public-access-block-configuration "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"

    Start-Sleep -Seconds 2

    aws s3api put-bucket-policy --bucket $BucketName --policy file://bucket-policy.json
    Remove-Item "bucket-policy.json"

    Write-Host "  Bucket created: $BucketName" -ForegroundColor Green
} else {
    Write-Host "  Bucket exists: $BucketName" -ForegroundColor Yellow
}

# ============================================================
# 2. Create Lambda Function
# ============================================================
Write-Host "[2/5] Creating Lambda function..." -ForegroundColor Cyan

$FunctionName = "agri-bedrock-chat-$Stage"
$RoleName = "agri-chatbot-lambda-role-$Stage"

# Create IAM Role if not exists
$RoleExists = aws iam get-role --role-name $RoleName 2>&1
if ($LASTEXITCODE -ne 0) {
    $TrustPolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }
    ]
}
"@
    $TrustPolicy | Out-File -FilePath "trust-policy.json" -Encoding utf8

    aws iam create-role `
        --role-name $RoleName `
        --assume-role-policy-document file://trust-policy.json

    # Attach policies
    aws iam attach-role-policy `
        --role-name $RoleName `
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

    # Create Bedrock policy
    $BedrockPolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel"],
            "Resource": "*"
        }
    ]
}
"@
    $BedrockPolicy | Out-File -FilePath "bedrock-policy.json" -Encoding utf8

    aws iam put-role-policy `
        --role-name $RoleName `
        --policy-name BedrockAccess `
        --policy-document file://bedrock-policy.json

    Remove-Item "trust-policy.json"
    Remove-Item "bedrock-policy.json"

    Write-Host "  Role created: $RoleName" -ForegroundColor Green
    Write-Host "  Waiting for role propagation..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
} else {
    Write-Host "  Role exists: $RoleName" -ForegroundColor Yellow
}

$RoleArn = (aws iam get-role --role-name $RoleName --query "Role.Arn" --output text)

# Create deployment package
Write-Host "  Creating deployment package..." -ForegroundColor Yellow

$DeployDir = ".\lambda_deploy"
if (Test-Path $DeployDir) { Remove-Item $DeployDir -Recurse -Force }
New-Item -ItemType Directory -Path $DeployDir | Out-Null

# Copy source files
Copy-Item -Path ".\src" -Destination "$DeployDir\src" -Recurse
Copy-Item -Path ".\data" -Destination "$DeployDir\data" -Recurse
Copy-Item -Path ".\lambdas\agri_api\app.py" -Destination "$DeployDir\app.py"

# Install dependencies
pip install boto3 pandas pydantic python-dateutil -t $DeployDir -q 2>&1 | Out-Null

# Create ZIP
$ZipFile = ".\lambda_package.zip"
if (Test-Path $ZipFile) { Remove-Item $ZipFile }
Compress-Archive -Path "$DeployDir\*" -DestinationPath $ZipFile

Write-Host "  Package created: $ZipFile" -ForegroundColor Green

# Create or update Lambda function
$FunctionExists = aws lambda get-function --function-name $FunctionName --region $Region 2>&1
if ($LASTEXITCODE -ne 0) {
    aws lambda create-function `
        --function-name $FunctionName `
        --runtime python3.10 `
        --role $RoleArn `
        --handler app.handler `
        --zip-file fileb://$ZipFile `
        --timeout 30 `
        --memory-size 512 `
        --region $Region `
        --environment "Variables={DATA_PATH=/var/task/data/sample_agri_prices.csv,BEDROCK_MODEL_ID=amazon.titan-text-express-v1,AWS_REGION_NAME=$Region}"

    Write-Host "  Lambda created: $FunctionName" -ForegroundColor Green
} else {
    aws lambda update-function-code `
        --function-name $FunctionName `
        --zip-file fileb://$ZipFile `
        --region $Region | Out-Null

    Write-Host "  Lambda updated: $FunctionName" -ForegroundColor Green
}

# Cleanup
Remove-Item $DeployDir -Recurse -Force
Remove-Item $ZipFile

# ============================================================
# 3. Create API Gateway
# ============================================================
Write-Host "[3/5] Creating API Gateway..." -ForegroundColor Cyan

$ApiName = "agri-chatbot-api-$Stage"

# Check if API exists
$ApiId = (aws apigatewayv2 get-apis --region $Region --query "Items[?Name=='$ApiName'].ApiId" --output text)

if (-not $ApiId) {
    $ApiResult = aws apigatewayv2 create-api `
        --name $ApiName `
        --protocol-type HTTP `
        --cors-configuration "AllowOrigins=*,AllowMethods=POST,OPTIONS,GET,AllowHeaders=content-type" `
        --region $Region `
        --output json | ConvertFrom-Json

    $ApiId = $ApiResult.ApiId
    Write-Host "  API created: $ApiId" -ForegroundColor Green
} else {
    Write-Host "  API exists: $ApiId" -ForegroundColor Yellow
}

# Create Lambda integration
$LambdaArn = "arn:aws:lambda:${Region}:${AccountId}:function:${FunctionName}"

$IntegrationId = (aws apigatewayv2 get-integrations --api-id $ApiId --region $Region --query "Items[?IntegrationUri=='$LambdaArn'].IntegrationId" --output text)

if (-not $IntegrationId) {
    $IntResult = aws apigatewayv2 create-integration `
        --api-id $ApiId `
        --integration-type AWS_PROXY `
        --integration-uri $LambdaArn `
        --payload-format-version "2.0" `
        --region $Region `
        --output json | ConvertFrom-Json

    $IntegrationId = $IntResult.IntegrationId
    Write-Host "  Integration created: $IntegrationId" -ForegroundColor Green
} else {
    Write-Host "  Integration exists: $IntegrationId" -ForegroundColor Yellow
}

# Create routes
$Routes = @("POST /api/query", "OPTIONS /api/query", "GET /api/health", "GET /api/dimensions")
foreach ($RouteKey in $Routes) {
    $RouteExists = (aws apigatewayv2 get-routes --api-id $ApiId --region $Region --query "Items[?RouteKey=='$RouteKey'].RouteId" --output text)
    if (-not $RouteExists) {
        aws apigatewayv2 create-route `
            --api-id $ApiId `
            --route-key $RouteKey `
            --target "integrations/$IntegrationId" `
            --region $Region | Out-Null
        Write-Host "  Route created: $RouteKey" -ForegroundColor Green
    }
}

# Create stage
$StageExists = (aws apigatewayv2 get-stages --api-id $ApiId --region $Region --query "Items[?StageName=='$Stage'].StageName" --output text)
if (-not $StageExists) {
    aws apigatewayv2 create-stage `
        --api-id $ApiId `
        --stage-name $Stage `
        --auto-deploy `
        --region $Region | Out-Null
    Write-Host "  Stage created: $Stage" -ForegroundColor Green
}

# Add Lambda permission for API Gateway
aws lambda add-permission `
    --function-name $FunctionName `
    --statement-id "apigateway-$ApiId" `
    --action lambda:InvokeFunction `
    --principal apigateway.amazonaws.com `
    --source-arn "arn:aws:execute-api:${Region}:${AccountId}:${ApiId}/*/*" `
    --region $Region 2>&1 | Out-Null

$ApiUrl = "https://$ApiId.execute-api.$Region.amazonaws.com/$Stage"
Write-Host "  API URL: $ApiUrl" -ForegroundColor Green

# ============================================================
# 4. Update Frontend with API URL
# ============================================================
Write-Host "[4/5] Updating frontend with API URL..." -ForegroundColor Cyan

$HtmlContent = Get-Content -Path "frontend/index.html" -Raw -Encoding utf8
$HtmlContent = $HtmlContent -replace "const API_ENDPOINT = window.API_ENDPOINT \|\| '/api/query';", "const API_ENDPOINT = '$ApiUrl/api/query';"
Set-Content -Path "frontend/index.html" -Value $HtmlContent -Encoding utf8

Write-Host "  Frontend updated with API endpoint" -ForegroundColor Green

# ============================================================
# 5. Upload Frontend to S3
# ============================================================
Write-Host "[5/5] Uploading frontend to S3..." -ForegroundColor Cyan

aws s3 sync frontend/ "s3://$BucketName/" `
    --region $Region `
    --delete

aws s3 cp "s3://$BucketName/index.html" "s3://$BucketName/index.html" `
    --region $Region `
    --content-type "text/html; charset=utf-8" `
    --metadata-directive REPLACE

Write-Host "  Frontend uploaded!" -ForegroundColor Green

# ============================================================
# Done!
# ============================================================
$S3Url = "http://$BucketName.s3-website-$Region.amazonaws.com"

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Deployment Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Access your chatbot at:" -ForegroundColor Cyan
Write-Host "  $S3Url" -ForegroundColor Yellow
Write-Host ""
Write-Host "API Endpoint:" -ForegroundColor Cyan
Write-Host "  $ApiUrl/api/query" -ForegroundColor Yellow
Write-Host ""

# Restore original frontend
$HtmlContent = $HtmlContent -replace "const API_ENDPOINT = '$ApiUrl/api/query';", "const API_ENDPOINT = window.API_ENDPOINT || '/api/query';"
Set-Content -Path "frontend/index.html" -Value $HtmlContent -Encoding utf8
