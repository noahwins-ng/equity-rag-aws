# PRD — Equity RAG on AWS

| | |
|---|---|
| **Status** | Draft v1 |
| **Date** | 2026-07-10 |
| **Tracker** | Linear project *Equity RAG on AWS* (Quant team), QNT-266..272 |
| **Parent project** | [equity-data-agent](https://github.com/noahwins-ng/equity-data-agent) (Track 2: RAG depth + eval) |
| **Budget** | USD 20 hard cap, then `terraform destroy` |

## 1. One-liner

Re-platform the equity-data-agent's *evaluated* RAG retrieval pipeline onto AWS-native
primitives (S3 Vectors + Bedrock), score it with the **identical** offline retrieval eval,
and publish a per-corpus before/after comparison — then tear the stack down. The durable
artifacts are this repo (Terraform + Lambda code), the comparison table, and a demo video.

## 2. Context

The parent monorepo ships a RAG stack that was built measurement-first:

- Two corpora in Qdrant: **news** (Finnhub articles) and **earnings** (EDGAR 8-K
  Item 2.02 / Ex 99.1), 10 US tickers.
- A deterministic retrieval eval (`ir_measures`): 51 labeled topics, TREC qrels,
  recall@5/@20, MRR, nDCG@10 — gated per-PR in CI against frozen runs.
- Measured, per-corpus results on the news corpus (frozen-run numbers):

| Configuration | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|
| Dense only | 0.48 | 0.72 | 0.85 | 0.70 |
| Hybrid (BM25 + RRF) | +0.04 | +0.10 | +0.03 | +0.06 |
| Hybrid + Cohere Rerank 3.5 | 0.53 | 0.76 | 0.94 | 0.79 |

- **The regime finding** (the core insight this project carries forward): hybrid + rerank
  lift retrieval substantially on **news** (large, lexically diverse, ranking-hard) and
  barely move **earnings** (small, templated, dense-saturated — retrieval there is really
  a `(ticker, period)` *filter* problem). Reported per-corpus, never blended.

This project asks: **does that behavior reproduce on a completely different substrate?**
Same corpus, same labels, same metrics — different embeddings (Titan V2 instead of the
in-repo model), different vector store (S3 Vectors instead of Qdrant), same reranker
(Cohere Rerank 3.5, via Bedrock instead of Cohere's API). If the news/earnings regime
difference holds across substrates, it's a property of the corpora — not an artifact of
one stack.

## 3. Goals

1. **G1 — Faithful re-platform.** Reproduce the retrieval flow (dense search → rerank →
   optional generation) on AWS serverless primitives, defined 100% in Terraform.
2. **G2 — Same eval, new substrate.** Run the identical `ir_measures` scoring + identical
   relevance labels against the cloud endpoint; produce a per-corpus in-repo vs. cloud
   comparison table.
3. **G3 — Cost-bounded and ephemeral.** Total spend ≤ USD 20. Zero idle-billed services.
   Verified clean teardown (empty Cost Explorer after `terraform destroy`).
4. **G4 — Durable artifacts.** This repo (IaC + code + docs), the comparison table, and a
   recorded demo: `apply` → query → eval → `destroy`.

## 4. Non-goals

- **No hybrid/BM25 on the cloud path.** S3 Vectors is dense-only; the cloud runs
  dense + rerank. This is a *documented tradeoff*, and the eval quantifies exactly what
  the missing BM25 leg costs (expectation: cloud news numbers land between the in-repo
  dense-only and hybrid+rerank rows).
- **No live ingestion.** The corpus is a frozen snapshot (build-time handoff from the
  monorepo, QNT-265). No Dagster, no schedulers, no freshness.
- **No agent.** This is the retrieval + generation slice only — no LangGraph, no intent
  classification, no thesis synthesis.
- **No persistent deployment.** The stack exists for the demo window, then is destroyed.
  There is no CD, no uptime monitoring, no rollback story.

## 5. Input: the snapshot seam (contract with QNT-265)

This repo consumes a frozen export produced by the monorepo (QNT-265, not yet shipped —
**this section is the spec it implements against**). Build-time data handoff only; zero
code coupling.

**Snapshot bundle** (versioned, checksummed). The snapshot is frozen at each corpus's
**native Qdrant granularity, sourced from the Qdrant payloads**, so the exact embedded
text and its id travel together (a doc-level export would force this repo to reproduce the
monorepo's chunker to join labels back to text). The two corpora do **not** share one
granularity or one point-id formula:

- **earnings** (`equity_earnings`) is **chunk-level** — one row per chunk, with
  `chunk_index` + `section`.
- **news** (`equity_news`) is **article-level** — one row per (ticker, article), no
  `chunk_index`, no `section`; `text` is the embedded headline + body.

- `corpus/{news,earnings}.jsonl` — one row per Qdrant point:
  - `point_id` — **the Qdrant point id, derived per corpus**: earnings
    `blake2b(ticker:doc_id:chunk_index)`, news `blake2b(ticker:url_id)`. This is the
    identity the qrels key on and MUST be preserved verbatim as the S3 Vectors key.
  - `doc_id` — release/article-level id that groups rows back into documents; *not* the
    eval identity.
  - `chunk_index` — position within the document. **Earnings only** (absent for news).
  - `corpus` — `news` | `earnings`. Every row and every relevance label is corpus-tagged
    so the cloud eval can score per-corpus; without the tag the regime finding is
    invisible downstream.
  - `ticker`, `date`, `text` (the exact embedded text), `source_url`, and `section`
    (**earnings only**).
  - **Text, not vectors.** Vectors are recomputed with Titan V2 — re-embedding into a
    different space is the point of the experiment.
- `labels/retrieval.yaml` — the 51 topics (query + expected corpus + ticker scope).
- `labels/retrieval_qrels.trec` — TREC qrels keyed on `point_id`; every qrels id joins to
  exactly one snapshot row. Runs use 1-based ranks.
- `manifest.json` — per-corpus row counts, date window, export commit SHA, checksums.

**Eval framing baked into the manifest:** news = the *treatment* corpus (ranking-hard,
where rerank pays); earnings = the *control* corpus (dense-saturated). The cloud eval is
a designed two-arm comparison, not an accident.

## 6. Architecture

```
                        ┌────────────────────────── Terraform (us-west-2) ─────────────────────────┐
                        │                                                                          │
 monorepo (QNT-265)     │   S3 bucket          index job (Lambda, one-shot)      S3 Vectors        │
 frozen snapshot ─────────► corpus/*.jsonl ──► Bedrock Titan Text Embeddings ──► index per corpus  │
 + labels + manifest    │   labels/            V2 → PutVectors (point_id-keyed,  (news, earnings)  │
                        │   manifest.json      corpus/ticker/date metadata)           │            │
                        │                                                             ▼            │
 eval client (local) ─────► API Gateway ──► retrieval Lambda:  dense top-k (S3 Vectors)            │
 ir_measures + labels   │                    → Bedrock Cohere Rerank 3.5 → [optional gpt-oss-20b]  │
                        │                                      │                                   │
                        │   CloudWatch  ◄── logs + latency/invocation/error metrics                │
                        │   AWS Budgets ◄── USD 20 alert (backstop to terraform destroy)           │
                        └──────────────────────────────────────────────────────────────────────────┘
```

**Service choices (and why):**

| Choice | Why | Rejected alternative |
|---|---|---|
| **S3 Vectors** (GA Dec 2025) | Zero idle floor, pay-per-use, trivially destroyed. 100–800 ms query latency is fine for an offline eval. | OpenSearch Serverless (~USD 700/mo floor), Aurora pgvector (min-ACU idle billing) |
| **Titan Text Embeddings V2** | Bedrock-native, cheap, 256/512/1024-dim options; a *deliberately different* embedding space from the in-repo model | Reusing in-repo vectors (would defeat the substrate-change experiment) |
| **Cohere Rerank 3.5 on Bedrock** | The *same model* as the in-repo rerank path — isolates the substrate variable | A different reranker (would confound the comparison) |
| **gpt-oss-20b on Bedrock** | Same open-weight family as the parent project's generation path | Claude on Bedrock (pricier; generation isn't what's being measured) |
| **Lambda + API Gateway** | Zero idle cost, IaC-trivial | ECS/Fargate service (idle-billed) |
| **us-west-2** | Co-locates all three Bedrock models + S3 Vectors | — |

## 7. Eval plan

Same metrics, same labels, scored per-corpus — the deliverable of the whole project is
this table (filled in by QNT-270):

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | in-repo dense (Qdrant) | 0.48 | 0.72 | 0.85 | 0.70 |
| news | in-repo hybrid+rerank (Qdrant) | 0.53 | 0.76 | 0.94 | 0.79 |
| news | **cloud dense (S3 Vectors)** | ? | ? | ? | ? |
| news | **cloud dense+rerank (S3 Vectors + Bedrock)** | ? | ? | ? | ? |
| earnings | in-repo (per-corpus numbers from monorepo) | … | … | … | … |
| earnings | **cloud dense / dense+rerank** | ? | ? | ? | ? |

**Hypotheses (stated before running — H1/H2 are the experiment):**

- **H1 (news):** cloud dense+rerank lands *between* in-repo dense-only and in-repo
  hybrid+rerank — rerank recovers most of the missing BM25 leg's lift.
- **H2 (earnings):** rerank lift stays marginal on the cloud too — the dense-saturated
  regime is a corpus property, not a stack property.
- **H3 (embeddings):** Titan V2 dense-only differs from in-repo dense-only (different
  space), but the *rerank delta* is directionally consistent.

Any outcome is publishable: confirmation proves the regime finding generalizes;
refutation is a genuinely interesting substrate effect and gets written up as such.

## 8. Budget and teardown

- **Hard cap:** USD 20 total, enforced socially by `terraform destroy` and mechanically
  backstopped by an AWS Budgets alert at USD 20 (and a warning threshold at USD 10).
- **Zero idle-billed resources** is an architecture rule: no NAT gateway, no provisioned
  concurrency, no OpenSearch, no always-on compute. Everything is pay-per-request.
- **Expected spend (estimates — verify real pricing during QNT-266):** corpus is small
  (thousands of chunks): Titan embedding + S3 Vectors storage/query = cents; Bedrock
  rerank on 51 topics × a handful of eval sweeps = low single dollars; Lambda/API GW
  within free tier. The cap has generous headroom for demo retakes.
- **Teardown is verified, not assumed:** after `terraform destroy`, assert zero remaining
  resources (`terraform state list` empty) and an empty next-day Cost Explorer. The demo
  video *includes* the teardown.

## 9. Delivery plan

Dependency: **QNT-265 (monorepo) ships the snapshot first** — implemented against §5.

| # | Ticket | Scope | Depends on |
|---|---|---|---|
| 0 | QNT-265 *(monorepo)* | Snapshot export (producer side of §5) | — |
| 1 | QNT-266 | Repo scaffold + Terraform skeleton + USD 20 budget guard | — |
| 2 | QNT-267 | Frozen corpus snapshot into S3 | 265, 266 |
| 3 | QNT-268 | Index job — Titan embeddings into S3 Vectors | 267 |
| 4 | QNT-269 | Retrieval service — Lambda + API GW, S3 Vectors + rerank + gpt-oss-20b | 268 |
| 5 | QNT-270 | Recycle retrieval eval against the cloud endpoint (fills §7 table) | 269 |
| 6 | QNT-271 | CloudWatch logs + metrics | 269 |
| 7 | QNT-272 | Demo recording + verified teardown + README | 270, 271 |

## 10. Success criteria

1. `terraform apply` from a clean checkout stands up the full stack; no console-created
   resources (everything destroyable by `terraform destroy`).
2. The §7 comparison table is filled with real numbers, per-corpus, and H1–H3 are each
   explicitly confirmed or refuted in the README.
3. Total spend ≤ USD 20 (Cost Explorer screenshot in the README).
4. Teardown verified: empty `terraform state list` + empty next-day Cost Explorer.
5. Demo video covers apply → query → eval comparison → destroy.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Bedrock model access requires per-model enablement (Titan / Cohere / gpt-oss) | Request access during QNT-266, before any dependent work |
| S3 Vectors query latency (100–800 ms) or API shape surprises | Latency is irrelevant to offline eval; spike a 10-vector index in QNT-266 to confirm the API |
| Rerank quota/throttling during eval sweeps | Throttle the eval client (the monorepo already learned this: unthrottled 51-topic sweeps 429 and understate results) |
| QNT-265 slips | §5 is the contract; cloud-side work through QNT-266 can proceed in parallel, QNT-267+ blocks |
| Cost surprise from a forgotten resource | Budgets alert + `terraform state list` as the single inventory + teardown in the demo script |

## 12. References

- Monorepo planning doc: `equity-data-agent/docs/v2-overall-enhancement.md` (Track 3)
- Regime finding + per-corpus eval discipline: monorepo QNT-261/262/274/279
- S3 Vectors, Bedrock model availability + pricing: verify current docs at QNT-266
