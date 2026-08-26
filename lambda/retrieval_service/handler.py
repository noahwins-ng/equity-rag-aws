"""QNT-269 retrieval service: dense search (S3 Vectors) -> Cohere Rerank 3.5 -> optional
gpt-oss-20b generation, both served via OpenRouter (ADR-0001) -- same substrate as the
QNT-268 index job. Invoked through a Lambda Function URL with AWS_IAM auth (see
terraform/retrieval_service.tf) instead of API Gateway: the only caller is the local eval
client, which already carries AWS credentials (SigV4), so IAM auth keeps the endpoint
private for free.

S3 Vectors metadata doesn't carry the candidates' source text (see lambda/index_job/handler.py
-- only corpus/ticker/date/doc_id[/chunk_index/section] is stored there), so rerank and
generation need it joined back from corpus/{corpus}.jsonl. This handler loads that file into
a per-container point_id -> row cache on cold start, reused across warm invocations.
"""

from __future__ import annotations

import json
import os
import urllib.request

import boto3
from openai import OpenAI

REGION = os.environ.get("AWS_REGION", "us-west-2")
CORPUS_BUCKET = os.environ["CORPUS_BUCKET"]
VECTOR_BUCKET = os.environ["VECTOR_BUCKET"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

# Same embedding model/dims as the QNT-268 index job -- queries and indexed vectors must
# share one embedding space.
EMBED_MODEL_ID = "openai/text-embedding-3-small"
EMBED_DIM = 512
RERANK_MODEL_ID = "cohere/rerank-v3.5"  # OpenRouter's slug for Cohere Rerank 3.5
GENERATION_MODEL_ID = "openai/gpt-oss-20b"

DEFAULT_DENSE_TOP_K = 20
DEFAULT_RERANK_TOP_N = 5

s3 = boto3.client("s3", region_name=REGION)
s3vectors = boto3.client("s3vectors", region_name=REGION)
openrouter = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

_corpus_cache: dict[str, dict[str, dict]] = {}


def _load_corpus(corpus: str) -> dict[str, dict]:
    if corpus not in _corpus_cache:
        obj = s3.get_object(Bucket=CORPUS_BUCKET, Key=f"corpus/{corpus}.jsonl")
        body = obj["Body"].read().decode("utf-8")
        rows = (json.loads(line) for line in body.splitlines() if line.strip())
        _corpus_cache[corpus] = {row["point_id"]: row for row in rows}
    return _corpus_cache[corpus]


def _embed_query(text: str) -> list[float]:
    resp = openrouter.embeddings.create(model=EMBED_MODEL_ID, input=text, dimensions=EMBED_DIM)
    return resp.data[0].embedding


def _dense_search(corpus: str, query_vector: list[float], top_k: int) -> list[dict]:
    resp = s3vectors.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=corpus,
        queryVector={"float32": query_vector},
        topK=top_k,
        returnDistance=True,
    )
    return resp["vectors"]


def _rerank(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    # OpenRouter's /rerank endpoint has no method on the OpenAI client -- rerank isn't part
    # of the OpenAI API surface the client wraps -- so this calls it directly.
    documents = [c["text"] for c in candidates]
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/rerank",
        data=json.dumps(
            {"model": RERANK_MODEL_ID, "query": query, "documents": documents, "top_n": top_n}
        ).encode(),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return [
        {**candidates[r["index"]], "rerank_score": r["relevance_score"]}
        for r in result["results"]
    ]


def _generate(query: str, docs: list[dict]) -> str:
    context = "\n\n".join(f"[{d['ticker']} {d['date']}] {d['text']}" for d in docs)
    completion = openrouter.chat.completions.create(
        model=GENERATION_MODEL_ID,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer the question using only the context below. If the context "
                    "doesn't contain the answer, say so explicitly."
                ),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
    )
    return completion.choices[0].message.content


def _response(status: int, payload: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def lambda_handler(event: dict, _context) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
        corpus = body["corpus"]
        query = body["query"]
    except (KeyError, json.JSONDecodeError) as exc:
        return _response(400, {"error": f"invalid request: {exc}"})

    if corpus not in ("news", "earnings"):
        return _response(400, {"error": f"unknown corpus: {corpus!r}"})

    top_k = int(body.get("top_k", DEFAULT_DENSE_TOP_K))
    top_n = int(body.get("top_n", DEFAULT_RERANK_TOP_N))
    generate = bool(body.get("generate", True))

    corpus_rows = _load_corpus(corpus)
    query_vector = _embed_query(query)
    dense_hits = _dense_search(corpus, query_vector, top_k)

    candidates = []
    for hit in dense_hits:
        row = corpus_rows.get(hit["key"])
        if row is None:
            continue
        candidates.append({**row, "dense_distance": hit.get("distance")})

    # Every dense hit's point_id failed to join against corpus_rows (e.g. the S3 corpus
    # snapshot and S3 Vectors index have drifted out of sync) -- OpenRouter's /rerank 400s
    # on an empty documents list, so short-circuit here instead.
    if not candidates:
        return _response(
            200, {"corpus": corpus, "query": query, "results": [], "answer": None}
        )

    reranked = _rerank(query, candidates, top_n)
    answer = _generate(query, reranked) if generate else None

    results = [
        {
            "point_id": d["point_id"],
            "doc_id": d["doc_id"],
            "ticker": d["ticker"],
            "date": d["date"],
            "chunk_index": d.get("chunk_index"),
            "section": d.get("section"),
            "text": d["text"],
            "dense_distance": d["dense_distance"],
            "rerank_score": d["rerank_score"],
        }
        for d in reranked
    ]

    return _response(
        200, {"corpus": corpus, "query": query, "results": results, "answer": answer}
    )
