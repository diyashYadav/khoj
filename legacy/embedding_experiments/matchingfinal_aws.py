




























import argparse
import json
import os
from decimal import Decimal

import boto3
import numpy as np


DEFAULT_TABLE = "FoundReport"
DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CACHE = "./foundreport_embedding_cache.npz"






def setup_aws_credentials():





    return None

def make_aws_session(region):
    setup_aws_credentials()
    return boto3.Session(region_name=region)






def detect_device():
    import torch

    if torch.cuda.is_available():
        print("GPU detected:")
        print(f"  Device : {torch.cuda.get_device_name(0)}")
        print(f"  CUDA   : {torch.version.cuda}")
        return "cuda"

    print("CUDA not available. Using CPU.")
    return "cpu"






def normalize_model_name(name):
    if not name:
        return ""

    name = str(name).strip().lower()

    prefixes = (
        "sentence-transformers/",
        "sentence_transformers/",
    )

    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]

    return name


def models_are_compatible(a, b):
    return normalize_model_name(a) == normalize_model_name(b)






def decode_embedding(value):








    if hasattr(value, "value"):
        value = value.value

    if isinstance(value, bytearray):
        value = bytes(value)

    if isinstance(value, bytes):
        if len(value) % 4 != 0:
            raise ValueError(
                f"Embedding binary length {len(value)} "
                "is not divisible by 4."
            )

        return np.frombuffer(
            value,
            dtype="<f4",
        ).copy()

    
    
    if isinstance(value, (list, tuple)):
        return np.asarray(
            [float(x) for x in value],
            dtype="float32",
        )

    raise TypeError(
        f"Unsupported embedding type: {type(value)}"
    )






def scan_table(table):










    print("\nScanning DynamoDB...")

    records = []
    page = 0
    scan_kwargs = {}

    while True:
        page += 1
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        records.extend(items)

        print(f"  DynamoDB page {page}: {len(items)} records")

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break

        scan_kwargs["ExclusiveStartKey"] = last_key

    print(f"\nTotal DynamoDB records: {len(records):,}")
    return records






def make_json_safe(obj):
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)

    if isinstance(obj, dict):
        return {
            str(k): make_json_safe(v)
            for k, v in obj.items()
            if k not in ("embedding", "embedding_model")
        }

    if isinstance(obj, list):
        return [make_json_safe(x) for x in obj]

    if isinstance(obj, tuple):
        return [make_json_safe(x) for x in obj]

    if isinstance(obj, bytes):
        return "<binary>"

    return obj


def save_cache(path, records, embeddings, model_name):
    print("\nSaving embedding cache:")
    print(f"  {path}")

    safe_records = [
        make_json_safe(record)
        for record in records
    ]

    np.savez_compressed(
        path,
        embeddings=np.asarray(
            embeddings,
            dtype="float32",
        ),
        records=np.array(
            json.dumps(
                safe_records,
                ensure_ascii=False,
            ),
            dtype=object,
        ),
        model=np.array(
            model_name,
            dtype=object,
        ),
    )

    print("Cache saved.")


def load_cache(path, requested_model):
    if not os.path.exists(path):
        return None

    print("\nLoading cached embeddings:")
    print(f"  {path}")

    try:
        data = np.load(
            path,
            allow_pickle=True,
        )

        cached_model = str(
            data["model"].item()
        )

        if not models_are_compatible(
            cached_model,
            requested_model,
        ):
            print(
                "Cache model mismatch. "
                "Ignoring existing cache."
            )
            print(f"  Cache    : {cached_model}")
            print(f"  Requested: {requested_model}")
            return None

        embeddings = np.asarray(
            data["embeddings"],
            dtype="float32",
        )

        records = json.loads(
            data["records"].item()
        )

        if embeddings.ndim != 2:
            raise ValueError(
                f"Invalid cached shape: {embeddings.shape}"
            )

        if len(records) != len(embeddings):
            raise ValueError(
                "Cached records and embeddings count mismatch."
            )

        print(f"Cached records  : {len(records):,}")
        print(f"Embedding shape : {embeddings.shape}")
        print(f"Cached model    : {cached_model}")

        return records, embeddings

    except Exception as exc:
        print(f"Cache load failed: {exc}")
        return None






