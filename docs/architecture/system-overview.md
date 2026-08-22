# Equity RAG on AWS — System Overview

How the system actually works *now*. Kept current by `change-scope` (on scope changes) and `retro`
(against what actually shipped). If this drifts from reality it is worse than nothing.

> **Status:** Phase 0 (QNT-266) and the QNT-267 S3 corpus seed are live in AWS account
> `000000000000` (us-west-2). Everything below the "Components / layers" table's QNT-268 row is
> still planned, not deployed. Update this doc as each further ticket lands so it never drifts
> from what's actually deployed vs. still planned.

## Architecture

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

Full narrative + rationale for each service choice: PRD §6.

## Components / layers

| Layer | Responsibility | Ships in |
|-------|----------------|----------|
| Terraform skeleton + budget guard | AWS provider (us-west-2), local state backend, USD 10/20 Budgets alerts + auto-deny hard-stop at USD 20 | **QNT-266 — shipped** |
| S3 corpus bucket | Frozen snapshot (corpus JSONL, labels, manifest) staged from the monorepo export | **QNT-267 — shipped** |
| Index job (Lambda, one-shot) | Corpus → Bedrock Titan Text Embeddings V2 → S3 Vectors, one index per corpus | QNT-268 |
| Retrieval service (Lambda + API GW) | Dense search (S3 Vectors) → Bedrock Cohere Rerank 3.5 → gpt-oss-20b generation | QNT-269 |
| Eval client (local) | ir_measures scoring against the cloud endpoint, per-corpus | QNT-270 |
| CloudWatch | Logs + latency/invocation/error metrics for the retrieval Lambda | QNT-271 |

## Data stores

- **S3 (corpus bucket, `equity-rag-aws-corpus-<account-id>`)** — `corpus/{news,earnings}.jsonl`,
  `labels/retrieval.yaml`, `labels/retrieval_qrels.trec`, `manifest.json`, seeded by
  `terraform/s3.tf` from the gitignored local `data/` staging copy (checksums verified against
  `manifest.json` via `scripts/verify_s3_checksums.sh`). Read-only input; identity is `point_id`
  (the Qdrant point id), preserved verbatim — see PRD §5. `doc_id` groups rows back into
  documents but is *not* the eval identity.
- **`eval/`** — the offline `ir_measures` scoring core (`retrieval_eval.py`, trimmed from
  equity-data-agent's `agent.evals.retrieval_eval`) plus a committed copy of the labels
  (`eval/labels/`). Not a deployed component; the QNT-270 eval client imports this module to
  score the cloud endpoint.
- **S3 Vectors** — two indices, one per corpus (`news`, `earnings`), dense-only, keyed by
  `point_id`, tagged with corpus/ticker/date metadata.
- No relational/document store — everything is file-based (S3) or vector-native (S3 Vectors).

## External surfaces

- **API Gateway → retrieval Lambda** — the only runtime endpoint. Request resolves the
  target corpus (per the topic's scope in `labels/retrieval.yaml`), returns reranked dense
  results + a generated answer.
- **Index job** — one-shot, not a persistent surface; triggered manually/by IaC apply, not
  on a schedule (no live ingestion — see PRD §4 non-goals).
- **Eval client** — runs locally against the deployed API Gateway endpoint; not a deployed
  component itself.

## Infrastructure

- **Region:** us-west-2 (pinned — co-locates Bedrock Titan/Cohere Rerank/gpt-oss-20b + S3
  Vectors).
- **Compute:** Lambda only — no NAT Gateway, no provisioned concurrency, no always-on
  compute (architecture rule: zero idle-billed resources).
- **Budget:** USD 20 hard cap. Two layers, both live: an AWS Budgets alert at USD 10 (warning) /
  USD 20 (notification), and a Budgets Action that auto-attaches an IAM deny policy to the
  operator's IAM user at USD 20 — scoped to only this project's billed actions (Bedrock invoke,
  S3 Vectors put/query, Lambda invoke, API Gateway invoke), never delete/terminate/`budgets:*`, so
  `terraform destroy` still works after it fires. Both backstop `terraform destroy` as the actual
  teardown mechanism.
- **State backend:** local (not S3-remote) — solo, single-apply/destroy-cycle project; avoids a
  remote-state bootstrap bucket that itself needs tearing down.
- **Lifecycle:** ephemeral — the stack exists for the demo window (`apply` → query → eval →
  `destroy`), not persistently deployed. No CD, no uptime monitoring, no rollback story
  (PRD §4).
