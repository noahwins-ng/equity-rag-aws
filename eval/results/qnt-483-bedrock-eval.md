# QNT-483 — cloud retrieval eval on Bedrock (Titan V2)

This is a re-run of the QNT-270 eval after model serving moved back to Bedrock (ADR-0002). The
labels (51 topics: 38 news, 13 earnings), the metrics, `eval/cloud_eval.py` and `top_k = top_n =
20` are all the same. Only the embedding model changed, from `openai/text-embedding-3-small` via
OpenRouter to **Bedrock Titan Text Embeddings V2** (512-dim, normalized). Rerank is the same
model, Cohere Rerank 3.5, now served from Bedrock. Run on 2026-10-03; no query needed a retry.

The in-repo rows and their provenance are unchanged from
[`qnt-270-cloud-eval.md`](qnt-270-cloud-eval.md). The QNT-270 cloud rows stay here as a
second data point and are not superseded.

## Comparison table

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | in-repo dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | in-repo hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | **cloud dense (S3 Vectors, Titan V2)** | 0.258 | 0.488 | 0.622 | 0.483 |
| news | **cloud dense+rerank (Titan V2 + Bedrock Rerank 3.5)** | 0.304 | 0.488 | 0.700 | 0.547 |
| news | *QNT-270: cloud dense (text-embedding-3-small)* | 0.310 | 0.654 | 0.641 | 0.544 |
| news | *QNT-270: cloud dense+rerank (OpenRouter)* | 0.411 | 0.654 | 0.806 | 0.679 |
| earnings | in-repo dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | in-repo hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | **cloud dense (S3 Vectors, Titan V2)** | 0.364 | 0.551 | 0.769 | 0.630 |
| earnings | **cloud dense+rerank (Titan V2 + Bedrock Rerank 3.5)** | 0.375 | 0.551 | 0.769 | 0.673 |
| earnings | *QNT-270: cloud dense (text-embedding-3-small)* | 0.321 | 0.534 | 0.789 | 0.629 |
| earnings | *QNT-270: cloud dense+rerank (OpenRouter)* | 0.364 | 0.534 | 0.761 | 0.639 |

R@20 can't change with rerank in this design. With `top_k = top_n = 20`, rerank reorders the
top-20 dense candidates but never changes which documents are in them. So each cloud R@20
measures the dense candidate pool alone.

## Held / regressed verdict

- **news:** dense-only **REGRESSED**. Titan V2 falls below in-repo dense on R@5 (−0.037),
  R@20 (−0.124) and nDCG@10 (−0.038), with MRR flat (+0.002). The full pipeline also
  **REGRESSED** against the in-repo hybrid+rerank ceiling, and by more than in QNT-270.
- **earnings:** dense-only **HELD**, and in fact improved on all four metrics (R@5 +0.029,
  R@20 +0.022, MRR +0.098, nDCG@10 +0.099). The full pipeline **REGRESSED** against the
  in-repo hybrid+rerank ceiling, as it did in QNT-270.

## Hypothesis assessment

- **H1 (news) — PARTIALLY CONFIRMED (3 of 4 metrics).** Cloud dense+rerank lands between
  in-repo dense and in-repo hybrid+rerank on R@5 (0.295 < 0.304 < 0.527, only just), MRR
  (0.620 < 0.700 < 0.857) and nDCG@10 (0.521 < 0.547 < 0.786). It fails on R@20: 0.488 is below
  in-repo dense's 0.612. Because R@20 is fixed by the dense pool, that miss is Titan V2's
  weaker news recall, not rerank. In QNT-270, text-embedding-3-small held H1 on all four
  metrics. Whether H1 holds therefore depends on the embedding model.
- **H2 (earnings) — REFUTED, same as QNT-270, and now reproduced across two embedding
  models.** The premise is wrong. In-repo earnings rerank lift is large: MRR goes to 1.000 and
  nDCG@10 gains +0.303. Cloud lift on earnings stays marginal with Titan V2 too: R@5 +0.011,
  MRR 0.000, nDCG@10 +0.043. It's marginal under both embedding models, so embedding space is
  unlikely to explain it. The more likely cause is the candidate pool: the cloud stack reranks
  pure dense candidates, while in-repo reranks a BM25-fused set.
- **H3 (embeddings) — CONFIRMED for news; earnings consistent in direction, MRR flat.**
  Dense-only results differ from in-repo on both corpora, as expected for a different
  embedding space. R@20 is excluded from the direction check because rerank can't change it
  (see above). On the other three metrics the rerank delta is:
  - **news:** positive on all three (R@5 +0.046, MRR +0.078, nDCG@10 +0.064). That matches
    in-repo.
  - **earnings:** positive on R@5 (+0.011) and nDCG@10 (+0.043), and exactly flat on MRR
    (0.000). QNT-270's earnings MRR reversal (−0.028) doesn't reproduce. With 13 topics, one
    query moving from rank 1 to rank 2 shifts MRR by about 0.04, so that reversal was within
    single-query noise.

## New finding: the embedding swap splits by corpus

Two cloud runs, identical apart from the embedding model, give a direct embedding ablation.
Titan V2 minus text-embedding-3-small, dense-only:

| Corpus | ΔR@5 | ΔR@20 | ΔMRR | ΔnDCG@10 |
|---|---|---|---|---|
| news | −0.052 | −0.166 | −0.019 | −0.061 |
| earnings | +0.043 | +0.017 | −0.020 | +0.001 |

On news, a lexically diverse corpus where ranking is hard, the embedding choice moves every
metric, and R@20 moves by a lot. On earnings, which is templated and close to a `(ticker,
period)` filter problem, the two models are effectively tied. This is the project's regime
finding showing up on a new axis. News is sensitive to every retrieval-stack choice (BM25,
rerank, embeddings). Earnings is sensitive to rerank in-repo but not to the embedding model.

## Caveats

- **Small samples.** 38 news and 13 earnings topics, with no confidence intervals or paired
  tests. Treat earnings deltas under about 0.04 as noise, and the news deltas as directional.
- **One run per configuration.** Neither cloud run was repeated, and Bedrock and OpenRouter
  may serve Rerank 3.5 with different numerics. The rerank deltas compare within each run,
  which controls for this, but the absolute numbers across runs don't.

## Reproduction

```
uv run python eval/cloud_eval.py
```

This requires the stack deployed and indexed (see README "Reproduce"). The client sends one
query every 21 s to stay under Bedrock Rerank 3.5's 3 requests/min quota, so a full sweep
takes about 18 min. The in-repo baseline snippet is in
[`qnt-270-cloud-eval.md`](qnt-270-cloud-eval.md#reproduction).
