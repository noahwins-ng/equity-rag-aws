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

## Stand up / tear down

```sh
cd terraform
terraform init
terraform apply -var-file=example.tfvars   # or your own .tfvars with a real alert email
# ... demo window: query, eval ...
uv run python scripts/invoke_retrieval.py news "Did Apple strike a chip deal with Intel?"
terraform destroy -var-file=example.tfvars
```

No console-created resources — everything above is defined in `terraform/` and `terraform destroy`
returns the account to zero. Budget: USD 20 hard cap, AWS Budgets alert at USD 10 (warning) and
USD 20 (hard cap), backstopping the destroy step. See [`docs/PRD.md` §8](docs/PRD.md#8-budget-and-teardown).
