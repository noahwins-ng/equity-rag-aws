# Equity RAG on AWS

Re-platforms the [equity-data-agent](https://github.com/noahwins-ng/equity-data-agent) monorepo's
evaluated RAG retrieval pipeline (dense search → rerank → optional generation) onto AWS-native,
pay-per-request primitives, scores it with the identical offline retrieval eval, and publishes a
per-corpus before/after comparison. Ephemeral: `terraform apply` for a demo window, then
`terraform destroy`. Full spec: [`docs/PRD.md`](docs/PRD.md).

## Hetzner → AWS mapping

The in-repo stack runs on a Hetzner VPS. This project swaps each component for an AWS-native,
zero-idle-cost equivalent — same retrieval flow, different substrate:

| In-repo (Hetzner) | AWS | Why |
|---|---|---|
| Qdrant (self-hosted, always-on) | S3 Vectors | Zero idle floor, pay-per-use, trivially destroyed — no always-on vector search process |
| In-repo embedding model | `openai/text-embedding-3-small` via OpenRouter | A deliberately *different* embedding space (re-embedding is the point of the experiment). Originally planned via AWS Bedrock; moved to OpenRouter after an unresolved AWS account-level Bedrock quota defect — see [ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md) |
| Cohere Rerank API | Cohere Rerank 3.5 via OpenRouter | Same model, different serving path — isolates the substrate variable |
| Groq (generation serving) | gpt-oss-20b via OpenRouter | Same open-weight model family, pay-per-request instead of a dedicated inference host |
| Hetzner VPS (app process) | Lambda + Function URL (`AWS_IAM` auth) | Zero idle cost, IaC-trivial, scales to zero between eval runs, private by IAM auth (no API Gateway needed) |
| VPS filesystem / local Qdrant storage | S3 (frozen corpus snapshot) | Durable, versioned, read-only input — no live ingestion |

## Dense-vs-hybrid tradeoff

The in-repo stack runs **hybrid retrieval** (BM25 + dense, fused with RRF) ahead of rerank. S3
Vectors is **dense-only** — there is no BM25/lexical leg on the cloud path. This is a documented
tradeoff, not an oversight: the retrieval eval (QNT-270) quantifies exactly what the missing BM25
leg costs, per corpus. The expectation, stated as a hypothesis before running it:

- **news** (large, lexically diverse, ranking-hard) is where hybrid+rerank shows the biggest lift
  in-repo — cloud dense+rerank should land *between* in-repo dense-only and in-repo hybrid+rerank.
- **earnings** (small, templated, dense-saturated — really a `(ticker, period)` filter problem)
  should barely move either way, in-repo or cloud — confirming the regime difference is a property
  of the corpus, not the stack.

Full hypotheses (H1–H3) and the comparison table: [`docs/PRD.md` §7](docs/PRD.md#7-eval-plan).

## Retrieval eval results

Cloud numbers from `eval/cloud_eval.py` against the deployed retrieval Lambda; in-repo numbers
recomputed per-corpus from `equity-data-agent`'s frozen run files. Full methodology and
reproduction steps: [`eval/results/qnt-270-cloud-eval.md`](eval/results/qnt-270-cloud-eval.md).

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | in-repo dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | in-repo hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | cloud dense (S3 Vectors) | 0.310 | 0.654 | 0.641 | 0.544 |
| news | cloud dense+rerank (S3 Vectors + OpenRouter) | 0.411 | 0.654 | 0.806 | 0.679 |
| earnings | in-repo dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | in-repo hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | cloud dense (S3 Vectors) | 0.321 | 0.534 | 0.789 | 0.629 |
| earnings | cloud dense+rerank (S3 Vectors + OpenRouter) | 0.364 | 0.534 | 0.761 | 0.639 |

**Verdicts:**

- **H1 (news) — CONFIRMED.** Cloud dense+rerank lands strictly between in-repo dense-only and
  in-repo hybrid+rerank on all four metrics — rerank recovers most, not all, of the missing BM25
  leg's lift.
- **H2 (earnings) — REFUTED.** The premise ("rerank lift stays marginal on earnings, in-repo or
  cloud") fails: in-repo earnings rerank lift is the largest of either corpus/config (MRR reaches
  a perfect 1.000). Cloud's rerank lift on earnings is small and mixed (MRR actually **drops**
  -0.028) — a substrate effect (Cohere Rerank 3.5 reranking pure-dense candidates vs. the in-repo's
  hybrid-informed candidate set), not a dense-saturated corpus property.
- **H3 (embeddings) — CONFIRMED for news, PARTIALLY REFUTED for earnings.** Dense-only numbers
  differ from in-repo on both corpora (different embedding space), as expected. Rerank-delta
  direction matches in-repo on news; on earnings it disagrees on MRR (in-repo positive, cloud
  negative) — the one metric where the two stacks diverge in direction, not just magnitude.

## Stand up / tear down

```sh
cd terraform
terraform init
terraform apply   # uses terraform.tfvars (gitignored) or pass -var-file=example.tfvars as a template

# The index job is a one-shot Lambda, not run automatically by apply -- invoke it once per
# corpus before querying, or the S3 Vectors indices are empty and queries return no results.
aws lambda invoke --cli-read-timeout 920 --function-name equity-rag-aws-index-job \
  --payload '{"corpus":"news"}' --cli-binary-format raw-in-base64-out out-news.json
aws lambda invoke --cli-read-timeout 920 --function-name equity-rag-aws-index-job \
  --payload '{"corpus":"earnings"}' --cli-binary-format raw-in-base64-out out-earnings.json

# ... demo window: query, eval ...
cd ..
uv run python scripts/invoke_retrieval.py news "Did Apple strike a chip deal with Intel?"

cd terraform
terraform destroy
```

No console-created resources — everything above is defined in `terraform/` and `terraform destroy`
returns the account to zero. Budget: USD 20 hard cap, AWS Budgets alert at USD 10 (warning) and
USD 20 (hard cap), backstopping the destroy step. See [`docs/PRD.md` §8](docs/PRD.md#8-budget-and-teardown).

## Cost model

AWS spend is dominated by fixed per-request pricing at near-zero scale; OpenRouter (model serving)
is the real cost driver and is **not** covered by the AWS Budgets guard — it needs its own
dashboard-configured spend limit. Full breakdown: [`docs/PRD.md` §8](docs/PRD.md#8-budget-and-teardown).

| Line item | Est. cost |
|---|---|
| S3 Vectors (storage + writes + queries) | ~$0.08 |
| Lambda + Function URL | ~$0 (within the perpetual free tier at this scale) |
| S3, CloudWatch, AWS Budgets | ~$0 |
| **AWS total** | **~$0.10**, well inside the USD 20 hard cap |
| OpenRouter (embeddings + rerank + generation) | separate spend, guarded by an OpenRouter-side dashboard limit, not the AWS cap |

## Demo video

[Stand-up → index → query → eval → teardown recording](https://github.com/noahwins-ng/equity-rag-aws/releases/download/demo-v1/equity-rag-aws-demo.mov)
(`terraform apply`, index job invocations for both corpora, sample queries against news and
earnings, the eval results above, then `terraform destroy`).
