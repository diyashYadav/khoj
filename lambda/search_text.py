import base64
import json
import time
import uuid
import urllib.request
from pathlib import Path

import boto3

REGION = "ap-southeast-2"
MODEL_ID = "au.anthropic.claude-haiku-4-5-20251001-v1:0"
CPU_MATCHER_INSTANCE_ID = "i-0506afa068b36435c"
CPU_MATCHER_URL = "http://127.0.0.1:8000/search"
TOP_N = 5
ALLOWED_ORIGIN = "https://updated-frontend.duo3mqhyrqgnv.amplifyapp.com"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
transcribe = boto3.client("transcribe", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)

EXTRACTION_PROMPT = """
You are an information extraction system for Bharat Talaash,
a missing-person search platform.

Extract only information that is explicitly present or reasonably
described in the input.

Return ONLY valid JSON.

Use this exact structure:

{
  "name": null,
  "age": null,
  "gender": null,
  "last_seen_location": null,
  "last_seen_date": null,
  "clothing": null,
  "description": null,
  "original_language": null,
  "confidence_notes": null
}

Rules:

1. Do not invent facts.
2. Unknown fields must be null.
3. Age should preferably be numeric if clearly known.
4. Gender should be one of:
   "male", "female", "other", "unknown"
5. Keep useful visual details in description:
   complexion, height, build, hair, eyes, scars,
   marks, disabilities, accessories, etc.
6. Clothing should describe visible/reported clothing.
7. Preserve names and locations accurately.
8. Understand English, Hindi, Hinglish and Indian languages.
9. original_language should describe the language detected.
10. confidence_notes should briefly mention uncertain extraction.
11. Do not include markdown.
12. Do not include text outside the JSON object.
"""

def response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(payload, default=str),
    }

def normalize_event(event):
    if not isinstance(event, dict):
        return {}
    if "body" not in event:
        return event
    body = event.get("body")
    if body is None:
        return {}
    if event.get("isBase64Encoded") and isinstance(body, str):
        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return {}

def safe_json_parse(text):
    if not text:
        raise ValueError("Bedrock returned an empty response")
    text = text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Could not find JSON object in Bedrock response")
    return json.loads(text[start:end + 1])

def invoke_bedrock(messages):
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1200,
        "temperature": 0,
        "messages": messages,
    }
    result = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body),
        contentType="application/json",
        accept="application/json",
    )
    result_body = json.loads(result["body"].read())
    content = result_body.get("content", [])
    text_parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return "\n".join(text_parts).strip()

def extract_from_text(text):
    if not text or not str(text).strip():
        raise ValueError("text is required")
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": EXTRACTION_PROMPT + "\n\nINPUT:\n" + str(text),
                }
            ],
        }
    ]
    return safe_json_parse(invoke_bedrock(messages))

def get_image_media_type(s3_key):
    extension = Path(s3_key).suffix.lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mapping.get(extension, "image/jpeg")

def extract_from_image(bucket, key):
    if not bucket or not key:
        raise ValueError("s3_bucket and s3_key are required for image input")
    obj = s3.get_object(Bucket=bucket, Key=key)
    image_bytes = obj["Body"].read()
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    media_type = get_image_media_type(key)
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_base64,
                    },
                },
                {
                    "type": "text",
                    "text": EXTRACTION_PROMPT + """

The image may be a missing-person poster,
police notice, social-media poster, photograph,
or document.

Read visible text and also describe useful
visual characteristics when visible.
""",
                },
            ],
        }
    ]
    return safe_json_parse(invoke_bedrock(messages))

def get_media_format(s3_key):
    extension = Path(s3_key).suffix.lower().replace(".", "")
    mapping = {
        "mp3": "mp3",
        "mp4": "mp4",
        "m4a": "mp4",
        "wav": "wav",
        "flac": "flac",
        "ogg": "ogg",
        "amr": "amr",
        "webm": "webm",
    }
    media_format = mapping.get(extension)
    if not media_format:
        raise ValueError(f"Unsupported audio format: {extension}")
    return media_format

