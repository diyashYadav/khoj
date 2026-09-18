


from __future__ import annotations
import hashlib, json, logging, os, struct, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import boto3

DEFAULT_TABLE = "FoundReport"
DEFAULT_REGION = "ap-southeast-2"
DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_BATCH_SIZE = 2000
DEFAULT_ENCODE_BATCH_SIZE = 256
DEFAULT_WORKERS = 16
DEFAULT_EMBEDDING_ATTRIBUTE = "embedding"
DEFAULT_MODEL_ATTRIBUTE = "embedding_model"
DEFAULT_HASH_ATTRIBUTE = "embedding_text_hash"
EMBEDDING_DIM = 384

SEMANTIC_FIELDS = ("description", "clothing", "distinctive_marks", "location")
SEMANTIC_LABELS = {
    "description": "description", "clothing": "clothing",
    "distinctive_marks": "distinctive marks", "location": "location",
}
PROJECTION_FIELDS = [
    "found_id", "description", "clothing", "distinctive_marks", "location",
    "embedding", "embedding_model", "embedding_text_hash",
]

log = logging.getLogger("bharat_talaash.embeddings")


def semantic_text(r):
    parts = []
    for f in SEMANTIC_FIELDS:
        v = r.get(f)
        if v not in (None, "", [], {}):
            parts.append(f"{SEMANTIC_LABELS[f]}: {v}")
    return " | ".join(parts)


