













import json
import time
from pathlib import Path

import boto3
import requests

from normalize_record import normalize_record


S3_BUCKET = "universe-test-1"
DYNAMODB_TABLE = "FoundReport"  


BASE_URL = "https://zipnet.delhipolice.gov.in"
LIST_ENDPOINT = f"{BASE_URL}/Victims/GetUnIdentifiedPersonsData/"

PAGE_SIZE = 50
CHECKPOINT_FILE = Path("zipnet_progress.json")  

REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "DhundHackathonProject/1.0 (missing-person matching research; contact: YOUR_EMAIL_HERE)",
    "Referer": f"{BASE_URL}/Victims/UnIdentifiedPersons",
}

COLUMNS = [
    {"data": "UnIdentifiedPersonId", "name": "UnIdentifiedPersonId", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "true"},
    {"data": "", "name": "", "searchable": "false", "orderable": "false"},
    {"data": "ImageUrls", "name": "", "searchable": "true", "orderable": "true"},
    {"data": "State", "name": "State", "searchable": "true", "orderable": "false"},
    {"data": "District", "name": "District", "searchable": "true", "orderable": "false"},
    {"data": "PoliceStation", "name": "PoliceStation", "searchable": "true", "orderable": "false"},
    {"data": "DDNo", "name": "DDNo", "searchable": "true", "orderable": "false"},
    {"data": "DD_Date", "name": "DD_Date", "searchable": "true", "orderable": "false"},
    {"data": "UIPFSerialNumber", "name": "UIPFSerialNumber", "searchable": "true", "orderable": "true"},
    {"data": "FoundDateTime", "name": "FoundDateTime", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "false"},
    {"data": "", "name": "", "searchable": "true", "orderable": "false"},
]

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"start": 0, "records_saved": 0}


def save_checkpoint(state: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(state))


def build_payload(start: int, length: int, search_form: dict = None) -> dict:
    payload = {"draw": "1"}
    for i, col in enumerate(COLUMNS):
        payload[f"columns[{i}][data]"] = col["data"]
        payload[f"columns[{i}][name]"] = col["name"]
        payload[f"columns[{i}][searchable]"] = col["searchable"]
        payload[f"columns[{i}][orderable]"] = col["orderable"]
        payload[f"columns[{i}][search][value]"] = ""
        payload[f"columns[{i}][search][regex]"] = "false"
    payload["order[0][column]"] = "1"
    payload["order[0][dir]"] = "desc"
    payload["start"] = str(start)
    payload["length"] = str(length)
    payload["search[value]"] = ""
    payload["search[regex]"] = "false"
    payload["searchFormJson"] = json.dumps(search_form or {})
    return payload


def fetch_page(start: int, length: int = PAGE_SIZE, search_form: dict = None) -> dict:
    payload = build_payload(start, length, search_form)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(LIST_ENDPOINT, data=payload, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            wait = 5 * attempt
            print(f"  Request failed ({exc}) — retrying in {wait}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
    raise RuntimeError(f"Gave up after {MAX_RETRIES} retries at start={start}")


def sanity_check_first_page() -> int:
    result = fetch_page(start=0, length=5)
    total = result.get("recordsTotal", 0)
    data = result.get("data", [])
    if not data or total == 0:
        raise RuntimeError("Empty response — check payload/session as discussed before.")
    print(f"Sanity check passed: server reports {total} total records.")
    return total


def clean_for_dynamodb(record: dict) -> dict:
    cleaned = {}
    for k, v in record.items():
        if v is None:
            continue
        if isinstance(v, tuple):
            v = list(v)
        cleaned[k] = v
    return cleaned


def save_page_to_s3(start: int, raw_records: list) -> None:
    key = f"raw-sources/zipnet/unidentified_persons/start-{start:06d}.json"
    body = json.dumps(raw_records, ensure_ascii=False).encode("utf-8")
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType="application/json")


def load_page_to_dynamodb(raw_records: list) -> int:
    table = dynamodb.Table(DYNAMODB_TABLE)
    saved = 0
    with table.batch_writer() as batch:
        for raw in raw_records:
            normalized = normalize_record(raw)
            cleaned = clean_for_dynamodb(normalized)
            if cleaned.get("found_id"):
                batch.put_item(Item=cleaned)
                saved += 1
    return saved


SKIPPED_RECORDS_LOG = Path("zipnet_skipped_records.log")


def fetch_range_resilient(start: int, target_end: int):







    length = target_end - start
    if length <= 0:
        return [], start

    try:
        result = fetch_page(start, length=length)
        return result.get("data", []), target_end
    except RuntimeError as exc:
        print(
            f"  [SKIP] start={start} length={length} failed ({exc}) "
            f"— skipping this page and continuing."
        )
        with SKIPPED_RECORDS_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{start}\n")
        return [], target_end


def scrape_direct_to_aws() -> None:
    if "PASTE_YOUR" in S3_BUCKET:
        raise RuntimeError("Set S3_BUCKET at the top of this file first.")

    total = sanity_check_first_page()
    state = load_checkpoint()
    start = state["start"]

    while start < total:
        target_end = min(start + PAGE_SIZE, total)
        print(f"Records {start}-{target_end} of {total} "
              f"(saved so far: {state['records_saved']})...")

        records, next_start = fetch_range_resilient(start, target_end)
        time.sleep(REQUEST_DELAY_SECONDS)

        if records:
            save_page_to_s3(start, records)                
            saved = load_page_to_dynamodb(records)          
            state["records_saved"] += saved

        start = next_start
        state["start"] = start
        save_checkpoint(state)

    print(f"\nDone. {state['records_saved']} records now in DynamoDB table "
          f"'{DYNAMODB_TABLE}', raw pages backed up under "
          f"s3://{S3_BUCKET}/raw-sources/zipnet/unidentified_persons/. "
          f"Check {SKIPPED_RECORDS_LOG} for any records that had to be skipped.")


if __name__ == "__main__":
    scrape_direct_to_aws()
