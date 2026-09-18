

from __future__ import annotations
import logging
from typing import Optional
from embedding_worker import (
    EmbeddingWorker, ProcessResult, ProcessStats, handoff_to_matcher)

log = logging.getLogger("bharat_talaash.pipeline")
_worker_singleton: Optional[EmbeddingWorker] = None


def get_worker(**kw):
    global _worker_singleton
    if _worker_singleton is None:
        _worker_singleton = EmbeddingWorker(**kw)
        log.info("EmbeddingWorker init (table=%s, region=%s, model=%s)",
                 _worker_singleton.table_name, _worker_singleton.region,
                 _worker_singleton.model_name)
    return _worker_singleton


def embed_batch(records, worker=None, matcher_engine=None):
    if not records:
        return ProcessResult([], ProcessStats())
    w = worker or get_worker()
    result = w.process_records(records)
    log.info("embed_batch: processed=%d skipped=%d embedded=%d updated=%d failed=%d",
             result.stats.processed, result.stats.skipped,
             result.stats.embedded, result.stats.updated, result.stats.failed)
    if matcher_engine is not None and result.records:
        try:
            handoff_to_matcher(result.records, matcher_engine)
        except Exception as exc:
            log.error("matcher handoff failed: %s", exc)
    return result


class EmbeddingBatcher:
    def __init__(self, batch_size=1000, worker=None, matcher_engine=None):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.batch_size = int(batch_size)
        self.worker = worker
        self.matcher_engine = matcher_engine
        self._buffer = []
        self._stats_total = ProcessStats()

    def __call__(self, records):
        if not records: return
        self._buffer.extend(records)
        while len(self._buffer) >= self.batch_size:
            chunk = self._buffer[:self.batch_size]
            self._buffer = self._buffer[self.batch_size:]
            self._flush(chunk)

    def finalize(self):
        if not self._buffer: return
        chunk = self._buffer; self._buffer = []
        self._flush(chunk)

    @property
    def stats(self):
        return self._stats_total

    def _flush(self, records):
        try:
            r = embed_batch(records, worker=self.worker,
                            matcher_engine=self.matcher_engine)
        except Exception as exc:
            log.error("Batcher flush failed: %s", exc)
            self._stats_total.processed += len(records)
            self._stats_total.failed += len(records)
            for x in records:
                self._stats_total.failures.append({
                    "found_id": x.get("found_id"),
                    "reason": f"flush exception: {exc}"})
            return
        self._stats_total.merge(r.stats)
