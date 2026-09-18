


























import argparse
import json
import os
import struct
from typing import Optional

import boto3
import numpy as np


from matching_engine_local import (
    rank_candidates,
    passes_hard_filters,
    semantic_text,
    DEFAULT_EMBEDDING_MODEL,
    render_explanation,
)

DEFAULT_TABLE = "FoundReport"
DEFAULT_REGION = "ap-southeast-2"
DEFAULT_EMBEDDING_ATTRIBUTE = "embedding"
DEFAULT_MODEL_ATTRIBUTE = "embedding_model"


def unpack_embedding(value) -> np.ndarray:

    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, bytearray):
        value = bytes(value)
    if not isinstance(value, (bytes, bytearray)):
        raise TypeError(f"Embedding is not binary data: {type(value)!r}")
    if len(value) % 4 != 0:
        raise ValueError(f"Embedding byte length {len(value)} is not divisible by 4")
    return np.frombuffer(value, dtype="<f4").copy()


def scan_table(table):

    kwargs = {
        "ProjectionExpression": (
            "#id, #name, age, age_range, gender, height_cm, complexion, "
            "location, date_found, clothing, distinctive_marks, description, "
            "photo, embedding, embedding_model"
        ),
        "ExpressionAttributeNames": {
            "#id": "found_id",
            "#name": "name",
        },
    }

    records = []
    while True:
        response = table.scan(**kwargs)
        records.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return records


class DynamoDBMatchingEngine:


    def __init__(
        self,
        table_name: str = DEFAULT_TABLE,
        region: str = DEFAULT_REGION,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        embedding_attribute: str = DEFAULT_EMBEDDING_ATTRIBUTE,
        model_attribute: str = DEFAULT_MODEL_ATTRIBUTE,
        candidate_limit: int = 200,
        top_n_expensive: int = 20,
    ):
        self.table_name = table_name
        self.region = region
        self.model_name = model_name
        self.embedding_attribute = embedding_attribute
        self.model_attribute = model_attribute
        self.candidate_limit = candidate_limit
        self.top_n_expensive = top_n_expensive

        self.session = boto3.Session(region_name=region)
        self.table = self.session.resource("dynamodb").Table(table_name)
        self.records = []
        self.embeddings = None
        self.model = None
        self.dimension = None

    def _load_model(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
        return self.model

    def refresh_from_dynamodb(self):

        print(f"Loading FoundReport from DynamoDB: {self.table_name} ({self.region})")
        raw = scan_table(self.table)

        records = []
        vectors = []
        skipped_no_embedding = 0
        wrong_model = 0

        for record in raw:
            binary = record.get(self.embedding_attribute)
            if not binary:
                skipped_no_embedding += 1
                continue

            stored_model = record.get(self.model_attribute)
            if stored_model and stored_model != self.model_name:
                wrong_model += 1
                continue

            try:
                vector = unpack_embedding(binary)
            except (TypeError, ValueError):
                skipped_no_embedding += 1
                continue

            records.append(record)
            vectors.append(vector)

        if not vectors:
            raise RuntimeError(
                "No usable embeddings found in DynamoDB. Run build_embeddings_kaggle.py first."
            )

        dimension = len(vectors[0])
        if any(len(v) != dimension for v in vectors):
            raise RuntimeError("DynamoDB contains embeddings with different dimensions.")

        matrix = np.vstack(vectors).astype("float32")
        
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-12)

        self.records = records
        self.embeddings = matrix
        self.dimension = dimension

        print(f"Loaded indexed records : {len(records):,}")
        print(f"Skipped no embedding   : {skipped_no_embedding:,}")
        print(f"Skipped wrong model    : {wrong_model:,}")
        print(f"Embedding dimension    : {dimension}")
        print(f"RAM for vectors        : {matrix.nbytes / (1024 ** 2):.2f} MB")
        return self

    def _query_embedding(self, missing: dict):
        model = self._load_model()
        text = semantic_text(missing)
        vector = model.encode(
            [text],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0].astype("float32")
        if self.dimension is not None and len(vector) != self.dimension:
            raise RuntimeError(
                f"Query embedding dimension {len(vector)} != index dimension {self.dimension}"
            )
        return vector

    def search(self, missing: dict, candidate_limit: Optional[int] = None):

        if self.embeddings is None:
            self.refresh_from_dynamodb()

        q = self._query_embedding(missing)

        
        allowed = np.array(
            [passes_hard_filters(missing, r) for r in self.records],
            dtype=bool,
        )
        allowed_indices = np.flatnonzero(allowed)
        if len(allowed_indices) == 0:
            return []

        similarities = self.embeddings[allowed_indices] @ q
        k = min(candidate_limit or self.candidate_limit, len(allowed_indices))

        if k < len(allowed_indices):
            selected = np.argpartition(-similarities, k - 1)[:k]
        else:
            selected = np.arange(len(allowed_indices))
        selected = selected[np.argsort(-similarities[selected])]

        candidates = []
        for local_idx in selected:
            original_idx = int(allowed_indices[int(local_idx)])
            candidate = dict(self.records[original_idx])
            candidate["semantic_similarity"] = round(float(similarities[local_idx]), 4)
            candidates.append(candidate)

        
        results = rank_candidates(
            missing,
            candidates,
            top_n_expensive=self.top_n_expensive,
        )

        semantic_by_id = {
            str(c.get("found_id")): c.get("semantic_similarity")
            for c in candidates
        }
        for result in results:
            cid = str(result["candidate"].get("found_id"))
            result["semantic_similarity"] = semantic_by_id.get(cid)

        return results


def load_case(args):
    if args.case_file:
        with open(args.case_file, "r", encoding="utf-8") as f:
            return json.load(f)
    if args.query_json:
        return json.loads(args.query_json)
    raise ValueError("Provide --query-json or --case-file")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--region", default=os.getenv("AWS_DEFAULT_REGION", DEFAULT_REGION))
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--candidate-limit", type=int, default=200)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--top-n-expensive", type=int, default=20)
    parser.add_argument("--query-json")
    parser.add_argument("--case-file")
    args = parser.parse_args()

    missing = load_case(args)

    engine = DynamoDBMatchingEngine(
        table_name=args.table,
        region=args.region,
        model_name=args.model,
        candidate_limit=args.candidate_limit,
        top_n_expensive=args.top_n_expensive,
    )
    engine.refresh_from_dynamodb()

    print("\nSearching locally...\n")
    results = engine.search(missing)

    print(f"Top {min(args.top, len(results))} potential matches:\n")
    for rank, result in enumerate(results[:args.top], start=1):
        candidate = result["candidate"]
        print(f"#{rank}  {candidate.get('found_id')}  "
              f"Similarity Score: {result['similarity_score']}/100  "
              f"Semantic: {result.get('semantic_similarity')}")
        print(render_explanation(result))
        print("-" * 72)


if __name__ == "__main__":
    main()
