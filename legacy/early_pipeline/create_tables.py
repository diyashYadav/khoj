











import time

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.client("dynamodb")


def table_exists(table_name: str) -> bool:
    try:
        dynamodb.describe_table(TableName=table_name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def wait_for_active(table_name: str) -> None:
    print(f"  Waiting for {table_name} to become ACTIVE...")
    dynamodb.get_waiter("table_exists").wait(TableName=table_name)


def wait_for_gsi_active(table_name: str, index_name: str) -> None:
    print(f"  Waiting for index {index_name} on {table_name} to backfill (can take a few minutes)...")
    while True:
        desc = dynamodb.describe_table(TableName=table_name)["Table"]
        gsis = {g["IndexName"]: g["IndexStatus"] for g in desc.get("GlobalSecondaryIndexes", [])}
        if gsis.get(index_name) == "ACTIVE":
            print(f"  {index_name} is ACTIVE.")
            return
        time.sleep(10)


def create_simple_table(table_name: str, pk_name: str) -> None:
    if table_exists(table_name):
        print(f"{table_name} already exists — skipping creation.")
        return
    print(f"Creating {table_name}...")
    dynamodb.create_table(
        TableName=table_name,
        AttributeDefinitions=[{"AttributeName": pk_name, "AttributeType": "S"}],
        KeySchema=[{"AttributeName": pk_name, "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    wait_for_active(table_name)
    print(f"{table_name} created.\n")


def create_missing_case_table() -> None:
    table_name = "MissingCase"
    if table_exists(table_name):
        print(f"{table_name} already exists — skipping creation.")
        return
    print(f"Creating {table_name} with GSIs...")
    dynamodb.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": "case_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "next_check_at", "AttributeType": "S"},
            {"AttributeName": "reporter_user_id", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "status-nextCheckAt-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "next_check_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "reporter_user_id-index",
                "KeySchema": [{"AttributeName": "reporter_user_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    wait_for_active(table_name)
    print(f"{table_name} created.\n")


def create_match_table() -> None:
    table_name = "Match"
    if table_exists(table_name):
        print(f"{table_name} already exists — skipping creation.")
        return
    print(f"Creating {table_name} with GSIs...")
    dynamodb.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": "match_id", "AttributeType": "S"},
            {"AttributeName": "case_id", "AttributeType": "S"},
            {"AttributeName": "found_id", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "match_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "case_id-index",
                "KeySchema": [{"AttributeName": "case_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "found_id-index",
                "KeySchema": [{"AttributeName": "found_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    wait_for_active(table_name)
    print(f"{table_name} created.\n")


def upgrade_found_report_table() -> None:
    table_name = "FoundReport"
    if not table_exists(table_name):
        print(f"{table_name} doesn't exist yet — run your scraper's table-creation "
              f"step first (see earlier setup), then re-run this script.")
        return

    desc = dynamodb.describe_table(TableName=table_name)["Table"]
    existing_gsi_names = {g["IndexName"] for g in desc.get("GlobalSecondaryIndexes", [])}
    stream_enabled = desc.get("StreamSpecification", {}).get("StreamEnabled", False)

    print(f"{table_name} already exists with {desc['ItemCount']} items (approx) — upgrading in place.")

    if not stream_enabled:
        print("  Enabling DynamoDB Streams (NEW_IMAGE)...")
        dynamodb.update_table(
            TableName=table_name,
            StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"},
        )
        wait_for_active(table_name)
        print("  Streams enabled.")
    else:
        print("  Streams already enabled — skipping.")

    gsis_to_add = [
        {
            "IndexName": "source-lastUpdatedAt-index",
            "attrs": [
                {"AttributeName": "source", "AttributeType": "S"},
                {"AttributeName": "last_updated_at", "AttributeType": "S"},
            ],
            "key_schema": [
                {"AttributeName": "source", "KeyType": "HASH"},
                {"AttributeName": "last_updated_at", "KeyType": "RANGE"},
            ],
        },
        {
            "IndexName": "reporter_user_id-index",
            "attrs": [{"AttributeName": "reporter_user_id", "AttributeType": "S"}],
            "key_schema": [{"AttributeName": "reporter_user_id", "KeyType": "HASH"}],
        },
    ]

    
    
    for gsi in gsis_to_add:
        if gsi["IndexName"] in existing_gsi_names:
            print(f"  {gsi['IndexName']} already exists — skipping.")
            continue
        print(f"  Adding index {gsi['IndexName']} (this backfills existing items, can take a few minutes)...")
        dynamodb.update_table(
            TableName=table_name,
            AttributeDefinitions=gsi["attrs"],
            GlobalSecondaryIndexUpdates=[{
                "Create": {
                    "IndexName": gsi["IndexName"],
                    "KeySchema": gsi["key_schema"],
                    "Projection": {"ProjectionType": "ALL"},
                }
            }],
        )
        wait_for_gsi_active(table_name, gsi["IndexName"])

    print(f"{table_name} upgrade complete.\n")


if __name__ == "__main__":
    create_simple_table("User", "user_id")
    create_simple_table("SourceSyncStatus", "source_name")
    create_missing_case_table()
    create_match_table()
    upgrade_found_report_table()
    print("All tables ready.")
