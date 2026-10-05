"""QNT-269 retrieval service: dense search (S3 Vectors) -> Cohere Rerank 3.5 -> optional
gpt-oss-20b generation, all served via Bedrock (ADR-0002, QNT-483) -- same substrate as the
QNT-268 index job. Invoked through a Lambda Function URL with AWS_IAM auth (see
terraform/retrieval_service.tf) instead of API Gateway: the only caller is the local eval
client, which already carries AWS credentials (SigV4), so IAM auth keeps the endpoint
private for free.

S3 Vectors metadata doesn't carry the candidates' source text (see lambda/index_job/handler.py
-- only corpus/ticker/date/doc_id[/chunk_index/section] is stored there), so rerank and
generation need it joined back from corpus/{corpus}.jsonl. This handler loads that file into
a per-container point_id -> row cache on cold start, reused across warm invocations.

QNT-312 adds two optional request fields, matching the original's served path (ADR-0003):
``ticker`` scopes both retrieval legs to one company (S3 Vectors metadata filter + BM25 over
that ticker's rows), and ``mode: "hybrid"`` fuses the dense ranking with a BM25 ranking
(``hybrid.py``) via RRF before rerank. BM25 is built in memory from the same cached corpus
rows -- no extra S3 object or always-on resource.
"""

from __future__ import annotations

import json
import os

import boto3
from botocore.config import Config
from hybrid import bm25_ranking, reciprocal_rank_fusion

REGION = os.environ.get("AWS_REGION", "us-west-2")
CORPUS_BUCKET = os.environ["CORPUS_BUCKET"]
VECTOR_BUCKET = os.environ["VECTOR_BUCKET"]

# Same embedding model/dims as the QNT-268 index job -- queries and indexed vectors must
# share one embedding space.
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 512
RERANK_MODEL_ID = "cohere.rerank-v3-5:0"
GENERATION_MODEL_ID = "openai.gpt-oss-20b-1:0"

DEFAULT_DENSE_TOP_K = 20
DEFAULT_RERANK_TOP_N = 5

s3 = boto3.client("s3", region_name=REGION)
s3vectors = boto3.client("s3vectors", region_name=REGION)
# Adaptive retries absorb throttling -- Rerank 3.5's on-demand quota on this account is only
# 3 requests/min (non-adjustable), so back-to-back callers will hit it.
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(retries={"mode": "adaptive", "max_attempts": 5}),
)

_corpus_cache: dict[str, dict[str, dict]] = {}


def _load_corpus(corpus: str) -> dict[str, dict]:
    if corpus not in _corpus_cache:
        obj = s3.get_object(Bucket=CORPUS_BUCKET, Key=f"corpus/{corpus}.jsonl")
        body = obj["Body"].read().decode("utf-8")
        rows = (json.loads(line) for line in body.splitlines() if line.strip())
        _corpus_cache[corpus] = {row["point_id"]: row for row in rows}
    return _corpus_cache[corpus]


def _embed_query(text: str) -> list[float]:
    resp = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}),
    )
    return json.loads(resp["body"].read())["embedding"]


def _dense_search(
    corpus: str, query_vector: list[float], top_k: int, ticker: str | None
) -> list[dict]:
    kwargs = {"filter": {"ticker": {"$eq": ticker}}} if ticker else {}
    resp = s3vectors.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=corpus,
        queryVector={"float32": query_vector},
        topK=top_k,
        returnDistance=True,
        **kwargs,
    )
    return resp["vectors"]


def _bm25_text(row: dict) -> str:
    # Mirrors the original's searchable text minus the earnings `title` field, which the
    # snapshot doesn't carry (ADR-0003). News rows already hold headline + body in `text`.
    return f"{row.get('section') or ''} {row['text']}"


def _rerank(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    documents = [c["text"] for c in candidates]
    resp = bedrock.invoke_model(
        modelId=RERANK_MODEL_ID,
        body=json.dumps(
            {"query": query, "documents": documents, "top_n": top_n, "api_version": 2}
        ),
    )
    result = json.loads(resp["body"].read())
    return [
        {**candidates[r["index"]], "rerank_score": r["relevance_score"]}
        for r in result["results"]
    ]


def _generate(query: str, docs: list[dict]) -> str:
    context = "\n\n".join(f"[{d['ticker']} {d['date']}] {d['text']}" for d in docs)
    resp = bedrock.converse(
        modelId=GENERATION_MODEL_ID,
        system=[
            {
                "text": (
                    "Answer the question using only the context below. If the context "
                    "doesn't contain the answer, say so explicitly."
                )
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [{"text": f"Context:\n{context}\n\nQuestion: {query}"}],
            }
        ],
    )
    # gpt-oss returns a reasoningContent block before the answer -- keep only text blocks.
    blocks = resp["output"]["message"]["content"]
    return "".join(b["text"] for b in blocks if "text" in b)


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
    # Normalised once so both legs agree: "" means unscoped, same as absent.
    ticker = body.get("ticker") or None
    if ticker is not None and not isinstance(ticker, str):
        return _response(400, {"error": f"ticker must be a string: {ticker!r}"})
    mode = body.get("mode", "dense")
    if mode not in ("dense", "hybrid"):
        return _response(400, {"error": f"unknown mode: {mode!r}"})

    corpus_rows = _load_corpus(corpus)
    query_vector = _embed_query(query)
    dense_hits = _dense_search(corpus, query_vector, top_k, ticker)
    distance_of = {hit["key"]: hit.get("distance") for hit in dense_hits}

    # Same shape as the original's hybrid_run_ids: top_k from each leg, RRF, then the top
    # top_k fused ids go to rerank.
    candidate_ids = [hit["key"] for hit in dense_hits]
    if mode == "hybrid":
        scoped = {
            pid: _bm25_text(row)
            for pid, row in corpus_rows.items()
            if ticker is None or row["ticker"] == ticker
        }
        bm25_ids = bm25_ranking(scoped, query, limit=top_k)
        fused = reciprocal_rank_fusion([candidate_ids, bm25_ids])
        candidate_ids = [pid for pid, _ in fused[:top_k]]

    candidates = []
    for pid in candidate_ids:
        row = corpus_rows.get(pid)
        if row is None:
            continue
        candidates.append({**row, "dense_distance": distance_of.get(pid)})

    # Every dense hit's point_id failed to join against corpus_rows (e.g. the S3 corpus
    # snapshot and S3 Vectors index have drifted out of sync) -- rerank rejects an empty
    # documents list, so short-circuit here instead.
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
