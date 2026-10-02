# Equity RAG on AWS — System Overview

How the system actually works *now*. Kept current by `change-scope` (on scope changes) and `retro`
(against what actually shipped). If this drifts from reality it is worse than nothing.

> **Status:** All 8 tickets in the delivery plan (QNT-265 through QNT-272) are shipped — this
> project is complete. Model serving moved from Bedrock to OpenRouter mid-Phase-1 (ADR-0001), then
> back to Bedrock once the account's quota defect was fixed (QNT-483, ADR-0002) — the index job and
> retrieval service both call Bedrock with IAM auth, no API keys. QNT-269 decided Lambda
> Function URL (`AWS_IAM` auth) over API Gateway — see the retrieval service row below. QNT-271
> added CloudWatch logs/metrics. QNT-272 recorded the demo, then ran `terraform destroy`
> (verified: empty `terraform state list`, ~$0 next-day Cost Explorer) — **the AWS stack
> described below is torn down, not currently running**; this document describes the
> architecture as built, reproducible from a clean `terraform apply`, not live infrastructure.
> The repo is now public (post-publish secrets/account-id sweep, QNT-272 AC4).

## Architecture

```
                        ┌────────────────────────── Terraform (us-west-2) ─────────────────────────┐
                        │                                                                          │
 monorepo (QNT-265)     │   S3 bucket          index job (Lambda, one-shot)      S3 Vectors        │
 frozen snapshot ─────────► corpus/*.jsonl ──► Bedrock Titan Embeddings V2 ───► index per corpus   │
 + labels + manifest    │   labels/            → PutVectors (point_id-keyed,    (news, earnings)   │
                        │   manifest.json      corpus/ticker/date metadata)           │            │
                        │                                                             ▼            │
 eval client (local) ─────► Function URL ──► retrieval Lambda: dense top-k (S3 Vectors)            │
 ir_measures + labels   │   (AWS_IAM auth)  → Bedrock Cohere Rerank 3.5 → [optional gpt-oss-20b]   │
                        │                                      │                                   │
                        │   CloudWatch  ◄── logs + latency/invocation/error metrics                │
                        │   AWS Budgets ◄── USD 20 alert + auto-deny hard-stop (covers Bedrock)    │
                        └──────────────────────────────────────────────────────────────────────────┘
   (Bedrock on-demand quotas on this account, all non-adjustable: Titan 60, Rerank 3, gpt-oss 100
    requests/min — the index job runs in ≤800-row slices and the eval client paces itself. ADR-0002.)
```

Full narrative + rationale for each service choice: PRD §6.

## Components / layers

| Layer | Responsibility | Ships in |
|-------|----------------|----------|
| Terraform skeleton + budget guard | AWS provider (us-west-2), local state backend, USD 10/20 Budgets alerts + auto-deny hard-stop at USD 20 | **QNT-266 — shipped** |
| S3 corpus bucket | Frozen snapshot (corpus JSONL, labels, manifest) staged from the monorepo export | **QNT-267 — shipped** |
| Index job (Lambda, invoked per corpus slice) | Corpus → Bedrock Titan V2 → S3 Vectors, one index per corpus | **QNT-268 — shipped; Bedrock QNT-483** |
| Retrieval service (Lambda + Function URL, `AWS_IAM` auth) | Dense search (S3 Vectors) → Bedrock Cohere Rerank 3.5 → Bedrock gpt-oss-20b generation | **QNT-269 — shipped; Bedrock QNT-483** |
| Eval client (local) | ir_measures scoring against the cloud endpoint, per-corpus | **QNT-270 — shipped** |
| CloudWatch | Logs (Terraform-managed log group) + latency/invocation/error metrics for the retrieval Lambda | **QNT-271 — shipped** |

## Data stores

