zip -r lambda.zip backend/lambda
aws lambda update-function-code \
  --function-name agri-llm-lambda \
  --zip-file fileb://lambda.zip