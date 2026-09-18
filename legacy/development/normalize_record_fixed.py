





import re

BASE_URL = "https://zipnet.delhipolice.gov.in"

REDACT_PHONE_NUMBERS_IN_REMARKS = True
PHONE_PATTERN = re.compile(r"\b[6-9]\d{9}\b")


def redact_remarks(remarks):
    if not remarks or not REDACT_PHONE_NUMBERS_IN_REMARKS:
        return remarks
    return PHONE_PATTERN.sub("[REDACTED]", remarks)


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_iso_date(ddmmyyyy):
    if not ddmmyyyy:
        return None
    try:
        d, m, y = ddmmyyyy.strip().split("/")
        
        from datetime import datetime
        return datetime.strptime(f"{d}/{m}/{y}", "%d/%m/%Y").date().isoformat()
    except (ValueError, AttributeError, TypeError):
        return None


def _to_age_range(age_from, age_to):






    af = _to_int(age_from)
    at = _to_int(age_to)

    
    if af is not None and af <= 0:
        af = None
    if at is not None and at <= 0:
        at = None

    if af is None and at is None:
        return None

    if af is None:
        return (at, at)

    if at is None:
        return (af, af)

    
    
    if at < af:
        af, at = at, af

    return (af, at)


def normalize_record(raw: dict) -> dict:
    age_range = _to_age_range(raw.get("AgeFrom"), raw.get("AgeTo"))

    clothing_parts = [raw.get("DressUpperColor"), raw.get("DressUpper"),
                       raw.get("DressLowerColor"), raw.get("DressLower")]
    clothing = " ".join(p for p in clothing_parts if p) or None

    description_parts = [
        f"Build: {raw['Build']}" if raw.get("Build") else None,
        f"Complexion: {raw['Complexion']}" if raw.get("Complexion") else None,
        f"Face: {raw['Face']}" if raw.get("Face") else None,
        f"Hair: {raw['Hair']}" if raw.get("Hair") else None,
        f"Beard: {raw['Beard']}" if raw.get("Beard") else None,
        f"Tattoo: {raw['Tattoo']}" if raw.get("Tattoo") else None,
    ]
    description = "; ".join(p for p in description_parts if p) or None

    name_raw = (raw.get("Name") or "").strip()
    name = None if name_raw.lower() in ("", "unknown") else name_raw

    return {
        "found_id": f"ZIPNET-{raw.get('UnIdentifiedPersonId')}",
        "source": "ZIPNET",
        "source_url": f"{BASE_URL}/Victims/UnIdentifiedPersons",
        "name": name,
        "gender": raw.get("Sex"),
        "age_range": age_range,
        "height_cm": _to_int(raw.get("Height")),
        "complexion": raw.get("Complexion"),
        "clothing": clothing,
        "distinctive_marks": raw.get("Tattoo") or raw.get("PhysicalDetails"),
        "location": raw.get("FoundPlace") or raw.get("PoliceStation"),
        "date_found": _to_iso_date(raw.get("FoundDateTime")),
        "description": description,
        "remarks": redact_remarks(raw.get("Remarks")),
        "photo_urls": [f"{BASE_URL}{u}" for u in (raw.get("ImageUrls") or [])],
        "state": raw.get("State"),
        "district": raw.get("District"),
        "police_station": raw.get("PoliceStation"),
    }
