
































import json
import time
from pathlib import Path

import requests

from normalize_record import normalize_record

BASE_URL = "https://zipnet.delhipolice.gov.in"
LIST_ENDPOINT = f"{BASE_URL}/Victims/GetUnIdentifiedPersonsData/"

PAGE_SIZE = 50
CHECKPOINT_FILE = Path("zipnet_progress.json")
OUTPUT_FILE = Path("zipnet_unidentified_persons.jsonl")

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
        raise RuntimeError(
            "Still empty even with the exact captured payload format — "
            "something else differs (maybe a cookie/session requirement, "
            "or a CSRF/anti-forgery token field wasn't included). Check "
            "DevTools once more for any hidden header like "
            "'__RequestVerificationToken' or a Cookie value being sent."
        )
    print(f"Sanity check passed: server reports {total} total records. "
          f"Sample record ID: {data[0].get('UnIdentifiedPersonId')}")
    return total


def scrape_all() -> None:
    total = sanity_check_first_page()
    state = load_checkpoint()
    start = state["start"]

    with OUTPUT_FILE.open("a", encoding="utf-8") as out:
        while start < total:
            print(f"Fetching records {start}-{start + PAGE_SIZE} of {total} "
                  f"(saved so far: {state['records_saved']})...")

            result = fetch_page(start)
            time.sleep(REQUEST_DELAY_SECONDS)

            records = result.get("data", [])
            if not records:
                print("No more records — done.")
                break

            for raw in records:
                normalized = normalize_record(raw)
                out.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                state["records_saved"] += 1

            start += PAGE_SIZE
            state["start"] = start
            save_checkpoint(state)

    print(f"\nDone. Saved {state['records_saved']} records to {OUTPUT_FILE}")


if __name__ == "__main__":
    scrape_all()
