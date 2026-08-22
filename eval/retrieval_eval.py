"""Offline ir_measures scoring core (QNT-267).

Trimmed from equity-data-agent's ``agent.evals.retrieval_eval`` (QNT-261) down to the
TREC I/O + metric computation this repo needs -- no Qdrant, no BM25/hybrid, no live
retrieval (this project is dense-only, see docs/PRD.md architecture_rules; those live
helpers don't apply here). Accepted light duplication: metrics are identical by
construction (same ir_measures metric objects, same TREC qrels/run format), so this
repo's cloud eval (QNT-270) scores against the exact same yardstick as the in-repo one.
"""

from __future__ import annotations

from pathlib import Path

import ir_measures
from ir_measures import RR, R, nDCG

METRICS = [R @ 5, R @ 20, RR, nDCG @ 10]


def load_qrels_trec(path: Path) -> dict[str, dict[str, int]]:
    """Load a TREC qrels file (``qid 0 docid relevance`` per line) keyed by point_id."""
    qrels: dict[str, dict[str, int]] = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        qid, _, docid, rel = parts
        qrels.setdefault(qid, {})[docid] = int(rel)
    return qrels


def load_run_trec(path: Path) -> dict[str, dict[str, float]]:
    """Load a TREC run file (``qid Q0 docid rank score tag`` per line)."""
    run: dict[str, dict[str, float]] = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 6:
            continue
        qid, _, docid, _, score, _ = parts
        run.setdefault(qid, {})[docid] = float(score)
    return run


def compute_metrics(
    qrels: dict[str, dict[str, int]], run: dict[str, dict[str, float]]
) -> dict[str, float]:
    """Aggregate recall@5/@20, MRR (RR), and nDCG@10 via ir_measures."""
    agg = ir_measures.calc_aggregate(METRICS, qrels, run)
    return {str(metric): float(value) for metric, value in agg.items()}
