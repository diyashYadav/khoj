import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

REGION = "ap-southeast-2"
TABLE = "MissingCase"
ALLOWED_ORIGIN = "https://updated-frontend.duo3mqhyrqgnv.amplifyapp.com"

table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

def normalize_event(event):
    if not isinstance(event, dict):
        return {}
    body = event.get("body", event)
    if isinstance(body, str):
        return json.loads(body or "{}")
    return body if isinstance(body, dict) else {}

def to_decimal(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [to_decimal(x) for x in value]
    if isinstance(value, dict):
        return {k: to_decimal(v) for k, v in value.items()}
    return value

def response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(payload),
    }

def lambda_handler(event, context):
    try:
        data = normalize_event(event)
    except Exception as exc:
        return response(400, {"error": "Invalid JSON", "detail": str(exc)})
    if not data:
        return response(400, {"error": "Missing case data is required"})
    case_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    item = {
        **data,
        "case_id": case_id,
        "created_at": created_at,
        "status": "active",
    }
    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=to_decimal(item))
    return response(
        201,
        {
            "message": "Missing case created",
            "case_id": case_id,
            "status": "active",
        },
    )
