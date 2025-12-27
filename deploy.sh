#!/bin/bash
# ============================================================
# AWS Agri Chatbot Deployment Script (Bash)
# ============================================================

set -e

STAGE="${1:-prod}"
REGION="${2:-ap-southeast-2}"
STACK_NAME="agri-chatbot-$STAGE"

echo "============================================"
echo "  Agricultural Price Chatbot Deployment"
echo "============================================"
echo ""
echo "Stage: $STAGE"
echo "Region: $REGION"
echo ""

# Get AWS Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "AWS Account ID: $ACCOUNT_ID"

# ============================================================
# 1. Build SAM Application
# ============================================================
echo ""
echo "[1/4] Building SAM application..."

sam build --template template.yaml --region $REGION

echo "Build completed!"

# ============================================================
# 2. Deploy SAM Stack
# ============================================================
echo ""
echo "[2/4] Deploying SAM stack..."

sam deploy \
    --template-file .aws-sam/build/template.yaml \
    --stack-name $STACK_NAME \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --parameter-overrides Stage=$STAGE \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset

echo "Stack deployed!"

# ============================================================
# 3. Get Stack Outputs
# ============================================================
echo ""
echo "[3/4] Getting stack outputs..."

FRONTEND_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
    --output text)

CLOUDFRONT_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontURL'].OutputValue" \
    --output text)

API_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query "Stacks[0].Outputs[?OutputKey=='ApiGatewayURL'].OutputValue" \
    --output text)

echo "Frontend Bucket: $FRONTEND_BUCKET"
echo "CloudFront URL: $CLOUDFRONT_URL"
echo "API Gateway URL: $API_URL"

# ============================================================
# 4. Deploy Frontend to S3
# ============================================================
echo ""
echo "[4/4] Deploying frontend to S3..."

# Upload to S3
aws s3 sync frontend/ "s3://$FRONTEND_BUCKET/" \
    --region $REGION \
    --delete \
    --cache-control "max-age=31536000"

# Set correct content type for HTML
aws s3 cp "s3://$FRONTEND_BUCKET/index.html" "s3://$FRONTEND_BUCKET/index.html" \
    --region $REGION \
    --content-type "text/html; charset=utf-8" \
    --cache-control "no-cache" \
    --metadata-directive REPLACE

echo "Frontend deployed!"

# ============================================================
# Invalidate CloudFront Cache
# ============================================================
echo ""
echo "Invalidating CloudFront cache..."

DISTRIBUTION_ID=$(aws cloudformation describe-stack-resource \
    --stack-name $STACK_NAME \
    --logical-resource-id CloudFrontDistribution \
    --region $REGION \
    --query "StackResourceDetail.PhysicalResourceId" \
    --output text)

aws cloudfront create-invalidation \
    --distribution-id $DISTRIBUTION_ID \
    --paths "/*" > /dev/null

echo "Cache invalidation started!"

# ============================================================
# Done!
# ============================================================
echo ""
echo "============================================"
echo "  Deployment Complete!"
echo "============================================"
echo ""
echo "Access your chatbot at:"
echo "$CLOUDFRONT_URL"
echo ""
echo "API Endpoint:"
echo "$API_URL"
echo ""
