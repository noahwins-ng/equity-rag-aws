# QNT-312 — ticker-scoped and hybrid (BM25 + RRF) cloud eval

This run adds the two retrieval differences ADR-0003 found between the original and the AWS
stack. Every query is now scoped to the topic's ticker, and a third configuration fuses BM25
with the dense ranking via RRF before rerank. Everything else is unchanged from QNT-483:
51 topics (38 news, 13 earnings), Titan V2 (512-dim), Cohere Rerank 3.5 on Bedrock,
`top_k = top_n = 20`, and the same labels and scoring code. Run on 2026-10-05, 102 calls,
no retries.

## Comparison table

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | original dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | original hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | *QNT-483: cloud dense, unscoped* | 0.258 | 0.488 | 0.622 | 0.483 |
| news | *QNT-483: cloud dense+rerank, unscoped* | 0.304 | 0.488 | 0.700 | 0.547 |
| news | **cloud dense (ticker-scoped)** | 0.317 | 0.623 | 0.660 | 0.540 |
| news | **cloud dense+rerank (ticker-scoped)** | 0.426 | 0.623 | 0.798 | 0.679 |
| news | **cloud hybrid+rerank (ticker-scoped)** | 0.524 | 0.807 | 0.866 | 0.787 |
| earnings | original dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | original hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | *QNT-483: cloud dense, unscoped* | 0.364 | 0.551 | 0.769 | 0.630 |
| earnings | *QNT-483: cloud dense+rerank, unscoped* | 0.375 | 0.551 | 0.769 | 0.673 |
| earnings | **cloud dense (ticker-scoped)** | 0.395 | 0.638 | 0.850 | 0.675 |
| earnings | **cloud dense+rerank (ticker-scoped)** | 0.406 | 0.638 | 0.892 | 0.751 |
| earnings | **cloud hybrid+rerank (ticker-scoped)** | 0.423 | 0.712 | 0.933 | 0.765 |

The original rows are the frozen equity-data-agent runs, as in QNT-270/QNT-483.

## Where the QNT-483 gap went (nDCG@10)

| Step | News | Earnings |
|---|---|---|
| QNT-483 cloud dense+rerank (unscoped) | 0.547 | 0.673 |
| + ticker scoping | 0.679 (+0.132) | 0.751 (+0.078) |
| + BM25 hybrid | 0.787 (+0.108) | 0.765 (+0.014) |
| Original hybrid+rerank | 0.786 | 0.834 |
| **Remaining gap** | **−0.001** | **0.069** |

- **News: the gap is closed.** Ticker scoping and BM25 contribute about equally. Hybrid +
  rerank matches or slightly beats the original on every metric except R@5 (0.524 vs.
  0.527). R@20, which only measures the candidate pool, goes from 0.488 to 0.807, past the
  original's 0.799.
- **Earnings: most of the gap closes, mainly through ticker scoping.** Scoping lifts nDCG@10
  by +0.078 and MRR from 0.769 to 0.892. BM25 adds +0.014 nDCG and +0.074 R@20, which is
  within single-query noise on 13 topics. About 0.07 of the gap remains.

## What this changes in the QNT-483 reading

- **The missing ticker scope was the largest single cause, and it was never recorded.** The
  QNT-483 write-up and the README put the gap down to keyword search and, on news, the
  embedding model. Neither run scoped to the ticker, so both explanations absorbed this
  effect.
- **Titan V2 isn't the weak link it looked like on news.** Scoped, Titan dense (0.540 nDCG)
  is on par with the original's MiniLM dense (0.521). The QNT-483 embedding ablation
  (text-embedding-3-small beating Titan V2 on news) was also unscoped, so it measured which
  model copes better with cross-ticker distractors, not which retrieves better within one
  company.
- **H2 (earnings is rerank-insensitive) stays refuted.** Scoped, the cloud rerank lift on
  earnings is +0.076 nDCG and +0.042 MRR, larger than unscoped (+0.043 and 0.000) but still
  below the original's.

## Remaining earnings gap: candidates, not measured

- **No release title in the BM25 text.** The original's earnings BM25 text is title +
  section + text, and the snapshot has no title (ADR-0003). Titles carry the quarter and
  fiscal year, which many earnings topics hinge on.
- **Rerank sees less text.** The original reranks on the same title + section + text. The
  AWS Lambda reranks on `text` alone (unchanged since QNT-269).
- **Embedding model.** Scoped dense is 0.675 here vs. the original's 0.531, so the embedding
  model doesn't explain a shortfall at the dense stage. Its effect on the fused set wasn't
  isolated.
- **Sample size.** 13 topics. One topic moving from rank 1 to rank 2 shifts MRR by about
  0.04. The original's MRR of 1.000 leaves no room to match except perfectly.

## Caveats

- **The labels favor lexical retrieval.** A document is relevant if it contains one of the
  topic's `anchor_terms`. BM25 matches the same kind of signal, so the hybrid lift here is an
  upper bound on the lift for paraphrased, real-world questions (ADR-0003).
- **Small samples, one run each.** No confidence intervals or paired tests. Treat earnings
  deltas under about 0.04 as noise.
- **Scoping assumes the ticker is known.** Every topic carries its ticker, and so does the
  original's served path. A free-text question with no ticker would need entity detection
  first. That's outside this eval.

## Reproduction

```
uv run python eval/cloud_eval.py
```

This requires the stack deployed and indexed (see the README's "Run it yourself"). Each topic
is queried twice (`mode=dense`, `mode=hybrid`) at one call per 21 s for Rerank 3.5's 3
requests/min quota, so the sweep takes about 36 min.
