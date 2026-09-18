







from normalize_record import normalize_record
from zipnet_common import BASE_URL, ZipnetScraper

S3_BUCKET = "PASTE_YOUR_BUCKET_NAME_HERE"

COLUMNS = [
    {"data": "UnIdentifiedPersonId", "name": "UnIdentifiedPersonId", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "true"},
    {"data": "", "name": "", "searchable": "false", "orderable": "false"},
    {"data": "ImageUrls", "name": "", "searchable": "true", "orderable": "true"},
    {"data": "State", "name": "State", "searchable": "true", "orderable": "false"},
    {"data": "District", "name": "District", "searchable": "true", "orderable": "false"},
    {"data": "PoliceStation", "name": "PoliceStation", "searchable": "true", "orderable": "false"},
    {"data": "DDNo", "name": "DDNo", "searchable": "true", "orderable": "false"},
    {"data": "DD_Date", "name": "DD_Date", "searchable": "true", "orderable": "false"},
    {"data": "UIPFSerialNumber", "name": "UIPFSerialNumber", "searchable": "true", "orderable": "true"},
    {"data": "FoundDateTime", "name": "FoundDateTime", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "false"},
    {"data": "", "name": "", "searchable": "true", "orderable": "false"},
]

scraper = ZipnetScraper(
    name="unidentified_persons",
    list_endpoint=f"{BASE_URL}/Victims/GetUnIdentifiedPersonsData/",
    referer_path="/Victims/UnIdentifiedPersons",
    columns=COLUMNS,
    normalize_fn=lambda raw: normalize_record(raw, record_subtype="living"),
    dynamodb_table="FoundReport",
    s3_bucket=S3_BUCKET,
    id_field="found_id",
)

if __name__ == "__main__":
    scraper.run()
