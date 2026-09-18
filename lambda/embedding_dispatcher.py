import base64
import json
import time
import uuid

import boto3

REGION = "ap-southeast-2"
QUEUE_URL = "https://sqs.ap-southeast-2.amazonaws.com/743976413697/BharatTalaash-PendingEmbeddings"
GPU_CONTROLLER_FUNCTION = "BharatTalaash-GPUController"
CPU_MATCHER_INSTANCE_ID = "i-0506afa068b36435c"
MAX_MESSAGES_PER_JOB = 2000
MAX_EMPTY_RECEIVES = 3

sqs = boto3.client("sqs", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)

def receive_many_messages():
    messages = []
    empty_receives = 0
    while len(messages) < MAX_MESSAGES_PER_JOB and empty_receives < MAX_EMPTY_RECEIVES:
        remaining = MAX_MESSAGES_PER_JOB - len(messages)
        batch_size = min(10, remaining)
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=0,
            VisibilityTimeout=900,
        )
        batch = response.get("Messages", [])
        if not batch:
            empty_receives += 1
            time.sleep(0.1)
            continue
        empty_receives = 0
        messages.extend(batch)
    print("SQS messages received:", len(messages))
    return messages

def parse_found_ids(messages):
    found_ids = []
    seen = set()
    valid_messages = []
    for msg in messages:
        try:
            body = json.loads(msg["Body"])
            found_id = body.get("found_id")
            if not found_id:
                continue
            found_id = str(found_id)
            valid_messages.append(msg)
            if found_id not in seen:
                seen.add(found_id)
                found_ids.append(found_id)
        except Exception as exc:
            print("Invalid SQS message:", msg.get("MessageId"), repr(exc))
    print("Unique found_ids:", len(found_ids))
    return found_ids, valid_messages

def invoke_gpu(found_ids):
    payload = {
        "mode": "embed",
        "job_id": "EMBED-" + str(uuid.uuid4()),
        "payload": {"found_ids": found_ids},
    }
    print("Invoking GPU for", len(found_ids), "unique records")
    response = lambda_client.invoke(
        FunctionName=GPU_CONTROLLER_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = response["Payload"].read()
    result = json.loads(raw)
    print("GPUController statusCode:", result.get("statusCode"))
    return result

def refresh_cpu_matcher(found_ids):
    payload = {"found_ids": found_ids}
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    command = f"""
PAYLOAD=$(echo '{encoded}' | base64 -d)

curl --silent --show-error --fail \\
  --max-time 120 \\
  -X POST \\
  http://127.0.0.1:8000/refresh \\
  -H 'Content-Type: application/json' \\
  --data "$PAYLOAD"
""".strip()
    response = ssm.send_command(
        InstanceIds=[CPU_MATCHER_INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=180,
    )
    command_id = response["Command"]["CommandId"]
    print("CPU refresh command:", command_id)
    for _ in range(360):
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=CPU_MATCHER_INSTANCE_ID,
            )
            status = result["Status"]
            if status == "Success":
                output = result.get("StandardOutputContent", "").strip()
                if not output:
                    raise RuntimeError("CPU refresh returned empty output")
                parsed = json.loads(output)
                print("CPU refresh succeeded")
                return parsed
            if status in ("Failed", "Cancelled", "TimedOut", "Cancelling"):
                raise RuntimeError(
                    result.get("StandardErrorContent") or f"CPU refresh failed: {status}"
                )
        except ssm.exceptions.InvocationDoesNotExist:
            pass
        time.sleep(0.5)
    raise TimeoutError("CPU matcher refresh timed out")

def delete_messages(messages):
    total_deleted = 0
    for start in range(0, len(messages), 10):
        chunk = messages[start:start + 10]
        entries = [
            {"Id": str(i), "ReceiptHandle": msg["ReceiptHandle"]}
            for i, msg in enumerate(chunk)
        ]
        response = sqs.delete_message_batch(QueueUrl=QUEUE_URL, Entries=entries)
        successful = response.get("Successful", [])
        failed = response.get("Failed", [])
        total_deleted += len(successful)
        if failed:
            print("SQS delete failures:", json.dumps(failed))
    print("SQS messages deleted:", total_deleted)
    return total_deleted

def lambda_handler(event, context):
    messages = receive_many_messages()
    if not messages:
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "idle", "message_count": 0}),
        }
    found_ids, valid_messages = parse_found_ids(messages)
    if not found_ids:
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "no_valid_ids", "received": len(messages)}),
        }
    gpu_result = invoke_gpu(found_ids)
    status_code = gpu_result.get("statusCode", 500)
    body = gpu_result.get("body", "{}")
    try:
        body_json = json.loads(body)
    except Exception:
        body_json = {}
    gpu_success = status_code == 200 and body_json.get("status") == "completed"
    if not gpu_success:
        print("GPU unavailable or embedding failed. Messages remain in SQS.")
        return {
            "statusCode": 503,
            "body": json.dumps(
                {
                    "status": "retry_later",
                    "received_messages": len(messages),
                    "unique_found_ids": len(found_ids),
                    "gpu_response": body_json,
                }
            ),
        }
    try:
        refresh_result = refresh_cpu_matcher(found_ids)
    except Exception as exc:
        print("CPU refresh failed:", repr(exc))
        return {
            "statusCode": 503,
            "body": json.dumps(
                {
                    "status": "refresh_retry_later",
                    "received_messages": len(messages),
                    "unique_found_ids": len(found_ids),
                    "error": str(exc),
                }
            ),
        }
    deleted = delete_messages(valid_messages)
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": "completed",
                "received_messages": len(messages),
                "unique_found_ids": len(found_ids),
                "deleted_messages": deleted,
                "gpu": body_json,
                "cpu_refresh": refresh_result,
            }
        ),
    }
