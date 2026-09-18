









from normalize_record import normalize_missing_person_record
from zipnet_common import BASE_URL, ZipnetScraper

S3_BUCKET = "PASTE_YOUR_BUCKET_NAME_HERE"

LIST_ENDPOINT = f"{BASE_URL}/Victims/GetMissingPersonsData/"
REFERER_PATH = "/Victims/MissingPersons"



COLUMNS = [
    {"data": "MissingPersonId", "name": "MissingPersonId", "searchable": "true", "orderable": "true"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "true"},
    {"data": "", "name": "", "searchable": "false", "orderable": "false"},
    {"data": "ImageUrls", "name": "", "searchable": "false", "orderable": "false"},
    {"data": "State", "name": "State", "searchable": "true", "orderable": "false"},
    {"data": "District", "name": "District", "searchable": "true", "orderable": "false"},
    {"data": "PoliceStation", "name": "Police Station", "searchable": "true", "orderable": "false"},
    {"data": "FIRNo", "name": "FIRNo", "searchable": "true", "orderable": "false"},
    {"data": "DD_Date", "name": "DD_Date", "searchable": "true", "orderable": "false"},
    {"data": "SerialNumber", "name": "SerialNumber", "searchable": "true", "orderable": "false"},
    {"data": "MissingFrom", "name": "MissingFrom", "searchable": "true", "orderable": "false"},
    {"data": "TracingStatus", "name": "TracingStatus", "searchable": "true", "orderable": "false"},
    {"data": "CreatedOn", "name": "CreatedOn", "searchable": "true", "orderable": "false"},
    {"data": "", "name": "", "searchable": "true", "orderable": "false"},
]



ORDER = [{"column": 1, "dir": "desc"}]
START = 0
LENGTH = 10
SEARCH_VALUE = ""
SEARCH_REGEX = "false"
SEARCH_FORM_JSON = "{}"

scraper = ZipnetScraper(
    name="missing_persons",
    list_endpoint=LIST_ENDPOINT,
    referer_path=REFERER_PATH,
    columns=COLUMNS,
    normalize_fn=normalize_missing_person_record,
    dynamodb_table="MissingCase",
    s3_bucket=S3_BUCKET,
    id_field="case_id",
)

if __name__ == "__main__":
    scraper.run()
