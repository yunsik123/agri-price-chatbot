import json
import boto3
import os

from prompt import SYSTEM_PROMPT

bedrock = boto3.client("bedrock-runtime")

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-sonnet-20240229-v1:0"
)

def handler(event, context):
    body = json.loads(event.get("body", "{}"))
    question = body.get("question", "")
    rows = body.get("rows", [])

    prompt = f"""
Question: {question}

Data:
{rows}

Please provide a concise analysis.
"""

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "temperature": 0.2,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }),
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"analysis": text})
    }