def text_hash(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def pack_embedding(vec):
    vals = [float(x) for x in vec]
    return struct.pack(f"<{len(vals)}f", *vals)


def decode_embedding(packed):
    packed = _as_bytes(packed) or b""
    if len(packed) % 4 != 0:
        raise ValueError(f"byte length {len(packed)} not multiple of 4")
    return list(struct.unpack(f"<{len(packed)//4}f", packed))


def _as_bytes(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        return v
    if isinstance(v, (bytearray, memoryview)):
        return bytes(v)
    inner = getattr(v, "value", None)
    if inner is not None and inner is not v:
        return _as_bytes(inner)
    try:
        return bytes(v)
    except Exception:
        return None


def _is_current(rec, model, h, ea, ma, ha, dim=EMBEDDING_DIM):
    e = rec.get(ea)
    if not e: return False
    if rec.get(ma) != model: return False
    if rec.get(ha) != h: return False
    try:
        b = _as_bytes(e)
        if b is None or len(b) != dim * 4: return False
        if len(decode_embedding(b)) != dim: return False
    except Exception:
        return False
    return True


@dataclass
class ProcessStats:
    processed: int = 0
    skipped: int = 0
    embedded: int = 0
    updated: int = 0
    failed: int = 0
    failures: List[Dict[str, Optional[str]]] = field(default_factory=list)

    def merge(self, other):
        self.processed += other.processed
        self.skipped += other.skipped
        self.embedded += other.embedded
        self.updated += other.updated
        self.failed += other.failed
        self.failures.extend(other.failures)

    def as_dict(self):
        return {"processed": self.processed, "skipped": self.skipped,
                "embedded": self.embedded, "updated": self.updated,
                "failed": self.failed, "failures": list(self.failures)}


@dataclass
class ProcessResult:
    records: List[Dict[str, Any]]
    stats: ProcessStats


class EmbeddingWorker:
    def __init__(self, table_name=DEFAULT_TABLE, region=DEFAULT_REGION,
                 model_name=DEFAULT_MODEL, workers=DEFAULT_WORKERS,
                 encode_batch_size=DEFAULT_ENCODE_BATCH_SIZE,
                 embedding_attribute=DEFAULT_EMBEDDING_ATTRIBUTE,
                 model_attribute=DEFAULT_MODEL_ATTRIBUTE,
                 hash_attribute=DEFAULT_HASH_ATTRIBUTE,
                 dry_run=False, force=False):
        self.table_name = table_name
        self.region = region
        self.model_name = model_name
        self.workers = max(1, int(workers))
        self.encode_batch_size = max(1, int(encode_batch_size))
        self.embedding_attribute = embedding_attribute
        self.model_attribute = model_attribute
        self.hash_attribute = hash_attribute
        self.dry_run = bool(dry_run)
        self.force = bool(force)
        self._model = None
        self._device = None
        self._session = boto3.Session(region_name=region)
        self.table = self._session.resource("dynamodb").Table(table_name)

    def process_records(self, records):
        stats = ProcessStats(processed=len(records))
        ready, todo = [], []
        for r in records:
            if not isinstance(r, dict) or not r.get("found_id"):
                stats.failed += 1
                stats.failures.append({"found_id": None, "reason": "missing found_id"})
                continue
            t = semantic_text(r)
            h = text_hash(t)
            if not self.force and _is_current(
                r, self.model_name, h,
                self.embedding_attribute, self.model_attribute,
                self.hash_attribute, EMBEDDING_DIM):
                stats.skipped += 1
                ready.append(self._enrich(r, _as_bytes(r.get(self.embedding_attribute)), h))
                continue
            todo.append((r, t, h))
        if not todo:
            return ProcessResult(ready, stats)
        todo, vecs = self._encode_with_fallback(todo, stats)
        if not todo or vecs is None:
            return ProcessResult(ready, stats)
        if self.dry_run:
            for (r, _t, h), v in zip(todo, vecs):
                stats.embedded += 1
                ready.append(self._enrich(r, pack_embedding(v), h))
            return ProcessResult(ready, stats)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futs = {}
            for (r, _t, h), v in zip(todo, vecs):
                p = pack_embedding(v)
                futs[pool.submit(self._write_one, r, p, h)] = (r, p, h)
            for fut in as_completed(futs):
                r, p, h = futs[fut]
                try:
                    fut.result()
                except Exception as exc:
                    stats.failed += 1
                    stats.failures.append({
                        "found_id": r.get("found_id"),
                        "reason": f"dynamodb write failed: {exc}"})
                    continue
                stats.embedded += 1
                stats.updated += 1
                ready.append(self._enrich(r, p, h))
        return ProcessResult(ready, stats)

    def _get_model(self):
        if self._model is not None:
            return self._model
        import torch
        from sentence_transformers import SentenceTransformer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            log.info("Loading %s on CUDA (%s)", self.model_name,
                     torch.cuda.get_device_name(0))
        else:
            log.warning("CUDA unavailable; %s on CPU", self.model_name)
        self._model = SentenceTransformer(self.model_name, device=device)
        self._device = device
        return self._model

    def _encode_with_fallback(self, todo, stats):
        import numpy as np
        m = self._get_model()
        texts = [t for _, t, _ in todo]
        try:
            v = m.encode(texts, batch_size=self.encode_batch_size,
                         show_progress_bar=False, normalize_embeddings=True,
                         convert_to_numpy=True).astype("float32")
            return todo, v
        except Exception as exc:
            log.warning("Batch encode failed (%s); per-record fallback", exc)
        ok_t, ok_v = [], []
        for item in todo:
            r, t, _h = item
            try:
                v = m.encode([t], batch_size=1, show_progress_bar=False,
                             normalize_embeddings=True,
                             convert_to_numpy=True)[0].astype("float32")
                ok_t.append(item); ok_v.append(v)
            except Exception as exc:
                stats.failed += 1
                stats.failures.append({"found_id": r.get("found_id"),
                                       "reason": f"encode failed: {exc}"})
        if not ok_t:
            return [], None
        return ok_t, np.stack(ok_v)

    def _write_one(self, r, packed, h):
        self.table.update_item(
            Key={"found_id": r["found_id"]},
            UpdateExpression="SET #emb = :emb, #model = :model, #hash = :hash",
            ExpressionAttributeNames={
                "#emb": self.embedding_attribute,
                "#model": self.model_attribute,
                "#hash": self.hash_attribute},
            ExpressionAttributeValues={
                ":emb": packed, ":model": self.model_name, ":hash": h})

    def _enrich(self, r, packed, h):
        out = dict(r)
        if packed is not None:
            out[self.embedding_attribute] = packed
        out[self.model_attribute] = self.model_name
        out[self.hash_attribute] = h
        return out

    def scan_batches(self, batch_size=DEFAULT_BATCH_SIZE):
        names, fields = {}, []
        for i, f in enumerate(PROJECTION_FIELDS):
            a = f"#f{i}"; names[a] = f; fields.append(a)
        kw = {"ProjectionExpression": ", ".join(fields),
              "ExpressionAttributeNames": names}
        buf = []
        while True:
            resp = self.table.scan(**kw)
            buf.extend(resp.get("Items", []))
            while len(buf) >= batch_size:
                yield buf[:batch_size]; buf = buf[batch_size:]
            lk = resp.get("LastEvaluatedKey")
            if not lk:
                break
            kw["ExclusiveStartKey"] = lk
        if buf:
            yield buf


def handoff_to_matcher(records, matcher_engine):
    if matcher_engine is None:
        raise ValueError("matcher_engine required")
    fn = getattr(matcher_engine, "add_or_update_records", None)
    if not callable(fn):
        raise TypeError("matcher_engine needs add_or_update_records(records)")
    return fn(records)


def _iter_input_records(path):
    if path is None: return
    if path == "-":
        for line in sys.stdin:
            if line.strip(): yield json.loads(line)
        return
    with open(path, "r", encoding="utf-8") as fh:
        head = fh.read(1); fh.seek(0)
        if head == "[":
            for r in json.load(fh): yield r
        else:
            for line in fh:
                if line.strip(): yield json.loads(line)


def main(argv=None):
    import argparse
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--table", default=DEFAULT_TABLE)
    p.add_argument("--region", default=os.getenv("AWS_DEFAULT_REGION", DEFAULT_REGION))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--encode-batch-size", type=int, default=DEFAULT_ENCODE_BATCH_SIZE)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--input-file", default=None)
    p.add_argument("--scan", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--embedding-attribute", default=DEFAULT_EMBEDDING_ATTRIBUTE)
    p.add_argument("--model-attribute", default=DEFAULT_MODEL_ATTRIBUTE)
    p.add_argument("--hash-attribute", default=DEFAULT_HASH_ATTRIBUTE)
    args = p.parse_args(argv)
    if not args.input_file and not args.scan:
        log.error("Provide --input-file or --scan"); return 2
    w = EmbeddingWorker(
        table_name=args.table, region=args.region, model_name=args.model,
        workers=args.workers, encode_batch_size=args.encode_batch_size,
        embedding_attribute=args.embedding_attribute,
        model_attribute=args.model_attribute,
        hash_attribute=args.hash_attribute,
        dry_run=args.dry_run, force=args.force)
    total = ProcessStats()
    if args.input_file:
        batch = []
        for r in _iter_input_records(args.input_file):
            batch.append(r)
            if len(batch) >= args.batch_size:
                total.merge(w.process_records(batch).stats); batch = []
        if batch:
            total.merge(w.process_records(batch).stats)
    else:
        for batch in w.scan_batches(batch_size=args.batch_size):
            total.merge(w.process_records(batch).stats)
    log.info("totals: %s", total.as_dict())
    return 0 if total.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
