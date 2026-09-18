






import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

dynamodb = boto3.resource("dynamodb")

DEFAULT_RECHECK_FREQUENCY_HOURS = 60  


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def convert_floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [convert_floats_to_decimal(x) for x in obj]
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    return obj


def convert_decimals_to_native(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, list):
        return [convert_decimals_to_native(x) for x in obj]
    if isinstance(obj, dict):
        return {k: convert_decimals_to_native(v) for k, v in obj.items()}
    return obj


def _clean_item(item: dict) -> dict:

    cleaned = {k: v for k, v in item.items() if v is not None}
    return convert_floats_to_decimal(cleaned)






def get_or_create_user(user_id: str, email: str, name: str = None) -> dict:
    table = dynamodb.Table("User")
    existing = table.get_item(Key={"user_id": user_id}).get("Item")
    if existing:
        return convert_decimals_to_native(existing)

    item = _clean_item({"user_id": user_id, "email": email, "name": name, "created_at": now_iso()})
    table.put_item(Item=item)
    return convert_decimals_to_native(item)


def get_user_email(user_id: str) -> str | None:
    if not user_id:
        return None
    table = dynamodb.Table("User")
    item = table.get_item(Key={"user_id": user_id}).get("Item")
    return item["email"] if item else None






def create_missing_case(fields: dict, reporter_user_id: str = None, source: str = "user_submitted") -> str:
    case_id = fields.get("case_id") or str(uuid.uuid4())
    item = {
        "case_id": case_id,
        "reporter_user_id": reporter_user_id,
        "source": source,
        "status": "PENDING_SEARCH",
        "created_at": now_iso(),
        "last_checked_at": None,
        "next_check_at": now_iso(),  
        **{k: v for k, v in fields.items() if k != "case_id"},
    }
    dynamodb.Table("MissingCase").put_item(Item=_clean_item(item))
    return case_id


def get_missing_case(case_id: str) -> dict | None:
    item = dynamodb.Table("MissingCase").get_item(Key={"case_id": case_id}).get("Item")
    return convert_decimals_to_native(item) if item else None


def get_active_cases_due_for_recheck(limit: int = 100) -> list:
    table = dynamodb.Table("MissingCase")
    response = table.query(
        IndexName="status-nextCheckAt-index",
        KeyConditionExpression=Key("status").eq("ACTIVE") & Key("next_check_at").lte(now_iso()),
        Limit=limit,
    )
    return [convert_decimals_to_native(i) for i in response.get("Items", [])]


def update_case_after_check(case_id: str, found_strong_match: bool,
                             frequency_hours: int = DEFAULT_RECHECK_FREQUENCY_HOURS) -> None:
    next_check = (datetime.utcnow() + timedelta(hours=frequency_hours)).isoformat()
    dynamodb.Table("MissingCase").update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET last_checked_at = :now, next_check_at = :next, "
                          "#s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":now": now_iso(),
            ":next": next_check,
            ":status": "MATCH_FOUND" if found_strong_match else "ACTIVE",
        },
    )






def create_found_report(fields: dict, reporter_user_id: str = None,
                         source: str = "user_submitted", record_subtype: str = "living") -> str:
    found_id = fields.get("found_id") or f"USER-{uuid.uuid4()}"
    item = {
        "found_id": found_id,
        "reporter_user_id": reporter_user_id,
        "source": source,
        "record_subtype": record_subtype,
        "created_at": now_iso(),
        "last_updated_at": now_iso(),
        **{k: v for k, v in fields.items() if k != "found_id"},
    }
    dynamodb.Table("FoundReport").put_item(Item=_clean_item(item))
    return found_id


def get_found_reports_updated_since(since_iso: str, max_items: int = 2000) -> list:

    table = dynamodb.Table("FoundReport")
    candidates = []
    scan_kwargs = {"FilterExpression": Attr("last_updated_at").gte(since_iso)}
    while True:
        response = table.scan(**scan_kwargs)
        candidates.extend(convert_decimals_to_native(i) for i in response.get("Items", []))
        if "LastEvaluatedKey" not in response or len(candidates) >= max_items:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return candidates[:max_items]


def get_all_active_missing_cases(max_items: int = 5000) -> list:

    table = dynamodb.Table("MissingCase")
    cases = []
    query_kwargs = {"IndexName": "status-nextCheckAt-index", "KeyConditionExpression": Key("status").eq("ACTIVE")}
    while True:
        response = table.query(**query_kwargs)
        cases.extend(convert_decimals_to_native(i) for i in response.get("Items", []))
        if "LastEvaluatedKey" not in response or len(cases) >= max_items:
            break
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return cases[:max_items]






def create_match(case_id: str, found_id: str, overall_score: float, field_scores: dict) -> str:
    match_id = str(uuid.uuid4())
    item = {
        "match_id": match_id,
        "case_id": case_id,
        "found_id": found_id,
        "overall_score": overall_score,
        "field_scores": field_scores,
        "verification_status": "PENDING",
        "created_at": now_iso(),
        "notified_at": None,
    }
    dynamodb.Table("Match").put_item(Item=_clean_item(item))
    return match_id


def mark_match_notified(match_id: str) -> None:
    dynamodb.Table("Match").update_item(
        Key={"match_id": match_id},
        UpdateExpression="SET notified_at = :now",
        ExpressionAttributeValues={":now": now_iso()},
    )


def match_already_exists(case_id: str, found_id: str) -> bool:

    table = dynamodb.Table("Match")
    response = table.query(
        IndexName="case_id-index",
        KeyConditionExpression=Key("case_id").eq(case_id),
        FilterExpression=Attr("found_id").eq(found_id),
    )
    return len(response.get("Items", [])) > 0






def get_sources_due_for_sync() -> list:
    table = dynamodb.Table("SourceSyncStatus")
    response = table.scan(FilterExpression=Attr("next_sync_due_at").lte(now_iso()))
    return [convert_decimals_to_native(i) for i in response.get("Items", [])]


def update_sync_status(source_name: str, record_count: int, frequency_hours: int = 60,
                        status: str = "OK", error: str = None) -> None:
    next_due = (datetime.utcnow() + timedelta(hours=frequency_hours)).isoformat()
    item = {
        "source_name": source_name,
        "last_synced_at": now_iso(),
        "last_record_count": record_count,
        "sync_frequency_hours": frequency_hours,
        "next_sync_due_at": next_due,
        "status": status,
        "last_error": error,
    }
    dynamodb.Table("SourceSyncStatus").put_item(Item=_clean_item(item))
