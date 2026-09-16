# Equity RAG on AWS

Takes an *evaluated* RAG retrieval pipeline (dense search → rerank → optional generation) from the
[equity-data-agent](https://github.com/noahwins-ng/equity-data-agent) monorepo, re-platforms it onto
pay-per-request AWS primitives (S3 Vectors + Lambda) with OpenRouter as the model-serving layer,
scores it with the **identical** offline retrieval eval, and reports what the substrate change
cost, per corpus. Ephemeral by design: `terraform apply` for a demo window, then `terraform destroy`.

**The finding, in two sentences.** On the news corpus, Cohere Rerank 3.5 on top of dense-only
S3 Vectors recovers most (not all) of the lift the in-repo stack gets from its BM25 hybrid leg —
the cloud pipeline lands strictly between in-repo dense-only and in-repo hybrid+rerank on every
metric. On the earnings corpus the picture flips: in-repo rerank lift is the largest of any
configuration, but the cloud stack's rerank lift is small and MRR actually drops — a substrate
effect, not the "dense-saturated corpus" property the original hypothesis assumed.
[Full results and hypothesis verdicts ↓](#retrieval-eval-results)

Spec: [`docs/PRD.md`](docs/PRD.md) · Decisions: [`docs/decisions/`](docs/decisions/) ·
Retros: [`docs/retros/`](docs/retros/) · Demo: [YouTube](https://youtu.be/fdJ5s8kmU-w)

## Architecture

```
                        ┌────────────────────────── Terraform (us-west-2) ─────────────────────────┐
                        │                                                                          │
 monorepo (QNT-265)     │   S3 bucket          index job (Lambda, one-shot)      S3 Vectors        │
 frozen snapshot ─────────► corpus/*.jsonl ──► OpenRouter embedding model ────► index per corpus   │
 + labels + manifest    │   labels/            → PutVectors (point_id-keyed,    (news, earnings)   │
                        │   manifest.json      corpus/ticker/date metadata)           │            │
                        │                                                             ▼            │
 eval client (local) ─────► Function URL ──► retrieval Lambda: dense top-k (S3 Vectors)            │
 ir_measures + labels   │   (AWS_IAM auth)  → OpenRouter Cohere Rerank 3.5 → [optional gpt-oss-20b]│
                        │                                      │                                   │
                        │   CloudWatch  ◄── logs + latency/invocation/error metrics                │
                        │   AWS Budgets ◄── USD 20 alert + IAM deny hard-stop (AWS spend only)     │
                        └──────────────────────────────────────────────────────────────────────────┘
   (OpenRouter is external HTTPS, not Terraform-managed AWS infra — reached via Lambda's default
    internet egress; no VPC/NAT needed.)
```

Everything inside the box is Terraform-defined and destroyed together. Component and data-store
breakdown: [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md).

### Hetzner → AWS mapping

The in-repo stack runs on a Hetzner VPS. This project swaps each component for an AWS-native,
zero-idle-cost equivalent — same retrieval flow, different substrate:

| In-repo (Hetzner) | AWS | Why |
|---|---|---|
| Qdrant (self-hosted, always-on) | S3 Vectors | Zero idle floor, pay-per-use, trivially destroyed — no always-on vector search process |
| In-repo embedding model (see the monorepo) | `openai/text-embedding-3-small` via OpenRouter, truncated to 512-dim | A deliberately *different* embedding space (re-embedding is the point of the experiment). Originally planned via AWS Bedrock Titan V2; moved to OpenRouter after an unresolved AWS account-level Bedrock quota defect — see [ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md) |
| Cohere Rerank 3.5 (Cohere API direct) | Cohere Rerank 3.5 via OpenRouter | Same model, different serving path — isolates the substrate variable |
| Groq (generation serving) | gpt-oss-20b via OpenRouter | Same open-weight model family, pay-per-request instead of a dedicated inference host |
| Hetzner VPS (app process) | Lambda + Function URL (`AWS_IAM` auth) | Zero idle cost, IaC-trivial, scales to zero between eval runs, private by IAM auth (no API Gateway needed) |
| VPS filesystem / local Qdrant storage | S3 (frozen corpus snapshot) | Durable, versioned, read-only input — no live ingestion |

### Dense-vs-hybrid tradeoff

The in-repo stack runs **hybrid retrieval** (BM25 + dense, fused with RRF) ahead of rerank. S3
Vectors is **dense-only** — there is no lexical leg on the cloud path. This is a documented
tradeoff, not an oversight; the eval below quantifies exactly what the missing BM25 leg costs,
per corpus. Hypotheses H1–H3 were stated before the eval ran: [`docs/PRD.md` §7](docs/PRD.md#7-eval-plan).

## Retrieval eval results

**What was measured.** 51 labeled topics (38 news, 13 earnings) with TREC qrels keyed on the
Qdrant `point_id`, scored with `ir_measures` — the same labels, metrics, and scoring code as the
parent repo's CI gate. Corpus: 1,963 news article rows across 10 US tickers and 1,934 earnings
chunk rows (EDGAR 8-K Item 2.02 / Ex 99.1, NVDA and AAPL only). Cloud numbers come from
`eval/cloud_eval.py` against the deployed retrieval Lambda (`top_k = top_n = 20`, generation
off); in-repo numbers are recomputed per-corpus from the monorepo's frozen run files.
Methodology and reproduction: [`eval/results/qnt-270-cloud-eval.md`](eval/results/qnt-270-cloud-eval.md).

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
  in-repo hybrid+rerank on all four metrics. Rerank recovers most, not all, of the missing BM25
  leg's lift.
- **H2 (earnings) — REFUTED.** The premise ("rerank lift stays marginal on earnings, in-repo or
  cloud") fails: in-repo earnings rerank lift is the largest of either corpus/config (MRR reaches
  1.000). Cloud's rerank lift on earnings is small and mixed (MRR drops by 0.028) — plausibly
  Cohere Rerank 3.5 reranking pure-dense candidates behaves differently from the same model
  reranking the in-repo's hybrid-informed candidate set.
- **H3 (embeddings) — CONFIRMED for news, PARTIALLY REFUTED for earnings.** Dense-only numbers
  differ from in-repo on both corpora (different embedding space), as expected. The rerank delta's
  direction matches in-repo on news; on earnings it disagrees on MRR. R@20 is excluded from the
  directional comparison — with `top_k = top_n = 20`, rerank reorders the top-20 but can't change
  its membership, so its R@20 delta is 0.000 by construction.

**Caveats, stated plainly.**

- **The earnings sample is small.** 13 topics means a single query slipping from rank 1 to rank 2
  shifts MRR by about 0.04 — larger than the cloud MRR drop the H2 verdict rests on. No
  confidence intervals or paired tests were computed; treat the earnings deltas as directional,
  not settled.
- **Two variables change at once.** In-repo hybrid+rerank vs. cloud dense+rerank differs in both
  the embedding model *and* the candidate pool (BM25 removed). H3 partially separates them, but
  the clean ablation — an in-repo dense+rerank run with no BM25 leg — was not produced.

## Reproduce

### Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) and the
  [AWS CLI](https://aws.amazon.com/cli/), with credentials for a single IAM user configured via
  the standard credential chain. The same user must be named in `iam_user_name` below — it is
  the principal the budget hard-stop's IAM deny policy attaches to, and the one whose credentials
  sign the invoke/eval requests.
- [`uv`](https://docs.astral.sh/uv/) for the Python tooling (`uv sync` installs `boto3`,
  `ir-measures`, `openai`, `pyyaml`).
- An [OpenRouter](https://openrouter.ai/) API key. **Set a spend limit in the OpenRouter
  dashboard first** — the AWS Budgets guard has no visibility into this spend (see
  [Cost model](#cost-model)).
- **The corpus snapshot bundle, staged under `data/`.** It is not in this repo (news rows carry
  vendor-sourced article bodies) and `terraform apply` fails without it — `terraform/s3.tf` reads
  `data/manifest.json` at plan time. Produce it with the monorepo's export script
  (equity-data-agent, QNT-265), pointing the output directory at this repo's `data/`. Expected
  layout: `data/{manifest.json, corpus/{news,earnings}.jsonl, labels/{retrieval.yaml,retrieval_qrels.trec}}`.
  Verify the upload afterwards with `scripts/verify_s3_checksums.sh`.

### Stand up → index → query → eval → tear down

```sh
uv sync

cd terraform
cp example.tfvars terraform.tfvars   # fill in email, IAM user, OpenRouter key (gitignored)
terraform init
terraform apply

# The index job is a one-shot Lambda, not run by apply -- invoke it once per corpus before
# querying, or the S3 Vectors indices are empty and queries return no results.
aws lambda invoke --cli-read-timeout 920 --function-name equity-rag-aws-index-job \
  --payload '{"corpus":"news"}' --cli-binary-format raw-in-base64-out out-news.json
aws lambda invoke --cli-read-timeout 920 --function-name equity-rag-aws-index-job \
  --payload '{"corpus":"earnings"}' --cli-binary-format raw-in-base64-out out-earnings.json
cd ..

# Sample query (SigV4-signed POST to the IAM-authenticated Function URL)
uv run python scripts/invoke_retrieval.py news "Did Apple strike a chip deal with Intel?"

# The retrieval eval -- prints the cloud rows of the results table above
uv run python eval/cloud_eval.py

cd terraform
terraform destroy
terraform state list   # must be empty
```

No console-created resources — everything is defined in `terraform/` and `terraform destroy`
returns the account to zero. Teardown is verified, not assumed: empty `terraform state list` plus
an empty next-day Cost Explorer.

## Cost model

Two vendors, two guards. AWS spend is near zero at this scale and is backstopped twice: an AWS
Budgets alert at USD 10 / USD 20, and a Budgets Action that auto-attaches an IAM deny policy to
the operator's user at USD 20 (scoped to this project's billable actions only, so `terraform
destroy` still works after it fires). OpenRouter is the real cost driver and is **not** covered by
either — it needs its own dashboard-configured spend limit.

| Line item | Observed / estimated |
|---|---|
| S3 Vectors (storage + writes + queries) | ~$0.08 est. |
| Lambda + Function URL | ~$0 (perpetual free tier at this scale) |
| S3, CloudWatch, AWS Budgets | ~$0 |
| **AWS total** | **~$0.10** est.; next-day Cost Explorer after teardown showed ~$0 |
| OpenRouter — embedding both corpora (3,897 calls, one index build) | ~$6.10 observed on the key's cumulative `/credits` usage — an upper bound, not a clean per-model attribution |
| OpenRouter — rerank + generation (eval sweeps, spot checks) | not separately measured |

Pricing basis and the per-line breakdown: [`docs/PRD.md` §8](docs/PRD.md#8-budget-and-teardown).

## Demo video

[![Demo: stand-up → index → query → eval → teardown](https://i.ytimg.com/vi/fdJ5s8kmU-w/hqdefault.jpg)](https://youtu.be/fdJ5s8kmU-w)

End to end: `terraform apply` → index job for both corpora → sample queries against
news and earnings → the eval run that produces the table above → `terraform destroy` and the
empty state list.

## Project docs

- [`docs/PRD.md`](docs/PRD.md) — spec: goals, snapshot seam contract, eval plan, budget, delivery plan.
- [`docs/decisions/0001-bedrock-to-openrouter.md`](docs/decisions/0001-bedrock-to-openrouter.md) —
  why model serving left Bedrock mid-project: an account-level quota defect AWS Support did not
  resolve, the alternatives weighed, and what the pivot cost.
- [`docs/retros/`](docs/retros/) — one retrospective per phase, each with an invariant → guard
  audit of what went wrong and whether anything now prevents it.
- [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) — the system as built.
