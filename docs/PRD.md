# PRD — Equity RAG on AWS

| | |
|---|---|
| **Status** | Active — QNT-265 (producer seam) shipped, QNT-266..272 not yet started |
| **Date** | 2026-07-10 (last reviewed 2026-08-26 — Bedrock → OpenRouter substrate change, ADR-0001) |
| **Tracker** | Linear project *Equity RAG on AWS* (Quant team), QNT-266..272 |
| **Parent project** | [equity-data-agent](https://github.com/noahwins-ng/equity-data-agent) (Track 2: RAG depth + eval) |
| **Budget** | USD 20 hard cap, then `terraform destroy` |

## 1. One-liner

Re-platform the equity-data-agent's *evaluated* RAG retrieval pipeline onto AWS-native
storage (S3 Vectors) with OpenRouter as the model-serving layer, score it with the **identical** offline retrieval eval,
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
Same corpus, same labels, same metrics — different embeddings (an OpenRouter-routed
embedding model instead of the in-repo model), different vector store (S3 Vectors instead
of Qdrant), same reranker (Cohere Rerank 3.5, via OpenRouter instead of Cohere's own API
directly). If the news/earnings regime difference holds across substrates, it's a property
of the corpora — not an artifact of one stack.

> **2026-08-26 substrate change:** the model-serving layer was re-platformed from AWS
> Bedrock to OpenRouter after AWS Support failed to resolve a confirmed account-level
> Bedrock provisioning defect (on-demand throughput quota stuck at 0 for every model,
> non-adjustable) across multiple support cases. S3 Vectors (the vector store) is
> unaffected — this only changes which service serves the embedding/rerank/generation
> models. See ADR-0001.

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

This repo consumes a frozen export produced by the monorepo (QNT-265, **shipped** PR #539,
2026-07-12 — **this section is the spec it implemented against**). Build-time data handoff
only; zero code coupling.

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
  - **Text, not vectors.** Vectors are recomputed with an OpenRouter-routed embedding
    model — re-embedding into a different space is the point of the experiment.
- `labels/retrieval.yaml` — the 51 topics (query + expected corpus + ticker scope).
- `labels/retrieval_qrels.trec` — TREC qrels keyed on `point_id`; every qrels id joins to
  exactly one snapshot row. Runs use 1-based ranks.
- `manifest.json` — per-corpus row counts, date window, export commit SHA, checksums.

**Eval framing baked into the manifest:** news = the *treatment* corpus (ranking-hard,
where rerank pays); earnings = the *control* corpus (dense-saturated). The cloud eval is
a designed two-arm comparison, not an accident.

**Staging path (decided 2026-07-12, mirrored in QNT-265):** the export script takes the
output directory as a CLI argument (no hardcoded sibling-repo path); the canonical
staging location is this repo's `data/` folder, which stays gitignored. Neither repo
commits the bundle — news rows carry vendor-sourced (Finnhub) article bodies and this
repo is public; the durable home is S3 (QNT-267). Integrity across the handoff is
carried by the manifest checksums, not by where the files sit.

## 6. Architecture

```
                        ┌────────────────────────── Terraform (us-west-2) ─────────────────────────┐
                        │                                                                          │
 monorepo (QNT-265)     │   S3 bucket          index job (Lambda, one-shot)      S3 Vectors        │
 frozen snapshot ─────────► corpus/*.jsonl ──► OpenRouter embedding model ────► index per corpus   │
 + labels + manifest    │   labels/            → PutVectors (point_id-keyed,    (news, earnings)   │
                        │   manifest.json      corpus/ticker/date metadata)           │            │
                        │                                                             ▼            │
 eval client (local) ─────► API Gateway ──► retrieval Lambda:  dense top-k (S3 Vectors)            │
 ir_measures + labels   │                    → OpenRouter Cohere Rerank 3.5 → [optional gpt-oss-20b]│
                        │                                      │                                   │
                        │   CloudWatch  ◄── logs + latency/invocation/error metrics                │
                        │   AWS Budgets ◄── USD 20 alert (AWS spend only — see §8 for the           │
                        │                    separate OpenRouter spend-limit guard)                 │
                        └──────────────────────────────────────────────────────────────────────────┘
              (OpenRouter is an external HTTPS API, not AWS infra — not Terraform-managed,
               reached over Lambda's default internet egress, no VPC/NAT needed)
```

**Service choices (and why):**

| Choice | Why | Rejected alternative |
|---|---|---|
| **S3 Vectors** (GA Dec 2025) | Zero idle floor, pay-per-use, trivially destroyed. 100–800 ms query latency is fine for an offline eval. | OpenSearch Serverless (~USD 700/mo floor), Aurora pgvector (min-ACU idle billing) |
| **`openai/text-embedding-3-small` via OpenRouter** | Single OpenAI-API-compatible endpoint; cheap, fast, truncatable to 512-dim via the `dimensions` param; a *deliberately different* embedding space from the in-repo model | AWS Bedrock — abandoned 2026-08-26 after a confirmed, unresolved AWS account-level quota provisioning defect (see ADR-0001); reusing in-repo vectors was already rejected (would defeat the substrate-change experiment) |
| **Cohere Rerank 3.5 via OpenRouter** | The *same model* as the in-repo rerank path — isolates the substrate variable. Same model as originally planned, just a different host (was: via Bedrock) | A different reranker (would confound the comparison) |
| **gpt-oss-20b via OpenRouter** | Same open-weight family as the parent project's generation path | A pricier proprietary model (generation isn't what's being measured) |
| **Lambda + API Gateway** | Zero idle cost, IaC-trivial | ECS/Fargate service (idle-billed) |
| **us-west-2** | S3 Vectors availability. (Previously also justified by Bedrock model co-location — moot now that model serving is via OpenRouter, an AWS-region-independent SaaS API) | — |

## 7. Eval plan

Same metrics, same labels, scored per-corpus — the deliverable of the whole project is
this table (filled in by QNT-270):

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | in-repo dense (Qdrant) | 0.48 | 0.72 | 0.85 | 0.70 |
| news | in-repo hybrid+rerank (Qdrant) | 0.53 | 0.76 | 0.94 | 0.79 |
| news | **cloud dense (S3 Vectors)** | ? | ? | ? | ? |
| news | **cloud dense+rerank (S3 Vectors + OpenRouter)** | ? | ? | ? | ? |
| earnings | in-repo (per-corpus numbers from monorepo) | … | … | … | … |
| earnings | **cloud dense / dense+rerank** | ? | ? | ? | ? |

**Hypotheses (stated before running — H1/H2 are the experiment):**

- **H1 (news):** cloud dense+rerank lands *between* in-repo dense-only and in-repo
  hybrid+rerank — rerank recovers most of the missing BM25 leg's lift.
- **H2 (earnings):** rerank lift stays marginal on the cloud too — the dense-saturated
  regime is a corpus property, not a stack property.
- **H3 (embeddings):** the OpenRouter embedding model's dense-only results differ from
  in-repo dense-only (different space), but the *rerank delta* is directionally consistent.

Any outcome is publishable: confirmation proves the regime finding generalizes;
refutation is a genuinely interesting substrate effect and gets written up as such.

## 8. Budget and teardown

- **Hard cap:** USD 20 total for **AWS spend**, enforced socially by `terraform destroy`
  and mechanically backstopped by an AWS Budgets alert at USD 20 (and a warning threshold
  at USD 10).
- **Zero idle-billed resources** is an architecture rule: no NAT gateway, no provisioned
  concurrency, no OpenSearch, no always-on compute. Everything is pay-per-request.
- **AWS spend (verified against current AWS pricing, 2026-08-19):**

  | Line item | Rate (us-west-2) | This project's scale | Est. cost |
  |---|---|---|---|
  | S3 Vectors storage | $0.06 / GB-month | <0.1 GB | ~$0.01 |
  | S3 Vectors writes (PUT) | $0.20 / GB | <0.1 GB | ~$0.02 |
  | S3 Vectors queries | $2.50/1M queries + $0.004/TB processed (first 100K vectors) + $0.01/GB returned (first 512KB/query free) | few hundred queries, tiny index | ~$0.05 |
  | Lambda | 1M requests + 400K GB-seconds/month free (perpetual) | hundreds–low thousands of invocations | ~$0 |
  | API Gateway | $3.50/1M requests (12-month new-account free tier — don't assume it applies) | same low volume | ~$0.01–0.02 even without free tier |
  | S3 (corpus/labels), CloudWatch, AWS Budgets | negligible / free at this scale | — | ~$0 |
  | **AWS total estimate** | | | **~$0.10**, well inside the USD 20 cap |

- **OpenRouter spend (separate from the AWS cap — see the guard below):** embedding the
  corpus (~5–10M tokens across index build + re-runs, via `openai/text-embedding-3-small`
  — §6), reranking 51 topics × several eval sweeps + dev iteration (the same dominant-cost
  pattern the old Cohere-Rerank-3.5-via-Bedrock estimate flagged — rerank is priced
  per-query, not per-token, so repeated dev-time eval sweeps drive it, not corpus size),
  and light spot-check generation. **Observed so far (2026-08-26, QNT-268):** the
  OpenRouter key's `/credits` endpoint reported `total_usage: ~$6.10` after running both
  corpora through the index job (3,897 embedding calls total) — but that figure is the
  key's cumulative total, not broken down by model/call, so it isn't a clean
  attribution to just this work (it may include other usage on the same key, and is
  higher than a naive estimate off OpenAI's published per-token embedding rate would
  suggest, implying either an OpenRouter markup or unaccounted-for usage). Check the
  OpenRouter dashboard's per-request usage log for a real breakdown before trusting this
  number for planning; update this line once confirmed. Rerank + generation costs (QNT-269)
  are still entirely unmeasured.
- **The AWS Budgets $20 hard-stop does NOT cover OpenRouter spend** — it only denies AWS
  API actions and has zero visibility into a third-party vendor's billing. **Mitigation
  (required, not optional):** configure a spend limit directly in the OpenRouter dashboard
  before any real usage — this is now the primary cost guard for the dominant cost driver
  (rerank), not the AWS Budgets alert. See ADR-0001.
- **Teardown is verified, not assumed:** after `terraform destroy`, assert zero remaining
  AWS resources (`terraform state list` empty) and an empty next-day Cost Explorer. The
  demo video *includes* the teardown. (OpenRouter has no "teardown" — there's no persistent
  resource there to destroy, just API usage; confirm no unexpected residual spend via the
  OpenRouter dashboard instead.)

## 9. Delivery plan

Dependency: **QNT-265 (monorepo) ships the snapshot first** — implemented against §5.

| # | Ticket | Scope | Depends on |
|---|---|---|---|
| 0 | QNT-265 *(monorepo)* | Snapshot export (producer side of §5) — **shipped, PR #539** | — |
| 1 | QNT-266 | Repo scaffold + Terraform skeleton + USD 20 budget guard | — |
| 2 | QNT-267 | Frozen corpus snapshot into S3 | 265, 266 |
| 3 | QNT-268 | Index job — OpenRouter embeddings into S3 Vectors | 267 |
| 4 | QNT-269 | Retrieval service — Lambda + API GW, S3 Vectors + OpenRouter rerank + generation | 268 |
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
| ~~Bedrock model access requires per-model enablement~~ — **realized 2026-08-26**: AWS account hit a confirmed, unresolved Bedrock provisioning defect (quota stuck at 0, non-adjustable, multiple support cases unresolved) | Model-serving layer re-platformed to OpenRouter (ADR-0001); no longer an open risk for this project |
| S3 Vectors query latency (100–800 ms) or API shape surprises | Latency is irrelevant to offline eval; spike a 10-vector index in QNT-266 to confirm the API |
| Rerank quota/throttling during eval sweeps | Throttle the eval client (the monorepo already learned this: unthrottled 51-topic sweeps 429 and understate results) |
| **AWS Budgets $20 hard-stop has zero visibility into OpenRouter spend** — the dominant cost driver (rerank) is no longer covered by the AWS-side safety net | Configure a spend limit directly in the OpenRouter dashboard before any real usage (§8) |
| OpenRouter account-level rate limits or new-account restrictions (same failure category as the Bedrock defect) | **Confirmed clean 2026-08-26** — 3,897 real embedding calls (both corpora, QNT-268) completed with zero errors. Re-verify if QNT-269 (higher-volume rerank/generation traffic) sees throttling |
| QNT-265 slips | §5 is the contract; cloud-side work through QNT-266 can proceed in parallel, QNT-267+ blocks |
| Cost surprise from a forgotten AWS resource | Budgets alert + `terraform state list` as the single inventory + teardown in the demo script |

## 12. References

- Monorepo planning doc: `equity-data-agent/docs/v2-overall-enhancement.md` (Track 3)
- Regime finding + per-corpus eval discipline: monorepo QNT-261/262/274/279
- S3 Vectors availability + pricing: verified 2026-08-19 against current AWS docs (see §8
  for the pricing breakdown).
- ADR-0001: model-serving substrate change from AWS Bedrock to OpenRouter (2026-08-26).