def build_query_text(case):
    parts = []

    fields = [
        ("name", "Name"),
        ("age", "Age"),
        ("age_range", "Age range"),
        ("gender", "Gender"),
        ("complexion", "Complexion"),
        ("height_cm", "Height"),
        ("last_seen_location", "Last seen location"),
        ("last_seen_date", "Last seen date"),
        ("clothing", "Clothing"),
        ("distinctive_marks", "Distinctive marks"),
        ("description", "Description"),
    ]

    for key, label in fields:
        value = case.get(key)

        if value is None:
            continue

        if str(value).strip() == "":
            continue

        parts.append(f"{label}: {value}")

    if not parts:
        parts.append(
            json.dumps(
                case,
                ensure_ascii=False,
            )
        )

    return ". ".join(parts)






class QueryEmbedder:

    def __init__(self, model_name, device):
        self.model_name = model_name
        self.device = device
        self.model = None

    def load(self):
        if self.model is not None:
            return self.model

        from sentence_transformers import SentenceTransformer

        print("\nLoading SentenceTransformer...")
        print(f"  Model : {self.model_name}")
        print(f"  Device: {self.device}")

        self.model = SentenceTransformer(
            self.model_name,
            device=self.device,
        )

        return self.model

    def encode(self, texts, batch_size=64):
        model = self.load()

        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return np.asarray(
            embeddings,
            dtype="float32",
        )






