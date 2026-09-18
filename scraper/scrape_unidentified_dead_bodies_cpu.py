import json
import logging
import os

import boto3

from normalize_record import normalize_record
from zipnet_common import BASE_URL, ZipnetScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")
S3_BUCKET = os.getenv("ZIPNET_S3_BUCKET", "universe-test-1")
QUEUE_URL = os.getenv(
    "BHARAT_TALAASH_EMBEDDING_QUEUE_URL",
    "https://sqs.ap-southeast-2.amazonaws.com/743976413697/BharatTalaash-PendingEmbeddings",
)
LIST_ENDPOINT = f"{BASE_URL}/Victims/GetUnIdentifiedDeadBodiesData/"
REFERER_PATH = "/Victims/UnIdentifiedDeadBodies"
SOURCE_URL_PATH = "/Victims/UnIdentifiedDeadBodies"

COLUMNS = [
    {"data": "UnIdentifiedDeadBodyId", "name": "UnIdentifiedDeadBodyId", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "true"},
    {"data": "", "name": "", "searchable": "false", "orderable": "false"},
    {"data": "ImageUrls", "name": "", "searchable": "true", "orderable": "true"},
    {"data": "State", "name": "State", "searchable": "true", "orderable": "false"},
    {"data": "District", "name": "District", "searchable": "true", "orderable": "false"},
    {"data": "PoliceStation", "name": "PoliceStation", "searchable": "true", "orderable": "false"},
    {"data": "DD_Date", "name": "DD date", "searchable": "true", "orderable": "false"},
    {"data": "UIDBSerialNumber", "name": "UIDBSerialNumber", "searchable": "true", "orderable": "false"},
    {"data": "FoundDateTime", "name": "FoundDateTime", "searchable": "true", "orderable": "false"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "false"},
    {"data": "", "name": "", "searchable": "true", "orderable": "false"},
]

_env = os.environ.get("ZIPNET_MAX_PAGES", "0").strip()
MAX_PAGES = int(_env) if _env.isdigit() and int(_env) > 0 else None

sqs = boto3.client("sqs", region_name=REGION)
queue_stats = {"queued": 0, "failed": 0}

def enqueue_for_embedding(records):
    ids = list(dict.fromkeys(str(r.get("found_id")) for r in records if r.get("found_id")))
    for start in range(0, len(ids), 10):
        chunk = ids[start:start + 10]
        entries = [
            {"Id": str(i), "MessageBody": json.dumps({"found_id": found_id})}
            for i, found_id in enumerate(chunk)
        ]
        try:
            result = sqs.send_message_batch(QueueUrl=QUEUE_URL, Entries=entries)
            queue_stats["queued"] += len(result.get("Successful", []))
            queue_stats["failed"] += len(result.get("Failed", []))
        except Exception as exc:
            queue_stats["failed"] += len(chunk)
            print(f"Embedding queue send failed for {len(chunk)} records: {exc}")

scraper = ZipnetScraper(
    name="unidentified_dead_bodies",
    list_endpoint=LIST_ENDPOINT,
    referer_path=REFERER_PATH,
    columns=COLUMNS,
    normalize_fn=lambda raw: normalize_record(
        raw,
        record_subtype="deceased",
        id_field_raw="UnIdentifiedDeadBodyId",
        source_url_path=SOURCE_URL_PATH,
    ),
    dynamodb_table="FoundReport",
    s3_bucket=S3_BUCKET,
    id_field="found_id",
    on_page_saved=enqueue_for_embedding,
)

if __name__ == "__main__":
    scraper.run(max_pages=MAX_PAGES)
    print(
        f"\nEmbedding queue totals: queued={queue_stats['queued']} failed={queue_stats['failed']}"
    )
