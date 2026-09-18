

import argparse
import boto3

from matching_engine_local import LocalSemanticIndex


def scan_table(table_name: str, region: str):
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    items = []
    kwargs = {"ProjectionExpression": "#id, #name, age, age_range, gender, height_cm, complexion, location, date_found, clothing, distinctive_marks, description, photo",
              "ExpressionAttributeNames": {"#id": "found_id", "#name": "name"}}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default="FoundReport")
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--out", default="./local_index")
    args = parser.parse_args()

    records = scan_table(args.table, args.region)
    print(f"Loaded {len(records):,} records from DynamoDB")

    index = LocalSemanticIndex()
    index.build(records)
    index.save(args.out)
    print(f"Saved local semantic index to {args.out}")
    print("No OpenSearch is required for future searches.")


if __name__ == "__main__":
    main()
