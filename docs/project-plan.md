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
  - Budget hard-stop: AWS Budgets Action auto-attaches a deny policy (scoped to
    S3 Vectors/Lambda-invoke/API Gateway-invoke, never delete/terminate/`budgets:*`)
    to the IAM user at USD 20 spend — a real technical backstop beyond the email alert
    (Bedrock actions dropped from the deny list 2026-08-26, QNT-268 -- ADR-0001; this
    guard only covers AWS-billed actions and never covered OpenRouter spend anyway)

## Phase 1 — Corpus & Index

- [x] QNT-267: frozen corpus snapshot into S3
  - Consumes QNT-265 (monorepo, shipped PR #539) — corpus/{news,earnings}.jsonl, labels, manifest
  - `point_id` (not `doc_id`) preserved verbatim as the join/identity key (PRD §5)
- [x] QNT-268: index job — OpenRouter embeddings into S3 Vectors
  - One S3 Vectors index per corpus (news, earnings); vectors keyed by `point_id`
  - **Triggered by:** scope change 2026-08-26 (was: Bedrock Titan embeddings) — see ADR-0001

## Phase 2 — Retrieval & Eval

- [x] QNT-269: retrieval service — Lambda + Function URL, S3 Vectors + OpenRouter rerank + generation
  - **Triggered by:** scope change 2026-08-26 (was: Bedrock rerank + gpt-oss-20b) — see ADR-0001
  - Per-corpus routing; no NAT Gateway / OpenSearch / Aurora (cost-trap checklist)
  - Decided at implementation: Lambda Function URL (`AWS_IAM` auth) instead of API Gateway —
    free, simpler IaC, keeps the endpoint private (only callers with `lambda:InvokeFunctionUrl`,
    i.e. the operator's own AWS credentials). No reserved-concurrency cap — this account's
    total Lambda concurrency quota is only 10, too low to reserve any of it
- [x] QNT-270: recycle retrieval eval against the cloud endpoint
  - Fills the PRD §7 in-repo-vs-cloud comparison table, per corpus
  - **Triggered by:** confirming or refuting H1/H2/H3 (PRD §7) is the project's core deliverable
  - Results: H1 confirmed (news), H2 refuted (earnings rerank lift is large in-repo, not
    marginal), H3 confirmed for news / partially refuted for earnings (MRR delta sign
    flips) — full writeup in `eval/results/qnt-270-cloud-eval.md`
  - In-repo baseline recomputed per-corpus from `equity-data-agent`'s frozen run files;
    PRD's original blended pre-relabel number superseded (see results doc)

## Phase 3 — Observability & Demo Wrap-up

- [x] QNT-271: CloudWatch logs + metrics for the retrieval service
- [x] QNT-272: demo recording + verified teardown + README
  - Stand-up → query → eval → teardown video; verified empty Cost Explorer
  - Repo flipped PUBLIC after a pre-publish secrets/account-id sweep
