



















import boto3
from boto3.dynamodb.conditions import Attr
from boto3.dynamodb.types import TypeDeserializer

from db_helpers import (
    convert_decimals_to_native,
    create_match,
    get_all_active_missing_cases,
    get_user_email,
    match_already_exists,
)
from matching_engine import rank_candidates
from notify import send_match_notification

MATCH_THRESHOLD = 60  
SAMPLE_SIZE = 100

_deserializer = TypeDeserializer()


def _deserialize_stream_image(image: dict) -> dict:
    return {k: _deserializer.deserialize(v) for k, v in image.items()}


def _get_comparison_pool(found_report: dict, sample_size: int = SAMPLE_SIZE) -> list:
    table = boto3.resource("dynamodb").Table("FoundReport")
    scan_kwargs = {"Limit": sample_size}
    if found_report.get("gender"):
        scan_kwargs["FilterExpression"] = Attr("gender").eq(found_report["gender"])
    response = table.scan(**scan_kwargs)
    pool = [convert_decimals_to_native(i) for i in response.get("Items", [])]
    if not any(p.get("found_id") == found_report.get("found_id") for p in pool):
        pool.append(found_report)
    return pool


def lambda_handler(event, context):
    active_cases = None
    pool_cache = {}  

    for record in event.get("Records", []):
        if record.get("eventName") != "INSERT":
            continue  

        new_image = record["dynamodb"].get("NewImage")
        if not new_image:
            continue

        found_report = convert_decimals_to_native(_deserialize_stream_image(new_image))
        found_id = found_report.get("found_id")
        print(f"New found report: {found_id} — checking against active missing cases...")

        if active_cases is None:
            active_cases = get_all_active_missing_cases()
        if not active_cases:
            print("No active missing cases to check against.")
            continue

        gender_key = found_report.get("gender", "_any")
        if gender_key not in pool_cache:
            pool_cache[gender_key] = _get_comparison_pool(found_report)
        pool = pool_cache[gender_key]

        for case in active_cases:
            if match_already_exists(case["case_id"], found_id):
                continue

            results = rank_candidates(case, pool)
            top = next((r for r in results if r["candidate"].get("found_id") == found_id), None)
            if not top or top["match_score"] < MATCH_THRESHOLD:
                continue

            match_id = create_match(case["case_id"], found_id, top["match_score"], top["breakdown"])
            print(f"Match created ({match_id}): case {case['case_id']} <-> {found_id} "
                  f"at {top['match_score']}%")

            reporter_email = get_user_email(case.get("reporter_user_id"))
            if reporter_email:
                send_match_notification(reporter_email, case["case_id"], found_id, top["match_score"])

    return {"statusCode": 200}
