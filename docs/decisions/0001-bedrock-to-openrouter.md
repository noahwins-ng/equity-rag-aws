# ADR-0001: Drop AWS Bedrock for OpenRouter as the model-serving layer

- **Status:** accepted
- **Date:** 2026-08-26
- **Ticket:** QNT-268 (also affects QNT-269)

## Context

The project's original design (PRD §6) served all three models — Titan Text Embeddings V2,
Cohere Rerank 3.5, and gpt-oss-20b — via AWS Bedrock, chosen specifically to co-locate with
S3 Vectors in `us-west-2` and to keep the whole stack inside one AWS account/Terraform
lifecycle.

While implementing QNT-268 (the index job), every `InvokeModel` call failed with
`ThrottlingException`, and in some regions with `AccessDeniedException: "Your account is
currently being verified."` Investigation (spanning several days) established:

- Every Bedrock model's on-demand throughput quota (requests/min, tokens/min) was **0** for
  this account, across every region checked (us-west-2, us-east-1/2, us-west-1,
  ca-central-1, eu-west-1/2, eu-central-1, ap-southeast-1/2, ap-northeast-1, ap-south-1).
- This was **not** an IAM permissions issue (the IAM user has `AdministratorAccess`) or an
  entitlement/agreement issue (`GetFoundationModelAvailability` showed
  `agreementAvailability`/`authorizationStatus`/`entitlementAvailability` all
  `AVAILABLE`/`AUTHORIZED` for every model checked, including after manually completing the
  Cohere Rerank 3.5 Marketplace agreement).
- Self-service quota increase is explicitly blocked at the API level
  (`service-quotas request-service-quota-increase` →
  `IllegalArgumentException: The request failed because the specified quota is not
  adjustable`), and the Bedrock console's per-model "Request quota increase" action shows
  "Not supported" for every model needed.
- Tested and ruled out: alternate regions (quota values were inconsistent/flaky across
  repeated checks — cannot be relied on), the newer Bedrock API-key auth flow (hit the
  identical quota wall once tested in its own credential-scope region), and the AWS
  "Getting Started" quickstart flow (no missed onboarding step — the account is correctly
  set up; the automatic default-quota-seeding step that's supposed to fire once model
  entitlement is granted simply never fired for this account).
- External research (AWS re:Post threads, a dev.to writeup) confirmed this matches a
  documented, known class of AWS account-provisioning defect: new accounts are supposed to
  be auto-seeded with AWS's standard default quotas (6000 req/min for Titan V2) once
  entitlement is granted, but that seeding step can silently fail, leaving an account
  permanently stuck at 0 until AWS Support/engineering manually intervenes. No self-service
  workaround exists; reported resolution times in similar cases range from 4-5 days to 15+
  days, with some cases needing several rounds of escalation.
- Two AWS Support cases were filed (the account is on Basic support, which has no Technical
  support case type and no Support API access) — both remained unassigned/unresolved after
  several days.

Given no forecastable resolution timeline and no technical workaround, continuing to wait
was judged not worth the schedule risk to the project.

## Decision

Drop AWS Bedrock as the model-serving layer entirely. Serve all three models — an
embedding model, Cohere Rerank 3.5, and a generation model (gpt-oss-20b or equivalent) —
through **OpenRouter** instead, using its OpenAI-API-compatible unified endpoint for
embeddings, rerank, and chat completions.

S3 Vectors (the vector store) is unaffected — it is a separate AWS service, not part of
Bedrock, and nothing about its Terraform configuration or the `point_id`-keyed identity
contract (PRD §5) changes.

Region stays `us-west-2` for S3 Vectors' sake; the "co-locates all three Bedrock models"
rationale no longer applies, since OpenRouter is a region-independent SaaS API reached over
the Lambda's default internet egress (no NAT Gateway needed either way).

The OpenRouter API key is stored as a Lambda environment variable sourced from a gitignored
`.tfvars` value, not AWS Secrets Manager — Secrets Manager carries a per-secret monthly
charge that would violate the project's "zero idle-billed resources" rule.

Because the AWS Budgets $20 hard-stop (QNT-266) only denies AWS API actions, it has no
visibility into OpenRouter spend. A separate spend-limit guard, configured directly in the
OpenRouter dashboard, is now required before any real usage — this is documented as an
explicit acceptance criterion on QNT-268/QNT-269, not left implicit.

## Alternatives considered

- **Keep waiting on AWS Support** — rejected: no confirmed resolution timeline (some
  real-world reports of this exact defect took 15+ days across multiple escalations), and
  QNT-269 would hit the identical account-wide block regardless, so waiting doesn't even
  partially unblock the project.
- **Temporarily use a different AWS region with working Bedrock quota** (some regions
  briefly showed non-zero quota during investigation) — rejected: quota values were
  observed to be inconsistent/flaky across repeated checks in the same region, Cohere
  Rerank 3.5 isn't available in most of the regions that did show quota, and it would mean
  throwaway re-indexing work once/if `us-west-2` is eventually unblocked.
- **Self-hosted open-source embedding model** (bundled into Lambda, or via SageMaker
  Serverless Inference) — rejected for now: bigger implementation lift, and changes what
  the PRD's H3 hypothesis is actually measuring (a specific named model's embedding space)
  more than swapping the hosting layer does.
- **Call Cohere's and OpenAI's/another vendor's APIs directly** instead of through
  OpenRouter — rejected in favor of OpenRouter specifically because the account already has
  OpenRouter access, and its unified API covers all three needs (embeddings, rerank,
  generation) through one client library and one vendor relationship, rather than two or
  three separate SDKs/keys/dashboards.

## Consequences

- **Easier:** one new vendor relationship instead of three Bedrock model-access processes;
  the existing `openai` Python client can be reused for all three model calls; no more
  region-co-location constraint driving infrastructure decisions.
- **Harder / new to live with:** a secret (the OpenRouter API key) now exists in this
  project for the first time — previously the architecture had zero secrets, pure IAM auth.
  The AWS Budgets cost guard no longer covers the dominant cost driver (rerank); the
  OpenRouter dashboard's own spend limit is now load-bearing and must be actively
  maintained, not just AWS Budgets. PRD §8's cost table is no longer fully populated with
  verified numbers for the OpenRouter side — needs updating with real figures once model
  choices are finalized and a real index-build run has happened.
- **Revisit if:** AWS resolves the Bedrock quota issue with clear signal it's now reliable
  account-wide — even then, re-adopting Bedrock is not obviously worth another migration
  given OpenRouter already works; would need a fresh cost/complexity comparison, not an
  automatic revert.
