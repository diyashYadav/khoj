import argparse
import sys
import base64
import json

import boto3
sys.path.insert(0, "/home/ssm-user/bharat-talaash/matching")
sys.path.insert(0, "/home/ssm-user/bharat-talaash/ai")

from boto3.dynamodb.types import TypeDeserializer

from embedding_worker import EmbeddingWorker, handoff_to_matcher
from matchingfinal import MatchingEngine

TABLE = "FoundReport"
REGION = "ap-southeast-2"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE = "/home/ssm-user/bharat-talaash/cache/foundreport_embedding_cache.npz"

ddb = boto3.client("dynamodb", region_name=REGION)
deserializer = TypeDeserializer()

def deserialize_item(item):
    return {key: deserializer.deserialize(value) for key, value in item.items()}

def fetch_records(found_ids):
    found_ids = list(dict.fromkeys(str(x) for x in found_ids if x))
    records = []
    for start in range(0, len(found_ids), 100):
        ids = found_ids[start:start + 100]
        request_items = {
            TABLE: {
                "Keys": [{"found_id": {"S": found_id}} for found_id in ids],
                "ConsistentRead": False,
            }
        }
        while request_items:
            response = ddb.batch_get_item(RequestItems=request_items)
            records.extend(
                deserialize_item(item)
                for item in response.get("Responses", {}).get(TABLE, [])
            )
            pending = response.get("UnprocessedKeys", {})
            if not pending.get(TABLE, {}).get("Keys"):
                break
            request_items = pending
    return records

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-b64", required=True)
    args = parser.parse_args()
    payload = json.loads(base64.b64decode(args.payload_b64).decode("utf-8"))
    found_ids = payload.get("found_ids", [])
    records = fetch_records(found_ids)
    worker = EmbeddingWorker(
        table_name=TABLE,
        region=REGION,
        model_name="all-MiniLM-L6-v2",
        workers=16,
        encode_batch_size=256,
    )
    processed = worker.process_records(records)
    matcher = MatchingEngine(TABLE, REGION, MODEL, 64, CACHE)
    matcher.bootstrap()
    index_update = handoff_to_matcher(processed.records, matcher) if processed.records else {
        "added": 0,
        "updated": 0,
        "skipped": 0,
    }
    result = {
        "status": "success",
        "requested": len(found_ids),
        "fetched": len(records),
        "embedding_stats": processed.stats.as_dict(),
        "index_update": index_update,
        "matcher_health": matcher.get_health_info(),
    }
    print("RESULT_JSON=" + json.dumps(result, default=str))

if __name__ == "__main__":
    main()
