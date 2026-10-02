"""QNT-268 index job: embed the frozen snapshot corpus (via Bedrock Titan V2) into S3 Vectors.

One invocation per corpus slice: event = {"corpus": "news"|"earnings", "start": int,
"limit": int} (start/limit optional, default = the whole corpus). Titan V2's on-demand
quota on this account is 60 requests/min (non-adjustable) and takes one text per call, so
~2k rows/corpus can't fit in one 15-min Lambda run -- invoke it in slices of <=800 rows
(QNT-483). ``put_vectors`` is a keyed upsert (key = point_id), so re-running any slice is
naturally idempotent.

Served off-AWS from 2026-08-26 (ADR-0001) while this account's Bedrock quota was
stuck at 0; moved back to Bedrock once that resolved (ADR-0002, QNT-483).
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "us-west-2")
CORPUS_BUCKET = os.environ["CORPUS_BUCKET"]
VECTOR_BUCKET = os.environ["VECTOR_BUCKET"]

EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 512
PUT_BATCH_SIZE = 100
# One worker: at 60 req/min the quota, not latency, is the bottleneck -- more workers only
# buy more throttling.
MAX_WORKERS = 1
MODEL_ERROR_RETRIES = 4

s3 = boto3.client("s3", region_name=REGION)
s3vectors = boto3.client("s3vectors", region_name=REGION)
# Adaptive retry mode rate-limits client-side after a ThrottlingException instead of
# failing the slice.
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(retries={"mode": "adaptive", "max_attempts": 10}),
)


def _load_corpus_rows(corpus: str) -> list[dict]:
    obj = s3.get_object(Bucket=CORPUS_BUCKET, Key=f"corpus/{corpus}.jsonl")
    body = obj["Body"].read().decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def _embed(text: str) -> list[float]:
    # Titan intermittently returns ModelErrorException ("unexpected error ... Try your request
    # again") -- not in botocore's retryable set, so one transient blip would otherwise fail a
    # whole ~12-min slice. Retry it here; throttling is still handled by the adaptive config.
    for attempt in range(MODEL_ERROR_RETRIES):
        try:
            resp = bedrock.invoke_model(
                modelId=EMBED_MODEL_ID,
                body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}),
            )
            return json.loads(resp["body"].read())["embedding"]
        except bedrock.exceptions.ModelErrorException:
            if attempt == MODEL_ERROR_RETRIES - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _row_metadata(row: dict) -> dict:
    # point_id is the vector key, never metadata -- it's the identity itself (PRD §5).
    metadata = {
        "corpus": row["corpus"],
        "ticker": row["ticker"],
        "date": row["date"],
        "doc_id": str(row["doc_id"]),
    }
    if "chunk_index" in row:
        metadata["chunk_index"] = row["chunk_index"]
    if "section" in row:
        metadata["section"] = row["section"]
    return metadata


def _embed_rows(rows: list[dict]) -> list[dict]:
    vectors: list[dict | None] = [None] * len(rows)

    def work(i: int, row: dict) -> tuple[int, list[float]]:
        return i, _embed(row["text"])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(work, i, row) for i, row in enumerate(rows)]
        for fut in as_completed(futures):
            i, embedding = fut.result()
            vectors[i] = {
                "key": rows[i]["point_id"],
                "data": {"float32": embedding},
                "metadata": _row_metadata(rows[i]),
            }
    return vectors


def _put_vectors(index_name: str, vectors: list[dict]) -> None:
    for i in range(0, len(vectors), PUT_BATCH_SIZE):
        batch = vectors[i : i + PUT_BATCH_SIZE]
        s3vectors.put_vectors(vectorBucketName=VECTOR_BUCKET, indexName=index_name, vectors=batch)


def lambda_handler(event: dict, _context) -> dict:
    corpus = event["corpus"]
    if corpus not in ("news", "earnings"):
        raise ValueError(f"unknown corpus: {corpus!r}")

    all_rows = _load_corpus_rows(corpus)
    start = int(event.get("start", 0))
    limit = int(event.get("limit", len(all_rows)))
    rows = all_rows[start : start + limit]
    vectors = _embed_rows(rows)
    _put_vectors(corpus, vectors)

    return {
        "corpus": corpus,
        "start": start,
        "rows": len(rows),
        "corpus_rows": len(all_rows),
        "vectors_written": len(vectors),
    }
