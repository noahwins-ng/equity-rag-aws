# Equity RAG on AWS — Plan

The narrative tracker. One checkbox item per ticket, grouped by phase (= Linear milestone).
`ship` ticks an item when its ticket merges; `change-scope` adds/removes items when scope shifts;
`sync-plan` reconciles this against the tracker. Every shipped ticket MUST appear here — the plan
is what a reader who opens the repo cold uses to understand what was built and why.

> Item format: `- [ ] <ISSUE-ID>: <short title>` with optional sub-bullets for deliverables or a
> `**Triggered by:**` note explaining why the ticket exists.

## Phase 0 — Foundation

- [x] QNT-266: repo scaffold + Terraform skeleton + USD 20 budget guard
  - Terraform skeleton pinned to us-west-2; state backend
  - AWS Budgets alerts at USD 10 (warning) / USD 20 (hard cap)
  - README scaffold: Hetzner → AWS mapping table + dense-vs-hybrid tradeoff note

## Phase 1 — Corpus & Index

- [ ] QNT-267: frozen corpus snapshot into S3
  - Consumes QNT-265 (monorepo, shipped PR #539) — corpus/{news,earnings}.jsonl, labels, manifest
  - `point_id` (not `doc_id`) preserved verbatim as the join/identity key (PRD §5)
- [ ] QNT-268: index job — Bedrock Titan embeddings into S3 Vectors
  - One S3 Vectors index per corpus (news, earnings); vectors keyed by `point_id`

## Phase 2 — Retrieval & Eval

- [ ] QNT-269: retrieval service — Lambda + API Gateway, S3 Vectors + Bedrock rerank + gpt-oss-20b
  - Per-corpus routing; no NAT Gateway / OpenSearch / Aurora (cost-trap checklist)
  - Open question to decide at implementation: Lambda Function URL (`AWS_IAM` auth) instead
    of API Gateway — free, simpler IaC, and keeps the endpoint private (vs. a public `NONE`-auth
    URL, a cost-risk against the $20 cap); pair with a small reserved-concurrency cap either way
- [ ] QNT-270: recycle retrieval eval against the cloud endpoint
  - Fills the PRD §7 in-repo-vs-cloud comparison table, per corpus
  - **Triggered by:** confirming or refuting H1/H2/H3 (PRD §7) is the project's core deliverable

## Phase 3 — Observability & Demo Wrap-up

- [ ] QNT-271: CloudWatch logs + metrics for the retrieval service
- [ ] QNT-272: demo recording + verified teardown + README
  - Stand-up → query → eval → teardown video; verified empty Cost Explorer
  - Repo flipped PUBLIC after a pre-publish secrets/account-id sweep
