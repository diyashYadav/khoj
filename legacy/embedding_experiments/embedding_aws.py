
































import argparse
import hashlib
import os
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from boto3.dynamodb.conditions import Key

MODEL_NAME_DEFAULT = "all-MiniLM-L6-v2"
EMBEDDING_ATTRIBUTE_DEFAULT = "embedding"
MODEL_ATTRIBUTE_DEFAULT = "embedding_model"
HASH_ATTRIBUTE_DEFAULT = "embedding_text_hash"

SEMANTIC_FIELDS = (
    "description",
    "clothing",
    "distinctive_marks",
    "location",
)


def get_aws_session(region: str):

    
    
    
    return boto3.Session(region_name=region)


def semantic_text(record: dict) -> str:
    labels = {
        "description": "description",
        "clothing": "clothing",
        "distinctive_marks": "distinctive marks",
        "location": "location",
    }
    parts = []
    for field in SEMANTIC_FIELDS:
        value = record.get(field)
        if value not in (None, "", [], {}):
            parts.append(f"{labels[field]}: {value}")
    return " | ".join(parts)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pack_embedding(vector) -> bytes:

    values = [float(x) for x in vector]
    return struct.pack(f"<{len(values)}f", *values)


def scan_records(table, projection_fields=None):

    fields = projection_fields or [
        "found_id", "description", "clothing", "distinctive_marks", "location",
        "embedding", "embedding_model", "embedding_text_hash",
    ]

    
    
    expr_names = {"#id": "found_id"}
    expr_fields = ["#id"]
    reserved = {"location", "name", "age", "gender"}
    for i, field in enumerate(fields):
        if field == "found_id":
            continue
        alias = f"#f{i}"
        expr_names[alias] = field
        expr_fields.append(alias)

    kwargs = {
        "ProjectionExpression": ", ".join(expr_fields),
        "ExpressionAttributeNames": expr_names,
    }

    records = []
    while True:
        response = table.scan(**kwargs)
        records.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
        print(f"  scanned {len(records):,} records...", flush=True)
    return records


def update_one(table, record, embedding_bytes, model_name, source_hash,
               embedding_attribute, model_attribute, hash_attribute):
    key = {"found_id": record["found_id"]}
    table.update_item(
        Key=key,
        UpdateExpression=(
            "SET #emb = :emb, #model = :model, #hash = :hash"
        ),
        ExpressionAttributeNames={
            "#emb": embedding_attribute,
            "#model": model_attribute,
            "#hash": hash_attribute,
        },
        ExpressionAttributeValues={
            ":emb": embedding_bytes,
            ":model": model_name,
            ":hash": source_hash,
        },
    )
    return record["found_id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default="FoundReport")
    parser.add_argument("--region", default=os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2"))
    parser.add_argument("--model", default=MODEL_NAME_DEFAULT)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--force", action="store_true",
                        help="Re-embed every record even if the same model/hash already exists")
    parser.add_argument("--embedding-attribute", default=EMBEDDING_ATTRIBUTE_DEFAULT)
    parser.add_argument("--model-attribute", default=MODEL_ATTRIBUTE_DEFAULT)
    parser.add_argument("--hash-attribute", default=HASH_ATTRIBUTE_DEFAULT)
    args = parser.parse_args()

    print("=" * 72)
    print("BHARAT TALAASH — AWS GPU EMBEDDING BUILDER")
    print("=" * 72)
    print(f"Region : {args.region}")
    print(f"Table  : {args.table}")
    print(f"Model  : {args.model}")

    session = get_aws_session(args.region)
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError(
            "AWS credentials not found. Configure Kaggle Secrets/environment "
            "or use an AWS credential provider available to boto3."
        )

    table = session.resource("dynamodb").Table(args.table)

    print("\nLoading records from DynamoDB...")
    records = scan_records(table)
    print(f"Loaded {len(records):,} records")

    
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device : {device}")
    if device == "cuda":
        print(f"GPU    : {torch.cuda.get_device_name(0)}")
    else:
        print("WARNING: CUDA is not available; embeddings will run on CPU.")

    print("\nLoading embedding model...")
    model = SentenceTransformer(args.model, device=device)

    
    
    todo = []
    skipped = 0
    for record in records:
        text = semantic_text(record)
        h = text_hash(text)
        if (
            not args.force
            and record.get(args.embedding_attribute)
            and record.get(args.model_attribute) == args.model
            and record.get(args.hash_attribute) == h
        ):
            skipped += 1
            continue
        todo.append((record, text, h))

    print(f"Already current : {skipped:,}")
    print(f"Need embedding   : {len(todo):,}")

    if not todo:
        print("\nNothing to update. DynamoDB is already up to date.")
        return

    texts = [x[1] for x in todo]
    print("\nGenerating embeddings...")
    embeddings = model.encode(
        texts,
        batch_size=args.batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype("float32")

    if embeddings.ndim != 2 or embeddings.shape[0] != len(todo):
        raise RuntimeError(f"Unexpected embedding shape: {embeddings.shape}")

    print(f"Embedding shape : {embeddings.shape}")
    print(f"Vector bytes    : {embeddings.shape[1] * 4:,} per record")

    
    
    print(f"\nWriting embeddings to DynamoDB with {args.workers} workers...")
    success = 0
    failed = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for (record, _text, h), vector in zip(todo, embeddings):
            packed = pack_embedding(vector)
            futures.append(pool.submit(
                update_one,
                table,
                record,
                packed,
                args.model,
                h,
                args.embedding_attribute,
                args.model_attribute,
                args.hash_attribute,
            ))

        for i, future in enumerate(as_completed(futures), start=1):
            try:
                future.result()
                success += 1
            except Exception as exc:
                failed.append(str(exc))
            if i % 250 == 0 or i == len(futures):
                print(f"  DynamoDB writes: {i:,}/{len(futures):,} | success={success:,} | failed={len(failed):,}", flush=True)

    print("\n" + "=" * 72)
    print("DONE")
    print("=" * 72)
    print(f"Total records : {len(records):,}")
    print(f"Skipped       : {skipped:,}")
    print(f"Updated       : {success:,}")
    print(f"Failed        : {len(failed):,}")

    if failed:
        print("\nFirst 10 errors:")
        for err in failed[:10]:
            print(" -", err)
        raise RuntimeError(f"{len(failed)} DynamoDB updates failed")

    print("\nAll embeddings are stored in FoundReport.")
    print("The AWS GPU matching engine can load them from DynamoDB and search locally.")


if __name__ == "__main__":
    main()
