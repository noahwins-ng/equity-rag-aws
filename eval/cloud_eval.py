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

Usage: uv run python eval/cloud_eval.py
"""

from __future__ import annotations

import json
import subprocess
import sys
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


def _function_url() -> str:
    return subprocess.check_output(
        ["terraform", "output", "-raw", "retrieval_service_url"],
        cwd=Path(__file__).parent.parent / "terraform",
        text=True,
    ).strip()


def _invoke(url: str, corpus: str, query: str) -> dict:
    body = json.dumps(
        {"corpus": corpus, "query": query, "top_k": TOP_K, "top_n": TOP_K, "generate": False}
    ).encode()
    request = AWSRequest(
        method="POST", url=url, data=body, headers={"Content-Type": "application/json"}
    )
    SigV4Auth(boto3.Session().get_credentials(), "lambda", REGION).add_auth(request)
    req = urllib.request.Request(url, data=body, headers=dict(request.headers), method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def run_eval() -> tuple[dict[str, str], dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Sweep every topic once; return (corpus_of, run_dense, run_rerank)."""
    topics = yaml.safe_load((LABELS_DIR / "retrieval.yaml").read_text())["queries"]
    url = _function_url()

    corpus_of: dict[str, str] = {}
    run_dense: dict[str, dict[str, float]] = {}
    run_rerank: dict[str, dict[str, float]] = {}

    for topic in topics:
        qid, corpus, query = topic["id"], topic["corpus"], topic["query"]
        corpus_of[qid] = corpus
        print(f"  {qid} ({corpus})...", file=sys.stderr)
        result = _invoke(url, corpus, query)
        run_dense[qid] = {r["point_id"]: -r["dense_distance"] for r in result["results"]}
        run_rerank[qid] = {r["point_id"]: r["rerank_score"] for r in result["results"]}

    return corpus_of, run_dense, run_rerank


def main() -> int:
    corpus_of, run_dense, run_rerank = run_eval()
    qrels = load_qrels_trec(LABELS_DIR / "retrieval_qrels.trec")

    print("\n| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |")
    print("|---|---|---|---|---|---|")
    for corpus in ("news", "earnings"):
        qids = {qid for qid, c in corpus_of.items() if c == corpus}
        qrels_c = {qid: v for qid, v in qrels.items() if qid in qids}
        for label, run in (("cloud dense", run_dense), ("cloud dense+rerank", run_rerank)):
            run_c = {qid: v for qid, v in run.items() if qid in qids}
            m = compute_metrics(qrels_c, run_c)
            print(
                f"| {corpus} | {label} | {m['R@5']:.3f} | {m['R@20']:.3f} "
                f"| {m['RR']:.3f} | {m['nDCG@10']:.3f} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
