import base64
import json
import time
from decimal import Decimal

import boto3

REGION = "ap-southeast-2"
INSTANCE_ID = "i-0643d91b9243e8779"
MATCH_TABLE = "Match"
GPU_VENV = "/home/ssm-user/bharat-talaash-gpu/bin/activate"
GPU_AUTOMATION_DIR = "/home/ssm-user/bharat-talaash/automation"

ec2 = boto3.client("ec2", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
match_table = dynamodb.Table(MATCH_TABLE)

def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError

def instance_state():
    result = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
    return result["Reservations"][0]["Instances"][0]["State"]["Name"]

def ensure_running():
    state = instance_state()
    if state == "stopped":
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
    elif state == "stopping":
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[INSTANCE_ID])
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
    if instance_state() != "running":
        ec2.get_waiter("instance_running").wait(InstanceIds=[INSTANCE_ID])

def wait_for_ssm(timeout_seconds=240):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [INSTANCE_ID]}]
        )
        info = response.get("InstanceInformationList", [])
        if info and info[0].get("PingStatus") == "Online":
            return
        time.sleep(5)
    raise TimeoutError("GPU instance did not become SSM Online")

def run_ssm(script_name, payload):
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    command = (
        f"cd {GPU_AUTOMATION_DIR} && "
        f". {GPU_VENV} && "
        f"python {script_name} --payload-b64 '{encoded}'"
    )
    response = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=840,
    )
    command_id = response["Command"]["CommandId"]
    for _ in range(1680):
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=INSTANCE_ID,
            )
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(0.5)
            continue
        status = result.get("Status")
        if status == "Success":
            stdout = result.get("StandardOutputContent", "")
            for line in reversed(stdout.splitlines()):
                if line.startswith("RESULT_JSON="):
                    return json.loads(line.split("=", 1)[1])
            raise RuntimeError("RESULT_JSON not found in GPU job output")
        if status in ("Failed", "Cancelled", "TimedOut", "Cancelling"):
            error = result.get("StandardErrorContent", "") or result.get("StandardOutputContent", "")
            raise RuntimeError(error or f"SSM command failed: {status}")
        time.sleep(0.5)
    raise TimeoutError("GPU SSM command timed out")

def save_job(job_id, mode, status, payload=None, result=None, error=None):
    item = {
        "match_id": job_id,
        "job_id": job_id,
        "mode": mode,
        "status": status,
        "updated_at": int(time.time()),
    }
    if payload is not None:
        item["payload"] = json.loads(json.dumps(payload, default=json_default), parse_float=Decimal)
    if result is not None:
        item["result"] = json.loads(json.dumps(result, default=json_default), parse_float=Decimal)
    if error is not None:
        item["error"] = str(error)
    match_table.put_item(Item=item)

def lambda_handler(event, context):
    job_id = str(event.get("job_id") or f"JOB-{int(time.time() * 1000)}")
    mode = str(event.get("mode") or "search").lower()
    payload = event.get("payload") or {}
    if mode not in ("search", "embed"):
        return {
            "statusCode": 400,
            "body": json.dumps({"job_id": job_id, "status": "failed", "error": "mode must be search or embed"}),
        }
    save_job(job_id, mode, "starting", payload=payload)
    try:
        ensure_running()
        wait_for_ssm()
        script_name = "gpu_embedding_job.py" if mode == "embed" else "gpu_job.py"
        result = run_ssm(script_name, payload)
        save_job(job_id, mode, "completed", payload=payload, result=result)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "job_id": job_id,
                    "mode": mode,
                    "status": "completed",
                    "result": result,
                },
                default=json_default,
            ),
        }
    except Exception as exc:
        save_job(job_id, mode, "failed", payload=payload, error=exc)
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "job_id": job_id,
                    "mode": mode,
                    "status": "failed",
                    "error": str(exc),
                }
            ),
        }
    finally:
        try:
            if instance_state() == "running":
                ec2.stop_instances(InstanceIds=[INSTANCE_ID])
        except Exception as stop_exc:
            print("GPU stop failed:", repr(stop_exc))
