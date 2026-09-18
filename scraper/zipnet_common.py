

import json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import boto3, requests

BASE_URL = "https://zipnet.delhipolice.gov.in"
REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES = 3
DEFAULT_WRITE_WORKERS = 16
PROTECTED_ATTRIBUTES = {"embedding", "embedding_model", "embedding_text_hash"}
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

_s3_client = None
_dynamodb_resource = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=AWS_REGION)
    return _s3_client


def _get_dynamodb():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb_resource


class ZipnetScraper:
    def __init__(self, name, list_endpoint, referer_path, columns,
                 normalize_fn, dynamodb_table, s3_bucket,
                 id_field, page_size=50, on_page_saved=None,
                 write_workers=DEFAULT_WRITE_WORKERS):
        self.name = name
        self.list_endpoint = list_endpoint
        self.columns = columns
        self.normalize_fn = normalize_fn
        self.dynamodb_table = dynamodb_table
        self.s3_bucket = s3_bucket
        self.id_field = id_field
        self.page_size = page_size
        self.on_page_saved = on_page_saved
        self.write_workers = max(1, int(write_workers))
        self.checkpoint_file = Path(f"zipnet_{name}_progress.json")
        self.skipped_log = Path(f"zipnet_{name}_skipped.log")
        self.headers = {
            "User-Agent": "DhundHackathonProject/1.0",
            "Referer": f"{BASE_URL}{referer_path}",
        }

    def build_payload(self, start, length, search_form=None):
        p = {"draw": "1"}
        for i, col in enumerate(self.columns):
            p[f"columns[{i}][data]"] = col["data"]
            p[f"columns[{i}][name]"] = col["name"]
            p[f"columns[{i}][searchable]"] = col["searchable"]
            p[f"columns[{i}][orderable]"] = col["orderable"]
            p[f"columns[{i}][search][value]"] = ""
            p[f"columns[{i}][search][regex]"] = "false"
        p["order[0][column]"] = "1"
        p["order[0][dir]"] = "desc"
        p["start"] = str(start)
        p["length"] = str(length)
        p["search[value]"] = ""
        p["search[regex]"] = "false"
        p["searchFormJson"] = json.dumps(search_form or {})
        return p

    def fetch_page(self, start, length=None, search_form=None):
        length = length or self.page_size
        payload = self.build_payload(start, length, search_form)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = requests.post(self.list_endpoint, data=payload,
                                  headers=self.headers, timeout=20)
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as exc:
                wait = 5 * attempt
                print(f"  [{self.name}] Request failed ({exc}) — retry in {wait}s "
                      f"({attempt}/{MAX_RETRIES})")
                time.sleep(wait)
        raise RuntimeError(f"[{self.name}] Gave up after {MAX_RETRIES} retries at start={start}")

    def sanity_check_first_page(self, search_form=None):
        res = self.fetch_page(0, length=5, search_form=search_form)
        total = res.get("recordsTotal", 0)
        if not res.get("data") or total == 0:
            raise RuntimeError(f"[{self.name}] Empty — check endpoint/columns.")
        print(f"[{self.name}] Sanity OK: server reports {total} records.")
        return total

    def fetch_range_resilient(self, start, target_end, search_form=None):
        need = target_end - start
        for length in (need, 25, 10, 5, 1):
            length = min(length, need)
            if length <= 0:
                break
            try:
                res = self.fetch_page(start, length=length, search_form=search_form)
                return res.get("data", []), start + length
            except RuntimeError as exc:
                print(f"  [{self.name}] start={start} length={length} failed ({exc}) — "
                      f"{'giving up' if length == 1 else 'shrinking'}...")
        print(f"  [{self.name}] start={start} broken even at 1 — skipping.")
        with self.skipped_log.open("a") as f:
            f.write(f"{start}\n")
        return [], start + 1

    def load_checkpoint(self):
        if self.checkpoint_file.exists():
            return json.loads(self.checkpoint_file.read_text())
        return {"start": 0, "records_saved": 0}

    def save_checkpoint(self, state):
        self.checkpoint_file.write_text(json.dumps(state))

    def clean_for_dynamodb(self, record):
        out = {}
        for k, v in record.items():
            if v is None:
                continue
            if isinstance(v, tuple):
                v = list(v)
            out[k] = v
        return out

    def save_page_to_s3(self, start, raw_records):
        key = f"raw-sources/zipnet/{self.name}/start-{start:06d}.json"
        body = json.dumps(raw_records, ensure_ascii=False).encode("utf-8")
        _get_s3().put_object(Bucket=self.s3_bucket, Key=key, Body=body,
                             ContentType="application/json")

    def _upsert_record(self, table, item):
        key = {self.id_field: item[self.id_field]}
        names, values, parts = {}, {}, []
        i = 0
        for k, v in item.items():
            if k == self.id_field or k in PROTECTED_ATTRIBUTES:
                continue
            an, av = f"#n{i}", f":v{i}"
            names[an] = k
            values[av] = v
            parts.append(f"{an} = {av}")
            i += 1
        if not parts:
            return item
        resp = table.update_item(
            Key=key,
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes", item)

    def load_page_to_dynamodb(self, raw_records):
        table = _get_dynamodb().Table(self.dynamodb_table)
        batch_norm = []
        for raw in raw_records:
            n = self.normalize_fn(raw)
            c = self.clean_for_dynamodb(n)
            if c.get(self.id_field):
                batch_norm.append(c)
        if not batch_norm:
            return 0
        saved, failed = [], 0
        with ThreadPoolExecutor(max_workers=self.write_workers) as pool:
            futs = {pool.submit(self._upsert_record, table, it): it
                    for it in batch_norm}
            for fut in as_completed(futs):
                item = futs[fut]
                try:
                    saved.append(fut.result())
                except Exception as exc:
                    failed += 1
                    print(f"  [{self.name}] upsert failed for "
                          f"{item.get(self.id_field)}: {exc}")
        if failed:
            print(f"  [{self.name}] {failed}/{len(batch_norm)} upserts failed")
        if saved and self.on_page_saved is not None:
            try:
                self.on_page_saved(saved)
            except Exception as exc:
                print(f"  [{self.name}] on_page_saved hook failed: {exc}")
        return len(saved)

    def run(self, search_form=None, max_pages=None):
        if "PASTE_YOUR" in self.s3_bucket:
            raise RuntimeError(f"[{self.name}] Set S3 bucket first.")
        total = self.sanity_check_first_page(search_form)
        state = self.load_checkpoint()
        start = state["start"]
        pages_done = 0
        stopped = False
        while start < total:
            if max_pages is not None and pages_done >= max_pages:
                stopped = True
                break
            tgt = min(start + self.page_size, total)
            print(f"[{self.name}] Records {start}-{tgt} of {total} "
                  f"(saved so far: {state['records_saved']})...")
            recs, nxt = self.fetch_range_resilient(start, tgt, search_form)
            time.sleep(REQUEST_DELAY_SECONDS)
            if recs:
                self.save_page_to_s3(start, recs)
                state["records_saved"] += self.load_page_to_dynamodb(recs)
            start = nxt
            state["start"] = start
            self.save_checkpoint(state)
            pages_done += 1
        if stopped:
            print(f"\n[{self.name}] Stopped after {pages_done} pages "
                  f"(start={state['start']}, saved={state['records_saved']}).")
        else:
            print(f"\n[{self.name}] Done. {state['records_saved']} saved.")
