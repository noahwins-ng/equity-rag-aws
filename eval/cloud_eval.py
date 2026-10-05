"""QNT-270: recycle the retrieval eval against the deployed cloud endpoint.

For each labeled topic (``labels/retrieval.yaml``), SigV4-signs a single POST to the
retrieval Lambda's Function URL with ``top_k=top_n=20`` and ``generate=false`` (skips
gpt-oss-20b generation -- unneeded for a retrieval-only eval, and generation isn't the
metric under test). One call returns every dense-search candidate carrying both
``dense_distance`` and ``rerank_score``, so a single sweep yields two rankings per query:

* dense-only   -- sorted by ``dense_distance`` ascending (S3 Vectors cosine distance:
  lower = closer, so score = -distance for ir_measures' higher-is-better convention).
* dense+rerank -- sorted by ``rerank_score`` descending, as returned.

Scored per-corpus (news, earnings -- never blended, per workflow-profile.yaml
architecture rules) against the copied labels, using the same ir_measures metrics as
``retrieval_eval.py``.

QNT-312: every call now carries the topic's ``ticker``, scoping both retrieval legs the
way the original does (ADR-0003), and each topic is queried twice -- ``mode=dense`` (yields
the two rankings above) and ``mode=hybrid`` (dense + BM25 via RRF, then rerank) -- so a
third ranking, hybrid+rerank, is scored on the same sweep.

Paced at one call per ``PACE_SECONDS``: every call reranks, and Bedrock Rerank 3.5's
on-demand quota on this account is 3 requests/min (non-adjustable, QNT-483) -- 51 topics x 2
calls take ~36 min.

Usage: uv run python eval/cloud_eval.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
import yaml
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from retrieval_eval import compute_metrics, load_qrels_trec

REGION = "us-west-2"
LABELS_DIR = Path(__file__).parent / "labels"
TOP_K = 20
PACE_SECONDS = 21  # > 60s / 3 req/min rerank quota


def _function_url() -> str:
    return subprocess.check_output(
        ["terraform", "output", "-raw", "retrieval_service_url"],
        cwd=Path(__file__).parent.parent / "terraform",
        text=True,
    ).strip()


def _invoke(url: str, corpus: str, query: str, ticker: str, mode: str) -> dict:
    body = json.dumps(
        {
            "corpus": corpus,
            "query": query,
            "ticker": ticker,
            "mode": mode,
            "top_k": TOP_K,
            "top_n": TOP_K,
            "generate": False,
        }
    ).encode()
    request = AWSRequest(
        method="POST", url=url, data=body, headers={"Content-Type": "application/json"}
    )
    SigV4Auth(boto3.Session().get_credentials(), "lambda", REGION).add_auth(request)
    req = urllib.request.Request(url, data=body, headers=dict(request.headers), method="POST")
    # A transient Bedrock error/throttle surfaces as a 5xx from the Lambda -- retry after the
    # pace interval rather than losing the whole ~18-min sweep to one blip.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=70) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 2:
                raise
            print(f"    {exc.code}, retrying...", file=sys.stderr)
            time.sleep(PACE_SECONDS)
    raise AssertionError("unreachable")


Run = dict[str, dict[str, float]]


def run_eval() -> tuple[dict[str, str], Run, Run, Run]:
    """Sweep every topic; return (corpus_of, run_dense, run_rerank, run_hybrid)."""
    topics = yaml.safe_load((LABELS_DIR / "retrieval.yaml").read_text())["queries"]
    url = _function_url()

    corpus_of: dict[str, str] = {}
    run_dense: dict[str, dict[str, float]] = {}
    run_rerank: dict[str, dict[str, float]] = {}
    run_hybrid: dict[str, dict[str, float]] = {}

    for i, topic in enumerate(topics):
        qid, corpus, query, ticker = topic["id"], topic["corpus"], topic["query"], topic["ticker"]
        corpus_of[qid] = corpus
        print(f"  {qid} ({corpus}, {ticker})...", file=sys.stderr)
        if i:
            time.sleep(PACE_SECONDS)
        result = _invoke(url, corpus, query, ticker, "dense")
        run_dense[qid] = {r["point_id"]: -r["dense_distance"] for r in result["results"]}
        run_rerank[qid] = {r["point_id"]: r["rerank_score"] for r in result["results"]}
        time.sleep(PACE_SECONDS)
        result = _invoke(url, corpus, query, ticker, "hybrid")
        run_hybrid[qid] = {r["point_id"]: r["rerank_score"] for r in result["results"]}

    return corpus_of, run_dense, run_rerank, run_hybrid


def main() -> int:
    corpus_of, run_dense, run_rerank, run_hybrid = run_eval()
    qrels = load_qrels_trec(LABELS_DIR / "retrieval_qrels.trec")

    print("\n| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |")
    print("|---|---|---|---|---|---|")
    for corpus in ("news", "earnings"):
        qids = {qid for qid, c in corpus_of.items() if c == corpus}
        qrels_c = {qid: v for qid, v in qrels.items() if qid in qids}
        for label, run in (
            ("cloud dense (ticker-scoped)", run_dense),
            ("cloud dense+rerank (ticker-scoped)", run_rerank),
            ("cloud hybrid+rerank (ticker-scoped)", run_hybrid),
        ):
            run_c = {qid: v for qid, v in run.items() if qid in qids}
            m = compute_metrics(qrels_c, run_c)
            print(
                f"| {corpus} | {label} | {m['R@5']:.3f} | {m['R@20']:.3f} "
                f"| {m['RR']:.3f} | {m['nDCG@10']:.3f} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