def transcribe_audio(bucket, key):
    if not bucket or not key:
        raise ValueError("s3_bucket and s3_key are required for audio input")
    job_name = "bharat-talaash-" + str(uuid.uuid4())
    media_uri = f"s3://{bucket}/{key}"
    media_format = get_media_format(key)
    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": media_uri},
        MediaFormat=media_format,
        IdentifyLanguage=True,
        LanguageOptions=[
            "hi-IN",
            "en-IN",
            "ta-IN",
            "te-IN",
            "mr-IN",
            "bn-IN",
            "gu-IN",
            "kn-IN",
            "ml-IN",
            "pa-IN",
        ],
    )
    for _ in range(50):
        result = transcribe.get_transcription_job(TranscriptionJobName=job_name)
        job = result["TranscriptionJob"]
        status = job["TranscriptionJobStatus"]
        if status == "COMPLETED":
            transcript_uri = job["Transcript"]["TranscriptFileUri"]
            with urllib.request.urlopen(transcript_uri, timeout=20) as resp:
                transcript_data = json.loads(resp.read().decode("utf-8"))
            transcripts = transcript_data.get("results", {}).get("transcripts", [])
            if not transcripts:
                raise RuntimeError("Transcription completed but no transcript was returned")
            transcript_text = transcripts[0].get("transcript", "").strip()
            if not transcript_text:
                raise RuntimeError("Audio transcript is empty")
            return transcript_text
        if status == "FAILED":
            raise RuntimeError(job.get("FailureReason", "Unknown transcription failure"))
        time.sleep(2)
    raise TimeoutError("Audio transcription timed out")

def build_matcher_query(extracted):
    query = {}
    excluded_fields = {"original_language", "confidence_notes"}
    for key, value in extracted.items():
        if key in excluded_fields:
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if key == "gender" and str(value).lower() == "unknown":
            continue
        query[key] = value
    return query

def search_cpu_matcher(matcher_query):
    matcher_payload = {"query": matcher_query, "top_n": TOP_N}
    encoded = base64.b64encode(json.dumps(matcher_payload).encode("utf-8")).decode("ascii")
    command = f"""
PAYLOAD=$(echo '{encoded}' | base64 -d)

curl --silent --show-error --fail \\
  --max-time 60 \\
  -X POST \\
  {CPU_MATCHER_URL} \\
  -H 'Content-Type: application/json' \\
  --data "$PAYLOAD"
""".strip()
    command_response = ssm.send_command(
        InstanceIds=[CPU_MATCHER_INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=90,
    )
    command_id = command_response["Command"]["CommandId"]
    for _ in range(120):
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=CPU_MATCHER_INSTANCE_ID,
            )
            status = result.get("Status")
            if status == "Success":
                output = result.get("StandardOutputContent", "").strip()
                if not output:
                    raise RuntimeError("CPU matcher returned empty output")
                return json.loads(output)
            if status in ("Failed", "Cancelled", "TimedOut", "Cancelling"):
                error = result.get("StandardErrorContent", "")
                raise RuntimeError(error or f"CPU matcher command failed: {status}")
        except ssm.exceptions.InvocationDoesNotExist:
            pass
        time.sleep(0.5)
    raise TimeoutError("CPU matcher timed out")

def lambda_handler(event, context):
    try:
        data = normalize_event(event)
        input_type = str(data.get("input_type", "")).strip().lower()
        if input_type not in ("text", "audio", "image"):
            return response(400, {"error": "input_type must be text, audio, or image"})
        transcript = None
        if input_type == "text":
            text = data.get("text")
            if not text:
                return response(400, {"error": "text is required for text input"})
            extracted = extract_from_text(text)
        elif input_type == "image":
            extracted = extract_from_image(data.get("s3_bucket"), data.get("s3_key"))
        else:
            transcript = transcribe_audio(data.get("s3_bucket"), data.get("s3_key"))
            extracted = extract_from_text(transcript)
        matcher_query = build_matcher_query(extracted)
        if not matcher_query:
            return response(
                422,
                {
                    "status": "no_searchable_information",
                    "query": extracted,
                    "matching": {"status": "not_run", "count": 0, "matches": []},
                },
            )
        matching = search_cpu_matcher(matcher_query)
        result = {"query": extracted, "status": "completed", "matching": matching}
        if transcript is not None:
            result["transcript"] = transcript
        return response(200, result)
    except json.JSONDecodeError as exc:
        return response(400, {"error": "Invalid JSON", "detail": str(exc)})
    except ValueError as exc:
        return response(400, {"error": str(exc)})
    except Exception as exc:
        print("SearchText error:", repr(exc))
        return response(500, {"error": "Search failed", "detail": str(exc)})