def norm(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def flatten_age(value):

    if value is None:
        return None

    if isinstance(value, (list, tuple)) and value:
        try:
            nums = [float(x) for x in value]
            return sum(nums) / len(nums)
        except Exception:
            return None

    try:
        return float(value)
    except Exception:
        return None


def text_tokens(value):
    if value is None:
        return set()

    text = norm(value)
    for ch in ",.;:/\\-_()[]{}":
        text = text.replace(ch, " ")

    return {
        x for x in text.split()
        if len(x) > 1
    }


def token_overlap(a, b):
    a_words = text_tokens(a)
    b_words = text_tokens(b)

    if not a_words or not b_words:
        return 0.0

    return len(a_words & b_words) / len(a_words)


def text_similarity(a, b):




    a_words = text_tokens(a)
    b_words = text_tokens(b)

    if not a_words or not b_words:
        return 0.0

    intersection = len(a_words & b_words)
    union = len(a_words | b_words)

    if union == 0:
        return 0.0

    return intersection / union


def passes_filters(query, candidate):







    q_gender = norm(query.get("gender"))
    c_gender = norm(candidate.get("gender"))

    if q_gender and c_gender:
        if q_gender != c_gender:
            return False

    return True


def structured_match(query, candidate):











    
    weights = {
        "gender": 15.0,
        "age": 15.0,
        "complexion": 10.0,
        "height_cm": 10.0,
        "clothing": 20.0,
        "distinctive_marks": 25.0,
        "location": 5.0,
    }

    matched_weight = 0.0
    comparable_weight = 0.0
    query_available_weight = 0.0

    details = {}

    
    
    
    q = norm(query.get("gender"))
    c = norm(candidate.get("gender"))

    if q:
        query_available_weight += weights["gender"]

    if q and c:
        comparable_weight += weights["gender"]

        if q == c:
            matched_weight += weights["gender"]
            details["gender"] = "match"
        else:
            details["gender"] = "conflict"

    elif q:
        details["gender"] = "missing_candidate"

    
    
    
    q_age = flatten_age(query.get("age"))
    c_age = flatten_age(candidate.get("age"))

    if c_age is None:
        c_age = flatten_age(candidate.get("age_range"))

    if q_age is not None:
        query_available_weight += weights["age"]

    if q_age is not None and c_age is not None:
        comparable_weight += weights["age"]

        diff = abs(q_age - c_age)

        if diff == 0:
            contribution = weights["age"]
            details["age"] = "exact"
        elif diff <= 2:
            contribution = weights["age"] * 0.80
            details["age"] = f"close ({diff:g} years)"
        elif diff <= 5:
            contribution = weights["age"] * 0.50
            details["age"] = f"moderate ({diff:g} years)"
        elif diff <= 8:
            contribution = weights["age"] * 0.20
            details["age"] = f"weak ({diff:g} years)"
        else:
            contribution = 0.0
            details["age"] = f"far ({diff:g} years)"

        matched_weight += contribution

    elif q_age is not None:
        details["age"] = "missing_candidate"

    
    
    
    q = norm(query.get("complexion"))
    c = norm(candidate.get("complexion"))

    if q:
        query_available_weight += weights["complexion"]

    if q and c:
        comparable_weight += weights["complexion"]

        if q in c or c in q:
            matched_weight += weights["complexion"]
            details["complexion"] = "match"
        else:
            details["complexion"] = "different"

    elif q:
        details["complexion"] = "missing_candidate"

    
    
    
    q_height = flatten_age(query.get("height_cm"))
    c_height = flatten_age(candidate.get("height_cm"))

    if q_height is not None:
        query_available_weight += weights["height_cm"]

    if q_height is not None and c_height is not None:
        comparable_weight += weights["height_cm"]

        diff = abs(q_height - c_height)

        if diff <= 2:
            matched_weight += weights["height_cm"]
            details["height_cm"] = "very close"
        elif diff <= 5:
            matched_weight += weights["height_cm"] * 0.70
            details["height_cm"] = "close"
        elif diff <= 10:
            matched_weight += weights["height_cm"] * 0.35
            details["height_cm"] = "moderate"
        else:
            details["height_cm"] = "different"

    elif q_height is not None:
        details["height_cm"] = "missing_candidate"

    
    
    
    q = query.get("clothing")
    c = candidate.get("clothing")

    if q:
        query_available_weight += weights["clothing"]

    if q and c:
        comparable_weight += weights["clothing"]

        overlap = token_overlap(q, c)

        if overlap >= 0.60:
            contribution = weights["clothing"]
            details["clothing"] = "strong"
        elif overlap >= 0.30:
            contribution = weights["clothing"] * 0.65
            details["clothing"] = "partial"
        elif overlap > 0:
            contribution = weights["clothing"] * 0.25
            details["clothing"] = "weak"
        else:
            contribution = 0.0
            details["clothing"] = "no token overlap"

        matched_weight += contribution

    elif q:
        details["clothing"] = "missing_candidate"

    
    
    
    q = query.get("distinctive_marks")
    c = candidate.get("distinctive_marks")

    if q:
        query_available_weight += weights["distinctive_marks"]

    if q and c:
        comparable_weight += weights["distinctive_marks"]

        overlap = token_overlap(q, c)

        if overlap >= 0.60:
            contribution = weights["distinctive_marks"]
            details["distinctive_marks"] = "strong"
        elif overlap >= 0.30:
            contribution = weights["distinctive_marks"] * 0.65
            details["distinctive_marks"] = "partial"
        elif overlap > 0:
            contribution = weights["distinctive_marks"] * 0.25
            details["distinctive_marks"] = "weak"
        else:
            contribution = 0.0
            details["distinctive_marks"] = "no token overlap"

        matched_weight += contribution

    elif q:
        details["distinctive_marks"] = "missing_candidate"

    
    
    
    q = query.get("last_seen_location")
    c = candidate.get("location")

    if q:
        query_available_weight += weights["location"]

    if q and c:
        comparable_weight += weights["location"]

        q_tokens = text_tokens(q)
        c_tokens = text_tokens(c)

        if q_tokens and c_tokens:
            overlap = len(q_tokens & c_tokens) / len(q_tokens)

            if overlap >= 0.50:
                matched_weight += weights["location"]
                details["location"] = "strong"
            elif overlap > 0:
                matched_weight += weights["location"] * 0.50
                details["location"] = "partial"
            else:
                details["location"] = "different"
        else:
            details["location"] = "unusable"

    elif q:
        details["location"] = "missing_candidate"

    
    if comparable_weight > 0:
        score = (
            matched_weight / comparable_weight
        ) * 100.0
    else:
        score = 0.0

    
    if query_available_weight > 0:
        completeness = (
            comparable_weight / query_available_weight
        ) * 100.0
    else:
        completeness = 0.0

    return {
        "score": round(score, 2),
        "comparable_weight": round(comparable_weight, 2),
        "query_available_weight": round(
            query_available_weight,
            2,
        ),
        "completeness": round(
            completeness,
            2,
        ),
        "details": details,
    }







class MatchingEngine:

    def __init__(
        self,
        table_name,
        region,
        model_name,
        batch_size,
        cache_path,
        refresh_cache=False,
    ):
        self.table_name = table_name
        self.region = region
        self.model_name = model_name
        self.batch_size = batch_size
        self.cache_path = cache_path
        self.refresh_cache = refresh_cache

        self.device = detect_device()

        self.session = make_aws_session(
            region
        )

        self.table = self.session.resource(
            "dynamodb"
        ).Table(table_name)

        self.records = []
        self.embeddings = None
        self.dimension = None

        self.embedder = QueryEmbedder(
            model_name,
            self.device,
        )

    
    
    

    def load_index(self):

        if not self.refresh_cache:

            cached = load_cache(
                self.cache_path,
                self.model_name,
            )

            if cached is not None:

                self.records, self.embeddings = cached

                self.dimension = (
                    self.embeddings.shape[1]
                )

                
                norms = np.linalg.norm(
                    self.embeddings,
                    axis=1,
                    keepdims=True,
                )

                self.embeddings /= np.maximum(
                    norms,
                    1e-12,
                )

                print(
                    f"\nUsing cached index: "
                    f"{len(self.records):,} records"
                )

                print(
                    f"Embedding dimension: "
                    f"{self.dimension}"
                )

                return

        raw = scan_table(self.table)

        records = []
        vectors = []

        skipped_no_embedding = 0
        skipped_bad_embedding = 0
        skipped_wrong_model = 0

        observed_models = {}

        for record in raw:

            embedding = record.get(
                "embedding"
            )

            if embedding is None:
                skipped_no_embedding += 1
                continue

            stored_model = record.get(
                "embedding_model"
            )

            model_key = str(
                stored_model
            ) if stored_model else "<missing>"

            observed_models[model_key] = (
                observed_models.get(
                    model_key,
                    0,
                ) + 1
            )

            
            
            
            
            
            if (
                stored_model
                and not models_are_compatible(
                    stored_model,
                    self.model_name,
                )
            ):
                skipped_wrong_model += 1
                continue

            try:
                vector = decode_embedding(
                    embedding
                )

            except Exception:
                skipped_bad_embedding += 1
                continue

            records.append(record)
            vectors.append(vector)

        print("\nEmbedding models found in DynamoDB:")

        for model, count in sorted(
            observed_models.items(),
            key=lambda x: -x[1],
        ):
            print(
                f"  {model}: {count:,}"
            )

        if not vectors:
            raise RuntimeError(
                "\nNo usable embeddings found.\n"
                "The DynamoDB embedding field exists, but "
                "the records could not be decoded or the "
                "stored embedding model did not match."
            )

        dimension = len(vectors[0])

        bad_dimensions = sum(
            len(v) != dimension
            for v in vectors
        )

        if bad_dimensions:
            raise RuntimeError(
                f"DynamoDB contains {bad_dimensions} "
                "embeddings with inconsistent dimensions."
            )

        matrix = np.vstack(
            vectors
        ).astype("float32")

        norms = np.linalg.norm(
            matrix,
            axis=1,
            keepdims=True,
        )

        matrix /= np.maximum(
            norms,
            1e-12,
        )

        self.records = records
        self.embeddings = matrix
        self.dimension = dimension

        print(
            f"\nLoaded indexed records : "
            f"{len(records):,}"
        )

        print(
            f"Skipped no embedding   : "
            f"{skipped_no_embedding:,}"
        )

        print(
            f"Skipped wrong model    : "
            f"{skipped_wrong_model:,}"
        )

        print(
            f"Skipped bad embedding  : "
            f"{skipped_bad_embedding:,}"
        )

        print(
            f"Embedding dimension    : "
            f"{dimension}"
        )

        print(
            "RAM for embeddings     : "
            f"{matrix.nbytes / (1024 ** 2):.2f} MB"
        )

        save_cache(
            self.cache_path,
            self.records,
            self.embeddings,
            self.model_name,
        )

    
    
    

    def create_query_embedding(self, case):

        query_text = build_query_text(
            case
        )

        print("\nQuery text:")
        print(query_text)

        vector = self.embedder.encode(
            [query_text],
            batch_size=self.batch_size,
        )[0]

        if len(vector) != self.dimension:
            raise RuntimeError(
                f"\nDimension mismatch:\n"
                f"  Query embedding : {len(vector)}\n"
                f"  DB embedding    : {self.dimension}\n"
                f"\nMake sure the query model is the same "
                f"model used to create DynamoDB embeddings."
            )

        return vector

    
    
    

    def similarity(self, query_vector):

        import torch

        if (
            self.device == "cuda"
            and torch.cuda.is_available()
        ):
            print(
                "\nRunning cosine similarity on GPU..."
            )

            db_tensor = torch.from_numpy(
                self.embeddings
            ).to(
                "cuda",
                non_blocking=True,
            )

            query_tensor = torch.from_numpy(
                query_vector
            ).to(
                "cuda",
                non_blocking=True,
            )

            with torch.inference_mode():
                scores = (
                    db_tensor
                    @ query_tensor
                )

            result = (
                scores
                .detach()
                .cpu()
                .numpy()
            )

            del db_tensor
            del query_tensor
            del scores

            torch.cuda.empty_cache()

            return result

        print(
            "\nRunning cosine similarity on CPU..."
        )

        return (
            self.embeddings
            @ query_vector
        )

    
    
    

    def search(
        self,
        case,
        top_n=10,
    ):

        query_vector = (
            self.create_query_embedding(
                case
            )
        )

        allowed = []

        for i, record in enumerate(
            self.records
        ):
            if passes_filters(
                case,
                record,
            ):
                allowed.append(i)

        if not allowed:
            print(
                "\nNo candidates passed "
                "the structured filters."
            )
            return []

        all_scores = self.similarity(
            query_vector
        )

        results = []

        for index in allowed:

            candidate = self.records[
                index
            ]

            cosine = float(
                all_scores[index]
            )

            
            
            
            semantic_score = max(
                0.0,
                min(
                    100.0,
                    ((cosine + 1.0) / 2.0)
                    * 100.0,
                ),
            )

            structured = structured_match(
                case,
                candidate,
            )

            structured_score = structured[
                "score"
            ]

            completeness = structured[
                "completeness"
            ]

            
            
            
            
            
            
            evidence_factor = min(
                1.0,
                completeness / 100.0,
            )

            effective_structured = (
                structured_score
                * evidence_factor
            )

            final_score = (
                0.80 * semantic_score
                + 0.20 * effective_structured
            )

            results.append(
                {
                    "candidate": candidate,
                    "semantic_similarity": round(
                        cosine,
                        4,
                    ),
                    "semantic_score": round(
                        semantic_score,
                        2,
                    ),
                    "structured_score": round(
                        structured_score,
                        2,
                    ),
                    "effective_structured_score": round(
                        effective_structured,
                        2,
                    ),
                    "data_completeness": round(
                        completeness,
                        2,
                    ),
                    "final_score": round(
                        final_score,
                        2,
                    ),
                    "structured_details": structured[
                        "details"
                    ],
                }
            )

        results.sort(
            key=lambda x: x["final_score"],
            reverse=True,
        )

        return results[:top_n]






def print_results(results):

    print("\n" + "=" * 72)
    print(
        f"TOP {len(results)} MATCHES"
    )
    print("=" * 72)

    if not results:
        print(
            "\nNo matching candidates found."
        )
        return

    for rank, result in enumerate(
        results,
        start=1,
    ):

        candidate = result[
            "candidate"
        ]

        print(
            f"\n#{rank}"
        )

        print("-" * 72)

        print(
            f"Found ID          : "
            f"{candidate.get('found_id')}"
        )

        print(
            f"Name              : "
            f"{candidate.get('name')}"
        )

        print(
            f"Age               : "
            f"{candidate.get('age')}"
        )

        print(
            f"Age range         : "
            f"{candidate.get('age_range')}"
        )

        print(
            f"Gender            : "
            f"{candidate.get('gender')}"
        )

        print(
            f"Complexion        : "
            f"{candidate.get('complexion')}"
        )

        print(
            f"Height            : "
            f"{candidate.get('height_cm')}"
        )

        print(
            f"Location          : "
            f"{candidate.get('location')}"
        )

        print(
            f"Date found        : "
            f"{candidate.get('date_found')}"
        )

        print(
            f"Clothing          : "
            f"{candidate.get('clothing')}"
        )

        print(
            f"Distinctive marks : "
            f"{candidate.get('distinctive_marks')}"
        )

        print(
            f"Description       : "
            f"{candidate.get('description')}"
        )

        print(
            f"Police station    : "
            f"{candidate.get('police_station')}"
        )

        print(
            f"District          : "
            f"{candidate.get('district')}"
        )

        print("\nScores:")

        print(
            f"  Semantic similarity     : "
            f"{result['semantic_similarity']}"
        )

        print(
            f"  Semantic score          : "
            f"{result['semantic_score']}/100"
        )

        print(
            f"  Structured match        : "
            f"{result['structured_score']}/100"
        )

        print(
            f"  Effective structured    : "
            f"{result['effective_structured_score']}/100"
        )

        print(
            f"  Data completeness       : "
            f"{result['data_completeness']}%"
        )

        print(
            f"  FINAL RETRIEVAL SCORE   : "
            f"{result['final_score']}/100"
        )

        details = result.get(
            "structured_details",
            {},
        )

        if details:
            print("\nStructured evidence:")

            for field, status in details.items():
                print(
                    f"  {field:20s}: {status}"
                )






def main():

    parser = argparse.ArgumentParser(
        description=(
            "Bharat Talaash "
            "AWS GPU matching engine"
        )
    )

    parser.add_argument(
        "--case-file",
        required=True,
        help="JSON file containing the input case",
    )

    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
    )

    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "SentenceTransformer model used for "
            "the query. Must match DynamoDB embeddings."
        ),
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
    )

    parser.add_argument(
        "--top",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--cache",
        default=DEFAULT_CACHE,
    )

    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help=(
            "Ignore local cache and read "
            "embeddings from DynamoDB again."
        ),
    )

    args = parser.parse_args()

    print("=" * 72)
    print(
        "BHARAT TALAASH - "
        "AWS GPU MATCHING ENGINE"
    )
    print("=" * 72)

    print(
        f"\nDynamoDB table : "
        f"{args.table}"
    )

    print(
        f"AWS region     : "
        f"{args.region}"
    )

    print(
        f"Embedding model: "
        f"{args.model}"
    )

    print(
        f"Batch size     : "
        f"{args.batch_size}"
    )

    with open(
        args.case_file,
        "r",
        encoding="utf-8",
    ) as f:
        case = json.load(f)

    print("\nInput case:")

    print(
        json.dumps(
            case,
            indent=2,
            ensure_ascii=False,
        )
    )

    engine = MatchingEngine(
        table_name=args.table,
        region=args.region,
        model_name=args.model,
        batch_size=args.batch_size,
        cache_path=args.cache,
        refresh_cache=args.refresh_cache,
    )

    engine.load_index()

    print("\n" + "=" * 72)
    print("SEARCHING")
    print("=" * 72)

    results = engine.search(
        case,
        top_n=args.top,
    )

    print_results(results)


if __name__ == "__main__":
    main()
