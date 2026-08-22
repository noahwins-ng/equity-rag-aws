"""QNT-267 AC4 smoke check: proves the scoring module computes metrics over the real
copied labels. NOT a retrieval eval -- there is no retrieval to score yet (that lands in
QNT-268/269, gets run for real in QNT-270). Builds a synthetic "perfect" run (every
labeled-relevant point_id ranked first) purely to exercise load_qrels_trec ->
compute_metrics end to end.
"""

from __future__ import annotations

from pathlib import Path

from retrieval_eval import compute_metrics, load_qrels_trec

LABELS_DIR = Path(__file__).parent / "labels"


def main() -> int:
    qrels = load_qrels_trec(LABELS_DIR / "retrieval_qrels.trec")
    run = {qid: {docid: 1.0 for docid in docids} for qid, docids in qrels.items()}

    metrics = compute_metrics(qrels, run)
    print(f"scoring module smoke check -- {len(qrels)} labeled queries")
    for name, value in metrics.items():
        print(f"  {name}: {value:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
