# ADR-0003: Add ticker scoping and a BM25 + RRF hybrid leg to the retrieval Lambda

- **Status:** accepted
- **Date:** 2026-10-05
- **Ticket:** QNT-312 (reverses the PRD §4 "no hybrid/BM25" non-goal)

## Context

PRD §4 left BM25 out of the cloud path because S3 Vectors only does vector search. The idea
was that the eval would measure what the missing keyword leg costs. QNT-483 measured a gap of
0.24 nDCG@10 on news and 0.16 on earnings against the original's hybrid + rerank, and the
README put most of it down to the missing keyword search.

Reading the original's retrieval code (equity-data-agent `shared/retrieval.py`,
`agent/evals/retrieval_eval.py`) turned up a second difference the PRD never recorded. The
original **scopes every search to the question's ticker**. Both the dense query
(`Filter(ticker == query.ticker)`) and the BM25 corpus are limited to that one company. The
AWS stack searched every ticker in the corpus. So the QNT-483 gap mixes three things: no
ticker scoping, no BM25, and a different embedding model.

The relevance labels have a bias worth recording. A document counts as relevant if it
contains one of the topic's hand-picked `anchor_terms`, scanned over that ticker's documents.
BM25 is also a lexical matcher, so it agrees with this rule by construction. Hybrid lift on
this eval is an upper bound on the lift for real, paraphrased questions.

## Decision

Add both differences to the retrieval Lambda as opt-in request fields, so the original's
served path can be reproduced and each effect measured on its own:

- **`ticker`** (optional): an S3 Vectors metadata filter `{"ticker": {"$eq": ticker}}` on
  the dense query, and the same restriction on the BM25 corpus. `ticker` is already stored as
  metadata on every vector, so no re-index is needed. The filter needs
  `s3vectors:GetVectors` on the retrieval role.
- **`mode: "hybrid"`**: fuse the dense ranking with a BM25 ranking via RRF, then rerank.
  BM25 is built in memory from the corpus rows the Lambda already caches, with no new S3
  object and no always-on resource. Idle cost stays at zero.

Parity with the original:

| Setting | Original (QNT-262) | AWS (this ADR) |
|---|---|---|
| Scope | query's ticker, both legs | same |
| BM25 | `rank_bm25` BM25Okapi, default k1/b | same library, 0.2.2 |
| Tokenizer | lowercase, `\w+` | same |
| Zero-score BM25 docs | dropped | same |
| Candidates per leg | 20 (`RUN_DEPTH`) | 20 (`top_k`) |
| Fusion | RRF, k = 60, ties by id | same |
| Reranked | top 20 fused (`RERANK_CANDIDATES`) | top 20 fused |
| BM25 text, news | headline + body | `text` (headline + body in the snapshot) |
| BM25 text, earnings | title + section + text | section + text (**no title**: the snapshot doesn't carry it) |
| Rerank input text | same searchable text as BM25 | `text` only (unchanged from QNT-269; for earnings this also drops title and section) |
| Embeddings | MiniLM via Qdrant Cloud Inference | Titan V2 (unchanged, the deliberate substrate difference) |

## Alternatives considered

- **A keyword-capable store (OpenSearch Serverless, Aurora pgvector).** Idle-billed (about
  USD 700/mo floor, or min-ACU billing), so it breaks the zero-idle rule and the USD 20 cap.
- **A prebuilt BM25 index object in S3.** It adds a build step and a second artifact to keep
  in sync with the corpus. At 2,000 rows per corpus, building BM25 per request takes
  milliseconds.
- **BM25 without ticker scoping.** It would leave the biggest unrecorded difference in
  place, and the eval couldn't separate the two effects.

## Consequences

- The eval can now report ticker-scoped dense, dense + rerank and hybrid + rerank on the
  same 51 topics. The QNT-483 (unscoped) rows stay as the "before".
- The Lambda package grows to about 32 MB zipped, because `rank-bm25` pulls in numpy. The
  build targets `manylinux_2_28`, since numpy has no manylinux2014 aarch64 wheel for Python
  3.13.
- Hybrid results inherit the lexical-label bias above, and the write-up has to say so.
- The earnings BM25 text lacks the release title. If the earnings hybrid lags the
  original's, that's the first suspect.
