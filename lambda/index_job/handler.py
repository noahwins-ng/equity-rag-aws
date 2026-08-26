"""QNT-268 index job: embed the frozen snapshot corpus (via OpenRouter) into S3 Vectors.

One invocation per corpus (event = {"corpus": "news"} or {"corpus": "earnings"}), so
each run stays well inside the Lambda timeout -- OpenRouter's embeddings endpoint takes
one request per call here, so ~2k rows/corpus needs concurrency, not batching, to embed
in reasonable time. ``put_vectors`` is a keyed upsert (key = point_id), so re-running
this job is naturally idempotent.

Originally embedded via AWS Bedrock (Titan V2); moved to OpenRouter 2026-08-26 after a
confirmed, unresolved AWS account-level Bedrock quota provisioning defect -- see
docs/decisions/0001-bedrock-to-openrouter.md.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from openai import OpenAI

REGION = os.environ.get("AWS_REGION", "us-west-2")
CORPUS_BUCKET = os.environ["CORPUS_BUCKET"]
VECTOR_BUCKET = os.environ["VECTOR_BUCKET"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

EMBED_MODEL_ID = "openai/text-embedding-3-small"
EMBED_DIM = 512
PUT_BATCH_SIZE = 100
MAX_WORKERS = 8

s3 = boto3.client("s3", region_name=REGION)
s3vectors = boto3.client("s3vectors", region_name=REGION)
openrouter = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)


def _load_corpus_rows(corpus: str) -> list[dict]:
    obj = s3.get_object(Bucket=CORPUS_BUCKET, Key=f"corpus/{corpus}.jsonl")
    body = obj["Body"].read().decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def _embed(text: str) -> list[float]:
    resp = openrouter.embeddings.create(model=EMBED_MODEL_ID, input=text, dimensions=EMBED_DIM)
    return resp.data[0].embedding


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

    rows = _load_corpus_rows(corpus)
    vectors = _embed_rows(rows)
    _put_vectors(corpus, vectors)

    return {"corpus": corpus, "rows": len(rows), "vectors_written": len(vectors)}
