












from normalize_record import normalize_record
from zipnet_common import BASE_URL, ZipnetScraper

S3_BUCKET = "PASTE_YOUR_BUCKET_NAME_HERE"


LIST_ENDPOINT = f"{BASE_URL}/Victims/GetUnIdentifiedDeadBodiesData/"
REFERER_PATH = "/Victims/UnIdentifiedDeadBodies"



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

scraper = ZipnetScraper(
    name="unidentified_dead_bodies",
    list_endpoint=LIST_ENDPOINT,
    referer_path=REFERER_PATH,
    columns=COLUMNS,
    normalize_fn=lambda raw: normalize_record(raw, record_subtype="deceased",
                                               id_field_raw="UnIdentifiedDeadBodyId"),
    dynamodb_table="FoundReport",
    s3_bucket=S3_BUCKET,
    id_field="found_id",
)

if __name__ == "__main__":
    scraper.run()