- **S3 (corpus bucket, `equity-rag-aws-corpus-<account-id>`)** — `corpus/{news,earnings}.jsonl`,
  `labels/retrieval.yaml`, `labels/retrieval_qrels.trec`, `manifest.json`, seeded by
  `terraform/s3.tf` from the gitignored local `data/` staging copy (checksums verified against
  `manifest.json` via `scripts/verify_s3_checksums.sh`). Read-only input; identity is `point_id`
  (the Qdrant point id), preserved verbatim — see PRD §5. `doc_id` groups rows back into
  documents but is *not* the eval identity.
- **`eval/`** — the offline `ir_measures` scoring core (`retrieval_eval.py`, trimmed from
  equity-data-agent's `agent.evals.retrieval_eval`) plus a committed copy of the labels
  (`eval/labels/`). Not a deployed component; `cloud_eval.py` (QNT-270) SigV4-signs one
  request per labeled topic against the deployed Function URL, reconstructs dense-only and
  dense+rerank rankings from the response, and scores both per-corpus. Results + hypothesis
  assessment (H1/H2/H3) live in `eval/results/qnt-483-bedrock-eval.md` (Titan V2, current) and
  `eval/results/qnt-270-cloud-eval.md` (OpenRouter embeddings, kept for comparison).
- **S3 Vectors** — two indices, one per corpus (`news`, `earnings`), dense-only, keyed by
  `point_id`, tagged with corpus/ticker/date metadata. Populated by the QNT-268 index job
  (512-dim cosine, Bedrock Titan Text Embeddings V2). Queried (not written) by
  the QNT-269 retrieval service, which joins hits back to source text from the S3 corpus
  bucket (S3 Vectors metadata doesn't carry the full text).
- No relational/document store — everything is file-based (S3) or vector-native (S3 Vectors).

## External surfaces

- **Lambda Function URL (`AWS_IAM` auth) → retrieval Lambda** — the only runtime endpoint.
  Request resolves the target corpus (per the topic's scope in `labels/retrieval.yaml`), does
  dense search (S3 Vectors) → Bedrock Cohere Rerank 3.5 → optional Bedrock gpt-oss-20b generation,
  returns reranked dense results + a generated answer. IAM auth (not API Gateway) keeps it
  private — only callers with `lambda:InvokeFunctionUrl` (the operator's own AWS credentials)
  can invoke it (no reserved-concurrency cap — this account's total Lambda concurrency quota
  is only 10, too low to reserve any of it). Rerank's 3 requests/min Bedrock quota caps it at
  about 3 queries/min. Sample-query smoke test:
  `scripts/invoke_retrieval.py`.
- **Index job** — one-shot, not a persistent surface; triggered manually/by IaC apply, not
  on a schedule (no live ingestion — see PRD §4 non-goals).
- **Eval client** (`eval/cloud_eval.py`) — runs locally against the deployed Function URL
  endpoint (SigV4-signed), one call per labeled topic, `generate=false`; not a deployed
  component itself.

## Infrastructure

- **Region:** us-west-2 — co-locates S3 Vectors with all three Bedrock models (ADR-0002).
- **Compute:** Lambda only — no NAT Gateway, no provisioned concurrency, no always-on
  compute (architecture rule: zero idle-billed resources).
- **Budget:** USD 20 hard cap, covering all project spend, Bedrock included. Two layers: an AWS Budgets
  alert at USD 10 (warning) / USD 20 (notification), and a Budgets Action that auto-attaches
  an IAM deny policy to the operator's IAM user at USD 20 — scoped to only this project's
  billed AWS actions (Bedrock invoke, S3 Vectors put/query, Lambda invoke, Function URL invoke),
  never delete/terminate/`budgets:*`, so `terraform destroy` still works after it fires.
- **Secrets:** none — pure IAM auth. (The OpenRouter API key that existed under ADR-0001 was
  removed in QNT-483.)
- **State backend:** local (not S3-remote) — solo, single-apply/destroy-cycle project; avoids a
  remote-state bootstrap bucket that itself needs tearing down.
- **Lifecycle:** ephemeral — the stack exists for the demo window (`apply` → query → eval →
  `destroy`), not persistently deployed. No CD, no uptime monitoring, no rollback story
  (PRD §4).
