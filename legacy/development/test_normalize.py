import json
from normalize_record import normalize_record


SAMPLE_RAW_RECORDS = [
    {"UnIdentifiedPersonId": 57368, "State": "DELHI", "District": "SOUTH WEST",
     "PoliceStation": "R. K. PURAM", "UIPFSerialNumber": "UIPF-202609000021",
     "FoundDateTime": "12/09/2026", "FoundPlace": "Munirka Metro Station Gate No. 2, R.K. Puram",
     "Sex": "Male", "AgeFrom": "35", "AgeTo": "36", "Name": "Unknown", "Height": "168",
     "Build": "Thin", "Complexion": "Fair", "Face": "Oval", "Hair": "Normal-Small-Black",
     "Beard": "Bearded", "Remarks": "IO Mob No.8168022439, 7065036222, 7065036262, RK Puram",
     "ImageUrls": ["/ImageUploads/2026/UIPFUploads/4b3accb5-638f-484b-90be-55637f6ee650.jpg"]},

    {"UnIdentifiedPersonId": 57365, "State": "DELHI", "District": "OUTER NORTH",
     "PoliceStation": "SAMAI PUR BADLI", "UIPFSerialNumber": "UIPF-202609000018",
     "FoundDateTime": "11/09/2026", "FoundPlace": "Sec-18, Rohini Metro Station Delhi",
     "Sex": "Male", "AgeFrom": "6", "AgeTo": "7", "Name": "Rohan", "Height": "74",
     "Build": "Normal", "Complexion": "Shallow", "Face": "Oval",
     "DressUpper": "BANIAN", "DressUpperColor": "GRAY",
     "DressLower": "TRACK SUIT LOWER", "DressLowerColor": "WHITE",
     "Remarks": None, "ImageUrls": ["/ImageUploads/2026/UIPFUploads/2ab5fdcd-e1de-45e3-811e-621fcc3ced67.jpg"]},

    {"UnIdentifiedPersonId": 57358, "State": "DELHI", "District": "NORTH DISTRICT",
     "PoliceStation": "CIVIL LINES", "UIPFSerialNumber": "UIPF-202609000012",
     "FoundDateTime": "03/09/2026", "FoundPlace": "GATE OF DELHI COUNCIL FOR CHILD WELFARE PALNA",
     "Sex": "Male", "AgeFrom": "0", "AgeTo": "0", "Name": "BHARAT", "Height": "51",
     "DressUpper": "T-SHIRT", "DressUpperColor": "CREAM",
     "Remarks": "HC VIKAS MOB NO. 8218922979",
     "ImageUrls": ["/ImageUploads/2026/UIPFUploads/684f2eb5-48ab-4548-83c4-7498218d2a80.jpg"]},
]

print("Testing the adapter on real sample records:\n")
for raw in SAMPLE_RAW_RECORDS:
    normalized = normalize_record(raw)
    print(json.dumps(normalized, indent=2, ensure_ascii=False))
    print()


r1 = normalize_record(SAMPLE_RAW_RECORDS[0])
assert r1["name"] is None, "‘Unknown’ should become None, not the literal string"
assert r1["age_range"] == (35, 36), f"expected (35, 36), got {r1['age_range']}"
assert "[REDACTED]" in r1["remarks"], "phone numbers in Remarks should be redacted by default"
assert "8168022439" not in r1["remarks"], "raw phone number must not leak through"

r2 = normalize_record(SAMPLE_RAW_RECORDS[1])
assert r2["name"] == "Rohan", "a real name should be preserved, not treated as unknown"
assert r2["clothing"] == "GRAY BANIAN WHITE TRACK SUIT LOWER"

print("All checks passed.")
