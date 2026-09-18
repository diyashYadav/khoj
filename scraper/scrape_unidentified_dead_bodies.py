

import logging, os
from normalize_record import normalize_record
from zipnet_common import BASE_URL, ZipnetScraper
from embedding_pipeline import EmbeddingBatcher

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

S3_BUCKET = os.getenv("ZIPNET_S3_BUCKET", "universe-test-1")
LIST_ENDPOINT = f"{BASE_URL}/Victims/GetUnIdentifiedDeadBodiesData/"
REFERER_PATH = "/Victims/UnIdentifiedDeadBodies"
SOURCE_URL_PATH = "/Victims/UnIdentifiedDeadBodies"

COLUMNS = [
    {"data": "UnIdentifiedDeadBodyId", "name": "UnIdentifiedDeadBodyId", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "true"},
    {"data": "", "name": "", "searchable": "false", "orderable": "false"},
    {"data": "ImageUrls", "name": "", "searchable": "true", "orderable": "true"},
    {"data": "State", "name": "State", "searchable": "true", "orderable": "false"},
    {"data": "District", "name": "District", "searchable": "true", "orderable": "false"},
    {"data": "PoliceStation", "name": "PoliceStation", "searchable": "true", "orderable": "false"},
    {"data": "DD_Date", "name": "DD date", "searchable": "true", "orderable": "false"},
    {"data": "UIDBSerialNumber", "name": "UIDBSerialNumber", "searchable": "true", "orderable": "false"},
    {"data": "FoundDateTime", "name": "FoundDateTime", "searchable": "true", "orderable": "false"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "false"},
    {"data": "", "name": "", "searchable": "true", "orderable": "false"},
]

INGEST_BATCH_SIZE = int(os.getenv("ZIPNET_INGEST_BATCH_SIZE", "1000"))
_env = os.environ.get("ZIPNET_MAX_PAGES", "0").strip()
MAX_PAGES = int(_env) if _env.isdigit() and int(_env) > 0 else None

_batcher = EmbeddingBatcher(batch_size=INGEST_BATCH_SIZE)

scraper = ZipnetScraper(
    name="unidentified_dead_bodies",
    list_endpoint=LIST_ENDPOINT,
    referer_path=REFERER_PATH,
    columns=COLUMNS,
    normalize_fn=lambda raw: normalize_record(
        raw, record_subtype="deceased",
        id_field_raw="UnIdentifiedDeadBodyId",
        source_url_path=SOURCE_URL_PATH),
    dynamodb_table="FoundReport",
    s3_bucket=S3_BUCKET,
    id_field="found_id",
    on_page_saved=_batcher,
)

if __name__ == "__main__":
    try:
        scraper.run(max_pages=MAX_PAGES)
    finally:
        _batcher.finalize()
    s = _batcher.stats
    print(f"\nEmbedding pipeline totals: processed={s.processed} "
          f"skipped={s.skipped} embedded={s.embedded} "
          f"updated={s.updated} failed={s.failed}")
    if s.failures:
        print("First 10 failures:")
        for f in s.failures[:10]:
            print("  -", f)
