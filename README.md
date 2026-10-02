# Equity RAG on AWS

An evaluated RAG retrieval pipeline (dense search → rerank → generation), re-platformed from a
self-hosted Qdrant stack onto pay-per-request AWS primitives (S3 Vectors + Lambda, all Terraform),
and scored with the **identical** offline eval to measure exactly what the substrate change cost.
Stood up for a demo window, then destroyed. AWS spend under $1, teardown verified.

**Result.** On news, rerank lifts dense-only S3 Vectors on every rank-sensitive metric, but how
much of the BM25 hybrid gap it closes depends on the embedding model. text-embedding-3-small
closed most of it. Bedrock Titan V2 closes less, and its weaker news recall leaves R@20 below
the original dense baseline. On earnings, the cloud rerank gain stays small under both embedding
models, a substrate effect the original hypothesis didn't predict. The embedding swap itself
splits by corpus: it moves every news metric and leaves earnings effectively unchanged.
[Results table and verdicts ↓](#retrieval-eval-results)

**Skills on display:** Terraform IaC with a technical cost cap · serverless RAG on Lambda + S3 Vectors ·
IR evaluation with `ir_measures` (recall, MRR, nDCG) · a documented vendor pivot under a real blocker,
and back again once it cleared ([ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md),
[ADR-0002](docs/decisions/0002-bedrock-model-serving-restored.md)) · per-phase retros ([`docs/retros/`](docs/retros/)).

[Spec](docs/PRD.md) · [Demo video](https://youtu.be/fdJ5s8kmU-w) · [Full eval write-up](eval/results/qnt-483-bedrock-eval.md) ([earlier OpenRouter run](eval/results/qnt-270-cloud-eval.md))

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
                        │   AWS Budgets ◄── USD 20 alert + IAM deny hard-stop (covers Bedrock)     │
                        └──────────────────────────────────────────────────────────────────────────┘
```

Everything inside the box is Terraform-defined and destroyed together. Component and data-store
breakdown: [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md).

### Hetzner → AWS mapping

The in-repo stack runs on a Hetzner VPS. This project swaps each component for an AWS-native,
zero-idle-cost equivalent — same retrieval flow, different substrate:

| In-repo (Hetzner) | AWS | Why |
|---|---|---|
| Qdrant (self-hosted, always-on) | S3 Vectors | Zero idle floor, pay-per-use, trivially destroyed — no always-on vector search process |
| In-repo embedding model (see the monorepo) | Bedrock Titan Text Embeddings V2, 512-dim | A deliberately *different* embedding space (re-embedding is the point of the experiment). Served via OpenRouter (`text-embedding-3-small`) while this account's Bedrock quota was broken ([ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md)), back on Bedrock once it was fixed ([ADR-0002](docs/decisions/0002-bedrock-model-serving-restored.md)) |
| Cohere Rerank 3.5 (Cohere API direct) | Cohere Rerank 3.5 via Bedrock | Same model, different serving path — isolates the substrate variable |
| Groq (generation serving) | gpt-oss-20b via Bedrock | Same open-weight model family, pay-per-request instead of a dedicated inference host |
| Hetzner VPS (app process) | Lambda + Function URL (`AWS_IAM` auth) | Zero idle cost, IaC-trivial, scales to zero between eval runs, private by IAM auth (no API Gateway needed) |
| VPS filesystem / local Qdrant storage | S3 (frozen corpus snapshot) | Durable, versioned, read-only input — no live ingestion |

## Retrieval eval results

51 labeled topics (38 news, 13 earnings), TREC qrels, `ir_measures` — the same labels, metrics,
and scoring code as the parent repo's CI gate. Corpus: 1,963 news articles across 10 US tickers;
1,934 earnings-release chunks (EDGAR 8-K, NVDA and AAPL). The in-repo stack runs hybrid BM25 +
dense ahead of rerank; S3 Vectors is dense-only, so the cloud path has no lexical leg — the eval
quantifies what that costs, per corpus. The current cloud rows use Bedrock Titan V2 embeddings.
The *earlier run* rows used `text-embedding-3-small` via OpenRouter while Bedrock was unavailable
(ADR-0001). The two runs are identical apart from the embedding model, so they double as an
embedding ablation.

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | in-repo dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | in-repo hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | cloud dense (S3 Vectors, Titan V2) | 0.258 | 0.488 | 0.622 | 0.483 |
| news | cloud dense+rerank (Titan V2 + Bedrock Rerank 3.5) | 0.304 | 0.488 | 0.700 | 0.547 |
| news | *earlier run: cloud dense (text-embedding-3-small)* | 0.310 | 0.654 | 0.641 | 0.544 |
| news | *earlier run: cloud dense+rerank (OpenRouter)* | 0.411 | 0.654 | 0.806 | 0.679 |
| earnings | in-repo dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | in-repo hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | cloud dense (S3 Vectors, Titan V2) | 0.364 | 0.551 | 0.769 | 0.630 |
| earnings | cloud dense+rerank (Titan V2 + Bedrock Rerank 3.5) | 0.375 | 0.551 | 0.769 | 0.673 |
| earnings | *earlier run: cloud dense (text-embedding-3-small)* | 0.321 | 0.534 | 0.789 | 0.629 |
| earnings | *earlier run: cloud dense+rerank (OpenRouter)* | 0.364 | 0.534 | 0.761 | 0.639 |

**Verdicts (Titan V2 run; full reasoning in the [write-up](eval/results/qnt-483-bedrock-eval.md)):**

- **H1 (news) — PARTIALLY CONFIRMED (3 of 4 metrics).** Cloud dense+rerank lands between in-repo
  dense-only and in-repo hybrid+rerank on R@5, MRR and nDCG@10. It misses on R@20 (0.488 vs.
  in-repo dense's 0.612), which only measures the dense candidate pool: Titan V2's news recall is
  weaker. With text-embedding-3-small, H1 held on all four metrics.
- **H2 (earnings) — REFUTED.** The premise ("rerank lift stays marginal on earnings, in-repo or
  cloud") fails: in-repo earnings rerank lift is the largest of either corpus/config (MRR reaches
  1.000). Cloud's earnings rerank lift is small under *both* embedding models (Titan V2: R@5
  +0.011, MRR 0.000, nDCG@10 +0.043). So the embedding space is unlikely to be the cause; the
  likelier one is reranking pure-dense candidates rather than the in-repo's BM25-fused set.
- **H3 (embeddings) — CONFIRMED for news; earnings consistent in direction.** Dense-only numbers
  differ from in-repo on both corpora, as expected for a different embedding space. The rerank
  delta is positive on news R@5/MRR/nDCG@10, matching in-repo. On earnings it's positive on
  R@5/nDCG@10 and flat on MRR. The earlier run's earnings MRR reversal (−0.028) didn't reproduce,
  consistent with single-query noise. R@20 is excluded, because with `top_k = top_n = 20` rerank
  can't change top-20 membership.
- **Embedding ablation (new).** Titan V2 vs. text-embedding-3-small, dense-only: news drops on
  every metric (R@20 −0.166), earnings is effectively tied. This is the regime finding on a
  new axis: news is sensitive to every stack choice, while earnings behaves like a filter problem.

**Caveats, stated plainly.**

- **The earnings sample is small.** 13 topics means a single query slipping from rank 1 to rank 2
  shifts MRR by about 0.04, which is larger than most of the cloud earnings deltas. No
  confidence intervals or paired tests were computed; treat the earnings deltas as directional,
  not settled. The earlier run's MRR reversal not reproducing is a direct example.
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
  `ir-measures`, `pyyaml`).
- Bedrock on-demand access in `us-west-2` for Titan Text Embeddings V2, Cohere Rerank 3.5 and
  gpt-oss-20b. Check with a real minimal call, not the console's "access granted" status. This
  account showed AUTHORIZED while every call failed ([ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md)).
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
cp example.tfvars terraform.tfvars   # fill in email + IAM user (gitignored)
terraform init
terraform apply

# The index job isn't run by apply -- invoke it before querying, or the S3 Vectors indices are
# empty. Titan V2's 60 req/min quota caps one 15-min run at ~800 rows, so each corpus goes in
# 750-row slices (~65 min total; re-running a slice is safe -- writes are keyed upserts).
for corpus in news earnings; do
  for start in 0 750 1500; do
    aws lambda invoke --cli-read-timeout 920 --function-name equity-rag-aws-index-job \
      --payload "{\"corpus\":\"$corpus\",\"start\":$start,\"limit\":750}" \
      --cli-binary-format raw-in-base64-out "out-$corpus-$start.json"
  done
done
cd ..

# Sample query (SigV4-signed POST to the IAM-authenticated Function URL)
uv run python scripts/invoke_retrieval.py news "Did Apple strike a chip deal with Intel?"

# The retrieval eval -- prints the cloud rows of the results table above. Paced at one query
# per 21 s for Rerank 3.5's 3 req/min quota, so ~18 min.
uv run python eval/cloud_eval.py

cd terraform
terraform destroy
terraform state list   # must be empty
```

No console-created resources — everything is defined in `terraform/` and `terraform destroy`
returns the account to zero. Teardown is verified, not assumed: empty `terraform state list` plus
an empty next-day Cost Explorer.

## Cost model

All spend, Bedrock included, is backstopped by a Budgets alert (USD 10 / 20) and a Budgets Action
that attaches an IAM deny policy at USD 20 (Bedrock invoke, S3 Vectors, Lambda invoke), scoped so
`terraform destroy` still works.

| Line item | Observed / estimated |
|---|---|
| S3 Vectors (storage + writes + queries) | ~$0.08 est. |
| Lambda + Function URL | ~$0 (perpetual free tier at this scale) |
| S3, CloudWatch, AWS Budgets | ~$0 |
| **AWS total** | **~$0.10** est.; next-day Cost Explorer after teardown showed ~$0 |
| Bedrock — Titan V2 embeddings (3,897 calls, one index build) | cents est. ($0.02/1M tokens) |
| Bedrock — Rerank 3.5 + gpt-oss-20b (eval sweep, spot checks) | ~$0.10 est. ($2.00/1K rerank queries) |
| *Historical:* OpenRouter (ADR-0001 period) — one index build + eval sweeps | ~$6.10 observed on the key's cumulative `/credits` usage — an upper bound |

Pricing basis and the per-line breakdown: [`docs/PRD.md` §8](docs/PRD.md#8-budget-and-teardown).

## Demo video

[![Demo: stand-up → index → query → eval → teardown](https://i.ytimg.com/vi/fdJ5s8kmU-w/hqdefault.jpg)](https://youtu.be/fdJ5s8kmU-w)

`terraform apply` → index both corpora → sample queries → the eval run → `terraform destroy`.

## Project docs

- [`docs/PRD.md`](docs/PRD.md) — spec: goals, seam contract, eval plan, budget.
- [`docs/decisions/0001-bedrock-to-openrouter.md`](docs/decisions/0001-bedrock-to-openrouter.md) —
  why model serving left Bedrock mid-project, the alternatives weighed, and what the pivot cost.
- [`docs/decisions/0002-bedrock-model-serving-restored.md`](docs/decisions/0002-bedrock-model-serving-restored.md) —
  the move back once the quota defect was fixed, and designing around its low quotas.
- [`docs/retros/`](docs/retros/) — one retrospective per phase, each with an invariant → guard audit.
- [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) — the system as built.
