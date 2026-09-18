

import re
from datetime import datetime

BASE_URL = "https://zipnet.delhipolice.gov.in"
REDACT_PHONE_NUMBERS_IN_REMARKS = True
PHONE_PATTERN = re.compile(r"\b[6-9]\d{9}\b")


def redact_remarks(remarks):
    if not remarks or not REDACT_PHONE_NUMBERS_IN_REMARKS:
        return remarks
    return PHONE_PATTERN.sub("[REDACTED]", remarks)


def _to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _to_iso_date(s):
    if not s:
        return None
    try:
        d, m, y = s.strip().split("/")
        return f"{y}-{m}-{d}"
    except (ValueError, AttributeError):
        return s


def _resolve_age_range(af_raw, at_raw, height_cm=None):
    af, at = _to_int(af_raw), _to_int(at_raw)
    if af is None and at is None:
        return None
    if af == 0 and at not in (None, 0):
        return (at, at)
    if at == 0 and af not in (None, 0):
        return (af, af)
    if af == 0 and at == 0:
        if height_cm is not None and height_cm <= 70:
            return (0, 1)
        return None
    if af is None:
        return (at, at)
    if at is None:
        return (af, af)
    if at < af:
        return (af, af)
    return (af, at)


def normalize_record(raw, record_subtype="living",
                     id_field_raw="UnIdentifiedPersonId",
                     source_url_path="/Victims/UnIdentifiedPersons"):
    age_range = _resolve_age_range(raw.get("AgeFrom"), raw.get("AgeTo"),
                                   _to_int(raw.get("Height")))
    parts = [raw.get("DressUpperColor"), raw.get("DressUpper"),
             raw.get("DressLowerColor"), raw.get("DressLower")]
    clothing = " ".join(p for p in parts if p) or None
    desc = [
        f"Build: {raw['Build']}" if raw.get("Build") else None,
        f"Complexion: {raw['Complexion']}" if raw.get("Complexion") else None,
        f"Face: {raw['Face']}" if raw.get("Face") else None,
        f"Hair: {raw['Hair']}" if raw.get("Hair") else None,
        f"Beard: {raw['Beard']}" if raw.get("Beard") else None,
        f"Tattoo: {raw['Tattoo']}" if raw.get("Tattoo") else None,
    ]
    description = "; ".join(p for p in desc if p) or None
    name_raw = (raw.get("Name") or "").strip()
    name = None if name_raw.lower() in ("", "unknown") else name_raw
    now = datetime.now().astimezone().isoformat()
    return {
        "found_id": f"ZIPNET-{raw.get(id_field_raw)}",
        "source": "ZIPNET",
        "source_url": f"{BASE_URL}{source_url_path}",
        "record_subtype": record_subtype,
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
        "created_at": now,
        "last_updated_at": now,
    }


def normalize_missing_person_record(raw):
    age_range = _resolve_age_range(raw.get("AgeFrom"), raw.get("AgeTo"),
                                   _to_int(raw.get("Height")))
    parts = [raw.get("DressUpperColor"), raw.get("DressUpper"),
             raw.get("DressLowerColor"), raw.get("DressLower")]
    clothing = " ".join(p for p in parts if p) or None
    desc = [
        f"Build: {raw['Build']}" if raw.get("Build") else None,
        f"Complexion: {raw['Complexion']}" if raw.get("Complexion") else None,
        f"Face: {raw['Face']}" if raw.get("Face") else None,
        f"Hair: {raw['Hair']}" if raw.get("Hair") else None,
    ]
    description = "; ".join(p for p in desc if p) or None
    now = datetime.now().astimezone().isoformat()
    return {
        "case_id": f"ZIPNET-{raw.get('MissingPersonId')}",
        "source": "ZIPNET",
        "source_url": f"{BASE_URL}/Victims/MissingPersons",
        "reporter_user_id": None,
        "name": (raw.get("Name") or "").strip() or None,
        "gender": raw.get("Sex"),
        "age": _to_int(raw.get("Age")),
        "age_range": age_range,
        "height_cm": _to_int(raw.get("Height")),
        "complexion": raw.get("Complexion"),
        "clothing": clothing,
        "distinctive_marks": raw.get("IdentificationMarks"),
        "last_seen_location": raw.get("LastSeenPlace") or raw.get("PoliceStation"),
        "last_seen_date": _to_iso_date(raw.get("MissingDateTime") or raw.get("LastSeenDate")),
        "description": description,
        "photo_urls": [f"{BASE_URL}{u}" for u in (raw.get("ImageUrls") or [])],
        "state": raw.get("State"),
        "district": raw.get("District"),
        "police_station": raw.get("PoliceStation"),
        "status": "ACTIVE",
        "created_at": now,
        "last_checked_at": None,
        "next_check_at": now,
    }
