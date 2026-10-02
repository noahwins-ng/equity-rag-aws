# ADR-0002: Move model serving back from OpenRouter to AWS Bedrock

- **Status:** accepted
- **Date:** 2026-10-02
- **Ticket:** QNT-483 (supersedes ADR-0001)

## Context

ADR-0001 moved all three models to OpenRouter because this account's Bedrock on-demand
throughput quota was stuck at 0 (a provisioning defect AWS Support had not resolved). By
2026-09-28 that had been fixed: a minimal real call in `us-west-2` succeeded for Titan Text
Embeddings V2 (512-dim), Cohere Rerank 3.5 (`cohere.rerank-v3-5:0`) and gpt-oss-20b
(`openai.gpt-oss-20b-1:0`, via `converse`). The calls were re-checked on 2026-10-02.

ADR-0001 asked for a fresh comparison rather than an automatic revert ("Revisit if"). The
comparison favors Bedrock:

- **Back to pure IAM, no secrets.** The OpenRouter API key was the project's only secret.
- **One spend guard again.** The AWS Budgets USD 20 hard stop covers Bedrock spend. It never
  covered OpenRouter, so a separate dashboard limit had to be maintained by hand.
- **It's the original PRD §6 design.** Titan V2 is the embedding model H3 was written about.

The fixed account has low on-demand quotas, none of them adjustable (`Adjustable: False`):

| Model | Requests/min |
|---|---|
| Titan Text Embeddings V2 | 60 |
| Cohere Rerank 3.5 | 3 |
| gpt-oss-20b | 100 |

## Decision

Serve all three models from Bedrock in `us-west-2`. Each Lambda role gets
`bedrock:InvokeModel`, scoped to the foundation-model ARNs it uses. `Converse` is authorized
by the same action. Remove the OpenRouter key, the `openai` dependency, and the `openrouter_api_key`
Terraform variable. Put `bedrock:InvokeModel*` back on the budget hard stop's deny list.

Design around the quotas instead of waiting on increases:

- **Index job:** the event takes optional `start`/`limit`, so each 15-min invocation embeds at
  most about 800 rows. The job runs one worker, with boto3 `adaptive` retries.
- **Retrieval service:** `adaptive` retries, and a 60s Lambda timeout so the function can
  wait out rerank throttling.
- **Eval client:** sends one query every 21s, which stays under the 3/min rerank limit.

The S3 Vectors indices keep 512-dim cosine, so their Terraform doesn't change. Titan V2 is a
different embedding space from text-embedding-3-small, so both corpora are re-indexed and
the eval is re-run into a new results file. The OpenRouter-era results stay as their own
data point.

## Alternatives considered

- **Stay on OpenRouter** — rejected. It works, but it keeps a secret and a spend surface
  outside the AWS guard, and both exist only because of a defect that is now fixed.
- **Bedrock batch inference for the index build** — rejected. It needs a service role, S3
  input/output plumbing and an asynchronous job with no completion-time guarantee. Slicing
  the invocations meets the quota with a few lines of code.
- **Run the index build locally instead of in Lambda** — rejected. It would move the PRD's
  "index job (Lambda, one-shot)" out of Terraform-managed infrastructure just to avoid
  several invocations.

## Consequences

- **Easier:** zero secrets, one cost guard, and the whole stack inside one AWS account and one
  Terraform lifecycle again.
- **Harder:** the quotas set the pace. An index build takes about 65 min across several
  invocations, and the 3/min rerank limit means the retrieval endpoint can't serve more than
  3 queries a minute with reranking. That's fine for a single-operator demo, but it would be
  a blocker for any real traffic.
- **Comparability:** results from QNT-270 (OpenRouter embeddings) and QNT-483 (Titan V2)
  measure different embedding spaces. They're reported side by side, never merged.
