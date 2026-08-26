# QNT-270 — cloud retrieval eval results

Produced by `eval/cloud_eval.py` against the deployed retrieval Lambda (Function URL
`retrieval_service_url`), scored with the same `ir_measures` metrics (R@5, R@20, MRR,
nDCG@10) as the in-repo baseline, per corpus. In-repo numbers below are freshly computed
from `equity-data-agent`'s current frozen `retrieval_qrels.trec` / `retrieval_run.trec` /
`retrieval_run_hybrid.trec` — the exact labels copied verbatim into `eval/labels/` — split
per-corpus using `retrieval.yaml`'s `corpus` field. These supersede the PRD's original
"in-repo dense (Qdrant)" row (R@5 0.48 / R@20 0.72 / MRR 0.85 / nDCG@10 0.70), which was a
pre-relabel number blended across both corpora, not a news-only figure — confirmed against
`equity-data-agent`'s `docs/project-plan-archive.md` history (QNT-265's snapshot export
found the news corpus had been fully reingested since QNT-261's original baseline, forcing
a relabel of 12/38 news topics and a rebaseline of both frozen run files).

## Comparison table

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | in-repo dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | in-repo hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | cloud dense (S3 Vectors) | 0.310 | 0.654 | 0.641 | 0.544 |
| news | cloud dense+rerank (S3 Vectors + OpenRouter) | 0.411 | 0.654 | 0.806 | 0.679 |
| earnings | in-repo dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | in-repo hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | cloud dense (S3 Vectors) | 0.321 | 0.534 | 0.789 | 0.629 |
| earnings | cloud dense+rerank (S3 Vectors + OpenRouter) | 0.364 | 0.534 | 0.761 | 0.639 |

## Held / regressed verdict

- **news:** Dense-only **HELD** — cloud dense matches or slightly beats in-repo dense on
  all four metrics (different embedding space, comparable quality). Full pipeline
  **REGRESSED** against in-repo's hybrid+rerank ceiling (down on all four metrics) — an
  expected, architecturally-documented tradeoff: S3 Vectors is dense-only, so the cloud
  stack has no BM25 hybrid leg (PRD §6). The regression lands exactly where H1 predicted.
- **earnings:** Dense-only roughly **HELD** (mixed: R@5 slightly down, R@20/MRR/nDCG@10
  up). Full pipeline **REGRESSED** against in-repo's hybrid+rerank ceiling, more sharply
  than news — see H2 below, the premise behind expecting a smaller gap doesn't hold.

## Hypothesis assessment

- **H1 (news) — CONFIRMED.** "Cloud dense+rerank lands between in-repo dense-only and
  in-repo hybrid+rerank." Holds on all four metrics: R@5 0.295 < 0.411 < 0.527; R@20
  0.612 < 0.654 < 0.799; MRR 0.620 < 0.806 < 0.857; nDCG@10 0.521 < 0.679 < 0.786. Rerank
  recovers most (not all) of the missing BM25 leg's lift, as hypothesized.

- **H2 (earnings) — REFUTED.** "Rerank lift stays marginal on the cloud too — the
  dense-saturated regime is a corpus property, not a stack property." The premise doesn't
  hold: in-repo earnings rerank lift is *not* marginal (R@5 +0.194, R@20 +0.145, MRR
  +0.329 to a perfect 1.000, nDCG@10 +0.303 — the largest lift of either corpus/config).
  Cloud's rerank lift on earnings, by contrast, *is* small and mixed (R@5 +0.043, R@20
  +0.000, MRR **-0.028** — rerank actually hurt ranking quality here, nDCG@10 +0.010).
  So earnings is not dense-saturated as a corpus property (in-repo proves rerank has large
  headroom there); the marginal lift observed is specific to the cloud stack — plausibly
  Cohere Rerank 3.5 via OpenRouter behaving differently on this corpus than the same model
  reranking the in-repo's fused dense+BM25 candidate set (a different, hybrid-informed
  input list) rather than pure dense candidates. Genuinely interesting substrate effect,
  not the hypothesized corpus property.

- **H3 (embeddings) — CONFIRMED for news, PARTIALLY REFUTED for earnings.** "Dense-only
  results differ from in-repo dense-only (different space), but the rerank delta is
  directionally consistent." Dense-only numbers differ from in-repo on both corpora, as
  expected (different embedding model/space). Rerank delta direction (note: R@20 is
  **structurally invariant** to rerank in this eval design — `cloud_eval.py` calls the
  endpoint with `top_k=top_n=20`, so rerank reorders the top-20 candidates but never
  changes membership, making R@20's delta exactly 0.000 by construction on both corpora,
  not a measured "no lift" result — excluded from the directional comparison below):
  - news: in-repo delta (dense→hybrid+rerank) is positive on R@5/MRR/nDCG@10 (R@20 also
    positive there, since the in-repo hybrid leg *does* add candidates beyond top-20
    dense); cloud delta (dense→dense+rerank) is positive on all 3 comparable metrics
    (R@5 +0.101, MRR +0.165, nDCG@10 +0.135) — directionally consistent.
  - earnings: in-repo delta is positive on R@5/MRR/nDCG@10; cloud delta is positive on
    R@5 (+0.043) and nDCG@10 (+0.010) but **negative on MRR** (-0.028) — the one metric
    where the two stacks disagree on direction, not just magnitude.

## Reproduction

Cloud numbers:

```
uv run python eval/cloud_eval.py
```

Requires the retrieval service to be deployed (`terraform apply` from `terraform/`) and
AWS credentials with `lambda:InvokeFunctionUrl` on the deployed function.

In-repo baseline numbers (run from `equity-data-agent`, not this repo — this repo never
imports the monorepo's packages, per the build-time-handoff seam in PRD §5; this snippet
is a reference for reproducing the numbers above, not a committed script here):

```python
import sys
sys.path.insert(0, "packages/agent/src/agent/evals")  # or point PYTHONPATH there
from pathlib import Path
import yaml
from retrieval_eval import compute_metrics, load_qrels_trec, load_run_trec

GOLDENS = Path("packages/agent/src/agent/evals/goldens")
topics = yaml.safe_load((GOLDENS / "retrieval.yaml").read_text())["queries"]
corpus_of = {q["id"]: q["corpus"] for q in topics}
qrels = load_qrels_trec(GOLDENS / "retrieval_qrels.trec")
run_dense = load_run_trec(GOLDENS / "retrieval_run.trec")
run_hybrid = load_run_trec(GOLDENS / "retrieval_run_hybrid.trec")

for corpus in ("news", "earnings"):
    qids = {qid for qid, c in corpus_of.items() if c == corpus}
    for label, run in (("dense", run_dense), ("hybrid+rerank", run_hybrid)):
        run_c = {qid: v for qid, v in run.items() if qid in qids}
        qrels_c = {qid: v for qid, v in qrels.items() if qid in qids}
        print(corpus, label, compute_metrics(qrels_c, run_c))
```
