import base64
import sys
from decimal import Decimal
from typing import Any, Dict, List

import boto3
from boto3.dynamodb.types import TypeDeserializer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, "/home/ssm-user/bharat-talaash/matching")

from matchingfinal import MatchingEngine

TABLE = "FoundReport"
REGION = "ap-southeast-2"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE = "/home/ssm-user/bharat-talaash/cache/foundreport_embedding_cache.npz"

app = FastAPI(title="BharatTalaash CPU Matcher")

engine = MatchingEngine(TABLE, REGION, MODEL, 64, CACHE)
engine.bootstrap()

ddb = boto3.client("dynamodb", region_name=REGION)
deserializer = TypeDeserializer()

class SearchRequest(BaseModel):
    query: Dict[str, Any]
    top_n: int = 5

class RefreshRequest(BaseModel):
    found_ids: List[str]

INTERNAL_FIELDS = {"embedding"}

def make_json_safe(value):
    if isinstance(value, dict):
        return {
            key: make_json_safe(item)
            for key, item in value.items()
            if key not in INTERNAL_FIELDS
        }
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if hasattr(value, "item"):
        try:
            return make_json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return make_json_safe(value.tolist())
        except Exception:
            pass
    return value

def deserialize_item(item):
    return {key: deserializer.deserialize(value) for key, value in item.items()}

def fetch_records(found_ids):
    records = []
    clean_ids = list(dict.fromkeys(str(x) for x in found_ids if x))
    for start in range(0, len(clean_ids), 100):
        ids = clean_ids[start:start + 100]
        request_items = {
            TABLE: {
                "Keys": [{"found_id": {"S": found_id}} for found_id in ids],
                "ConsistentRead": False,
            }
        }
        while request_items:
            response = ddb.batch_get_item(RequestItems=request_items)
            items = response.get("Responses", {}).get(TABLE, [])
            records.extend(deserialize_item(item) for item in items)
            unprocessed = response.get("UnprocessedKeys", {})
            table_pending = unprocessed.get(TABLE)
            if not table_pending or not table_pending.get("Keys"):
                break
            request_items = unprocessed
    return records

@app.get("/health")
def health():
    return make_json_safe(engine.get_health_info())

@app.post("/search")
def search(req: SearchRequest):
    try:
        results = engine.search(req.query, top_n=req.top_n)
        safe_results = make_json_safe(results)
        return {"status": "success", "count": len(safe_results), "matches": safe_results}
    except Exception as exc:
        print("SEARCH ERROR:", repr(exc))
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/refresh")
def refresh(req: RefreshRequest):
    try:
        records = fetch_records(req.found_ids)
        if not records:
            return {
                "status": "success",
                "requested": len(req.found_ids),
                "fetched": 0,
                "index_update": {"added": 0, "updated": 0, "skipped": 0},
                "health": make_json_safe(engine.get_health_info()),
            }
        result = engine.add_or_update_records(records)
        return {
            "status": "success",
            "requested": len(req.found_ids),
            "fetched": len(records),
            "index_update": make_json_safe(result),
            "health": make_json_safe(engine.get_health_info()),
        }
    except Exception as exc:
        print("REFRESH ERROR:", repr(exc))
        raise HTTPException(status_code=500, detail=str(exc))
