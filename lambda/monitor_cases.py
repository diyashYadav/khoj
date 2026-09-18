import json
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

REGION = "ap-southeast-2"
MISSING_TABLE = "MissingCase"
MATCH_TABLE = "Match"
SEARCH_FUNCTION = "BharatTalaash-SearchText"
TOP_MATCHES_PER_CASE = 5

resource = boto3.resource("dynamodb", region_name=REGION)
missing_table = resource.Table(MISSING_TABLE)
match_table = resource.Table(MATCH_TABLE)
lambda_client = boto3.client("lambda", region_name=REGION)

def decimalize(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [decimalize(x) for x in value]
    if isinstance(value, dict):
        return {k: decimalize(v) for k, v in value.items()}
    return value

def active_cases():
    items = []
    kwargs = {"FilterExpression": Attr("status").eq("active")}
    while True:
        response = missing_table.scan(**kwargs)
        items.extend(response.get("Items", []))
        key = response.get("LastEvaluatedKey")
        if not key:
            break
        kwargs["ExclusiveStartKey"] = key
    return items

def case_to_text(case):
    fields = [
        ("name", "Name"),
        ("age", "Age"),
        ("gender", "Gender"),
        ("last_seen_location", "Last seen location"),
        ("last_seen_date", "Last seen date"),
        ("clothing", "Clothing"),
        ("description", "Description"),
        ("distinctive_marks", "Distinctive marks"),
    ]
    parts = []
    for key, label in fields:
        value = case.get(key)
        if value not in (None, "", [], {}):
            parts.append(f"{label}: {value}")
    return ". ".join(parts)

def search_case(case):
    text = case_to_text(case)
    response = lambda_client.invoke(
        FunctionName=SEARCH_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps({"input_type": "text", "text": text}).encode("utf-8"),
    )
    outer = json.loads(response["Payload"].read())
    if int(outer.get("statusCode", 500)) != 200:
        raise RuntimeError(outer.get("body", "Search failed"))
    body = outer.get("body", "{}")
    return json.loads(body) if isinstance(body, str) else body

def save_matches(case_id, result):
    matches = result.get("matching", {}).get("matches", [])[:TOP_MATCHES_PER_CASE]
    saved = 0
    for match in matches:
        candidate = match.get("candidate", {})
        found_id = candidate.get("found_id")
        if not found_id:
            continue
        item = {
            "match_id": str(uuid.uuid4()),
            "case_id": case_id,
            "found_id": found_id,
            "final_score": match.get("final_score"),
            "semantic_score": match.get("semantic_score"),
            "structured_score": match.get("structured_score"),
            "structured_details": match.get("structured_details", {}),
            "candidate": candidate,
            "verification_status": "pending",
            "created_at": int(time.time()),
        }
        match_table.put_item(Item=decimalize(item))
        saved += 1
    return saved

def lambda_handler(event, context):
    cases = active_cases()
    completed = 0
    failed = 0
    matches_saved = 0
    for case in cases:
        try:
            result = search_case(case)
            matches_saved += save_matches(case["case_id"], result)
            missing_table.update_item(
                Key={"case_id": case["case_id"]},
                UpdateExpression="SET last_checked_at = :t",
                ExpressionAttributeValues={":t": int(time.time())},
            )
            completed += 1
        except Exception as exc:
            print("Monitor failure:", case.get("case_id"), repr(exc))
            failed += 1
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": "completed",
                "cases_seen": len(cases),
                "completed": completed,
                "failed": failed,
                "matches_saved": matches_saved,
            }
        ),
    }
