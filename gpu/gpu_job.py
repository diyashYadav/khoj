import argparse
import sys
import base64
import json

sys.path.insert(0, "/home/ssm-user/bharat-talaash/matching")

from matchingfinal import MatchingEngine

TABLE = "FoundReport"
REGION = "ap-southeast-2"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE = "/home/ssm-user/bharat-talaash/cache/foundreport_embedding_cache.npz"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-b64", required=True)
    args = parser.parse_args()
    payload = json.loads(base64.b64decode(args.payload_b64).decode("utf-8"))
    query = payload.get("query", payload)
    top_n = int(payload.get("top_n", 5)) if isinstance(payload, dict) else 5
    engine = MatchingEngine(TABLE, REGION, MODEL, 64, CACHE)
    engine.bootstrap()
    results = engine.search(query, top_n=top_n)
    result = {
        "status": "success",
        "query": query,
        "count": len(results),
        "matches": results,
        "matcher_health": engine.get_health_info(),
    }
    print("RESULT_JSON=" + json.dumps(result, default=str))

if __name__ == "__main__":
    main()
