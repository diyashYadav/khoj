







import json
import time
from pathlib import Path

import boto3
import requests

BASE_URL = "https://zipnet.delhipolice.gov.in"
REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES = 3

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


class ZipnetScraper:
    def __init__(self, name: str, list_endpoint: str, referer_path: str, columns: list,
                 normalize_fn, dynamodb_table: str, s3_bucket: str,
                 id_field: str, page_size: int = 50):









        self.name = name
        self.list_endpoint = list_endpoint
        self.columns = columns
        self.normalize_fn = normalize_fn
        self.dynamodb_table = dynamodb_table
        self.s3_bucket = s3_bucket
        self.id_field = id_field
        self.page_size = page_size
        self.checkpoint_file = Path(f"zipnet_{name}_progress.json")
        self.skipped_log = Path(f"zipnet_{name}_skipped.log")
        self.headers = {
            "User-Agent": "DhundHackathonProject/1.0 (missing-person matching research; contact: YOUR_EMAIL_HERE)",
            "Referer": f"{BASE_URL}{referer_path}",
        }

    def build_payload(self, start: int, length: int, search_form: dict = None) -> dict:
        payload = {"draw": "1"}
        for i, col in enumerate(self.columns):
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

    def fetch_page(self, start: int, length: int = None, search_form: dict = None) -> dict:
        length = length or self.page_size
        payload = self.build_payload(start, length, search_form)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(self.list_endpoint, data=payload, headers=self.headers, timeout=20)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                wait = 5 * attempt
                print(f"  [{self.name}] Request failed ({exc}) — retrying in {wait}s "
                      f"(attempt {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
        raise RuntimeError(f"[{self.name}] Gave up after {MAX_RETRIES} retries at start={start}")

    def sanity_check_first_page(self, search_form: dict = None) -> int:
        result = self.fetch_page(start=0, length=5, search_form=search_form)
        total = result.get("recordsTotal", 0)
        data = result.get("data", [])
        if not data or total == 0:
            raise RuntimeError(
                f"[{self.name}] Empty response — the endpoint URL or columns[] for "
                f"this page probably need fixing. Check DevTools on this specific "
                f"page (F12 -> Network -> Fetch/XHR -> search -> inspect the "
                f"request), same procedure as before."
            )
        print(f"[{self.name}] Sanity check passed: server reports {total} total records.")
        return total

    def fetch_range_resilient(self, start: int, target_end: int, search_form: dict = None):
        length_needed = target_end - start
        for length in (length_needed, 25, 10, 5, 1):
            length = min(length, length_needed)
            if length <= 0:
                break
            try:
                result = self.fetch_page(start, length=length, search_form=search_form)
                return result.get("data", []), start + length
            except RuntimeError as exc:
                print(f"  [{self.name}] start={start} length={length} failed ({exc}) — "
                      f"{'giving up on this record' if length == 1 else 'shrinking and retrying'}...")
        print(f"  [{self.name}] Record at start={start} breaks the server even at "
              f"length=1 — skipping, logged to {self.skipped_log}.")
        with self.skipped_log.open("a") as f:
            f.write(f"{start}\n")
        return [], start + 1

    def load_checkpoint(self) -> dict:
        if self.checkpoint_file.exists():
            return json.loads(self.checkpoint_file.read_text())
        return {"start": 0, "records_saved": 0}

    def save_checkpoint(self, state: dict) -> None:
        self.checkpoint_file.write_text(json.dumps(state))

    def clean_for_dynamodb(self, record: dict) -> dict:
        cleaned = {}
        for k, v in record.items():
            if v is None:
                continue
            if isinstance(v, tuple):
                v = list(v)
            cleaned[k] = v
        return cleaned

    def save_page_to_s3(self, start: int, raw_records: list) -> None:
        key = f"raw-sources/zipnet/{self.name}/start-{start:06d}.json"
        body = json.dumps(raw_records, ensure_ascii=False).encode("utf-8")
        s3.put_object(Bucket=self.s3_bucket, Key=key, Body=body, ContentType="application/json")

    def load_page_to_dynamodb(self, raw_records: list) -> int:
        table = dynamodb.Table(self.dynamodb_table)
        saved = 0
        with table.batch_writer() as batch:
            for raw in raw_records:
                normalized = self.normalize_fn(raw)
                cleaned = self.clean_for_dynamodb(normalized)
                if cleaned.get(self.id_field):
                    batch.put_item(Item=cleaned)
                    saved += 1
        return saved

    def run(self, search_form: dict = None) -> None:
        if "PASTE_YOUR" in self.s3_bucket:
            raise RuntimeError(f"[{self.name}] Set the S3 bucket before running.")

        total = self.sanity_check_first_page(search_form)
        state = self.load_checkpoint()
        start = state["start"]

        while start < total:
            target_end = min(start + self.page_size, total)
            print(f"[{self.name}] Records {start}-{target_end} of {total} "
                  f"(saved so far: {state['records_saved']})...")

            records, next_start = self.fetch_range_resilient(start, target_end, search_form)
            time.sleep(REQUEST_DELAY_SECONDS)

            if records:
                self.save_page_to_s3(start, records)
                saved = self.load_page_to_dynamodb(records)
                state["records_saved"] += saved

            start = next_start
            state["start"] = start
            self.save_checkpoint(state)

        print(f"\n[{self.name}] Done. {state['records_saved']} records saved to "
              f"'{self.dynamodb_table}'.")
