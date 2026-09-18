import sys
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, "/home/ssm-user/bharat-talaash/matching")

from matchingfinal import MatchingEngine

TABLE = "FoundReport"
REGION = "ap-southeast-2"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE = "/home/ssm-user/bharat-talaash/cache/foundreport_embedding_cache.npz"

app = FastAPI(title="BharatTalaash GPU Matcher")
engine = MatchingEngine(TABLE, REGION, MODEL, 64, CACHE)
engine.bootstrap()

class SearchRequest(BaseModel):
    query: Dict[str, Any]
    top_n: int = 5

class RefreshRequest(BaseModel):
    records: List[Dict[str, Any]]

@app.get("/health")
def health():
    return engine.get_health_info()

@app.post("/search")
def search(req: SearchRequest):
    try:
        results = engine.search(req.query, top_n=req.top_n)
        return {"status": "success", "count": len(results), "matches": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/refresh")
def refresh(req: RefreshRequest):
    try:
        result = engine.add_or_update_records(req.records)
        return {"status": "success", "index_update": result, "health": engine.get_health_info()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
