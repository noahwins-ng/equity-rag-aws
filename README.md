# Equity RAG on AWS

A question-answering system over stock-market documents: news about 10 US companies and
earnings releases from NVIDIA and Apple. Ask *"What was NVIDIA's data center revenue last
quarter?"* and it retrieves NVIDIA's recent earnings releases and answers *"$62.3 billion"* (Q4
FY2026).

The retrieval pipeline was first built and evaluated in
[equity-data-agent](https://github.com/noahwins-ng/equity-data-agent) on self-hosted Qdrant, with
hybrid keyword + vector search and Cohere rerank. This repo rebuilds it on pay-per-request AWS
(S3 Vectors, Lambda, Bedrock, all in Terraform) and scores it with the **identical** eval to
measure what the move cost. The stack exists only for a demo window. Total AWS spend was under $1,
and teardown to zero is verified.

- **Finding:** the cloud version beats the original's vector-only baseline on ranking quality
  (nDCG@10) for both document sets, but neither cloud run reaches the original's hybrid + rerank.
  S3 Vectors has no keyword search, and that's the biggest gap. Among the cloud choices, the
  embedding model mattered most on news and hardly at all on earnings.
- **How it's engineered:** a $20 spend cap enforced by an automatic IAM deny, not just an email; a
  documented switch to another vendor when Bedrock was broken for this account, and back once it was
  fixed; and a design that works inside non-adjustable Bedrock quotas as low as 3 requests/minute.

[Demo video](https://youtu.be/fdJ5s8kmU-w) · [Full eval write-up](eval/results/qnt-483-bedrock-eval.md) ·
[Spec](docs/PRD.md) · [Decision records](docs/decisions/)

## Headline result

nDCG@10 (ranking quality of the top 10, higher is better) on the same 51 labeled questions:

| Corpus | Original: vector only | Original: hybrid + rerank | Cloud: vector + rerank |
|---|---|---|---|
| News (1,963 articles, 38 questions) | 0.521 | **0.786** | 0.547 |
| Earnings (1,934 release chunks, 13 questions) | 0.531 | **0.834** | 0.673 |

- **Keyword search is the biggest missing piece.** The cloud stack trails the original by 0.24 on
  news and 0.16 on earnings. S3 Vectors has no keyword (BM25) search, and reranking alone doesn't
  make up for it.
- **Among the cloud choices, the embedding model matters most on news.** The same pipeline with
  OpenAI's `text-embedding-3-small` instead of Titan V2 scored 0.679 instead of 0.547, closing about
  half the gap.
- **On earnings, the embedding model barely matters** (0.639 vs. 0.673), and cloud rerank adds
  only +0.04. Earnings retrieval behaves like a `(company, quarter)` lookup more than a ranking
  problem.

The two document sets behave differently under every change tested: news needs good ranking,
while earnings is mostly a lookup. Testing whether that difference survives a completely
different stack was the point of this experiment, and it did.
[All four metrics, both cloud runs, hypotheses and caveats ↓](#full-results)

## Architecture

```
                        ┌────────────────────────── Terraform (us-west-2) ─────────────────────────┐
                        │                                                                          │
 source project         │   S3 bucket          index job (Lambda, sliced)        S3 Vectors        │
 frozen snapshot ─────────► corpus/*.jsonl ──► Bedrock Titan Embeddings V2 ───► index per corpus   │
 + labels + manifest    │   labels/            → PutVectors (keyed by chunk id, (news, earnings)   │
                        │   manifest.json      ticker/date metadata)                  │            │
                        │                                                             ▼            │
 eval client (local) ─────► Function URL ──► retrieval Lambda: dense top-k (S3 Vectors)            │
 ir_measures + labels   │   (AWS_IAM auth)  → Bedrock Cohere Rerank 3.5 → [optional gpt-oss-20b]   │
                        │                                      │                                   │
                        │   CloudWatch  ◄── logs + latency/invocation/error metrics                │
                        │   AWS Budgets ◄── USD 20 alert + IAM deny hard-stop (covers Bedrock)     │
                        └──────────────────────────────────────────────────────────────────────────┘
```

Everything inside the box is defined in Terraform and destroyed together. Component breakdown:
[`docs/architecture/system-overview.md`](docs/architecture/system-overview.md).

**What changed from the original stack**, which runs on a Hetzner VPS:

| Original | AWS | Why |
|---|---|---|
| Qdrant (always-on) | S3 Vectors | No idle cost; pay per use. Vector-only: no keyword (BM25) search |
| Original embedding model | Bedrock Titan Text Embeddings V2 (512-dim) | Deliberately a different embedding space |
| Cohere Rerank 3.5 (Cohere API) | Cohere Rerank 3.5 via Bedrock | Same model, so rerank isn't a variable |
| gpt-oss-20b on Groq | gpt-oss-20b via Bedrock | Same model family, pay per request |
| VPS app process | Lambda + Function URL (IAM auth) | Scales to zero; private without API Gateway |
| VPS disk | S3 (frozen corpus snapshot) | Read-only input; no live ingestion |

## Engineering decisions worth reading

- **A cost cap that enforces itself.** AWS Budgets alerts at $10 and, at $20, automatically attaches
  an IAM deny policy to the operator's IAM user. It blocks Bedrock, S3 Vectors and Lambda calls but
  never delete actions, so `terraform destroy` still works after it fires.
  ([`terraform/main.tf`](terraform/main.tf))
- **A vendor outage, handled with a written decision both ways.** Bedrock's console showed every
  model as authorized, but every real call failed: a provisioning defect left this account's quota
  at 0. Model serving moved to OpenRouter ([ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md)),
  then moved back once AWS fixed it ([ADR-0002](docs/decisions/0002-bedrock-model-serving-restored.md)).
  The switch-back removed the project's only secret and put model spend back under the $20 cap.
- **Designed to fit hard quotas.** Bedrock allows 60 embedding and 3 rerank requests per minute on
  this account, and neither can be raised. The index job runs in 750-row slices that each fit one
  15-minute Lambda run, and re-running a slice is safe because writes are keyed upserts. The eval
  client paces itself at one query per 21 seconds.
- **An eval built to be trusted.** The labels, metrics and scoring code are frozen and copied from
  the original project. Results are reported per corpus and never blended, the two cloud runs are
  kept side by side as an embedding comparison, and the caveats are stated rather than hidden.
- **Teardown verified, not assumed.** Everything is Terraform with no console-created resources.
  After `terraform destroy`, the state list is empty and no project resources remain (checked by
  service). Next-day Cost Explorer showed about $0 after the earlier teardown.
- **Lessons kept.** Each phase has a retro with an invariant-to-guard audit ([`docs/retros/`](docs/retros/)).
  One example: a "verify with a real call, not the console status" rule written after the Bedrock outage.

## Full results

<details>
<summary>All four metrics, both cloud runs, hypothesis verdicts and caveats</summary>

51 labeled topics (38 news, 13 earnings), TREC qrels, `ir_measures`. The labels, metrics and
scoring code are the same as the original project's CI gate. Corpus: 1,963 news articles across
10 US tickers and 1,934 earnings-release chunks (EDGAR 8-K, NVDA and AAPL). The current cloud
rows use Bedrock Titan V2 embeddings. The *earlier run* rows used `text-embedding-3-small` via
OpenRouter while Bedrock was unavailable. The two runs are identical apart from the embedding
model, so they double as an embedding ablation.

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | original dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | original hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | cloud dense (S3 Vectors, Titan V2) | 0.258 | 0.488 | 0.622 | 0.483 |
| news | cloud dense+rerank (Titan V2 + Bedrock Rerank 3.5) | 0.304 | 0.488 | 0.700 | 0.547 |
| news | *earlier run: cloud dense (text-embedding-3-small)* | 0.310 | 0.654 | 0.641 | 0.544 |
| news | *earlier run: cloud dense+rerank (OpenRouter)* | 0.411 | 0.654 | 0.806 | 0.679 |
| earnings | original dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | original hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | cloud dense (S3 Vectors, Titan V2) | 0.364 | 0.551 | 0.769 | 0.630 |
| earnings | cloud dense+rerank (Titan V2 + Bedrock Rerank 3.5) | 0.375 | 0.551 | 0.769 | 0.673 |
| earnings | *earlier run: cloud dense (text-embedding-3-small)* | 0.321 | 0.534 | 0.789 | 0.629 |
| earnings | *earlier run: cloud dense+rerank (OpenRouter)* | 0.364 | 0.534 | 0.761 | 0.639 |

**Hypotheses, stated before running ([PRD §7](docs/PRD.md#7-eval-plan)), and verdicts on the
Titan V2 run:**

- **H1 (news): cloud vector + rerank lands between the original vector-only and hybrid + rerank. —
  Partially confirmed (3 of 4 metrics).** It holds on R@5, MRR and nDCG@10. It misses on R@20
  (0.488 vs. 0.612), which only measures the vector candidate pool: Titan V2's news recall is
  weaker. With `text-embedding-3-small` it held on all four.
- **H2 (earnings): rerank lift stays marginal on both stacks, because earnings is a
  "dense-saturated" corpus. — Refuted.** The original stack's earnings lift is the largest of any
  corpus or config (MRR reaches 1.000). The cloud lift is small under *both* embedding models, so
  the cause is more likely reranking pure-vector candidates than the corpus itself.
- **H3 (embeddings): vector-only results differ from the original, but rerank moves metrics in the
  same direction. — Confirmed for news; consistent for earnings.** Rerank is positive on news
  R@5/MRR/nDCG@10. On earnings it's positive on R@5/nDCG@10 and flat on MRR. R@20 is excluded,
  because with `top_k = top_n = 20` rerank can't change which documents make the top 20.

**Caveats.**

- **The earnings sample is small.** With 13 topics, one query slipping from rank 1 to rank 2 shifts
  MRR by about 0.04, which is larger than most of the cloud earnings deltas. No confidence intervals
  or paired tests were computed, so treat earnings deltas as directional. The earlier run's
  earnings MRR drop (−0.028) didn't reproduce on Titan V2, which is a direct example.
- **Two variables change at once.** The original hybrid + rerank and the cloud vector + rerank
  differ in both the embedding model *and* the candidate pool (no BM25). The two cloud runs isolate
  the embedding model; a clean "original stack minus BM25" run was not produced.

Full reasoning: [`eval/results/qnt-483-bedrock-eval.md`](eval/results/qnt-483-bedrock-eval.md)
(Titan V2) and [`eval/results/qnt-270-cloud-eval.md`](eval/results/qnt-270-cloud-eval.md)
(earlier run).

</details>

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
  ([equity-data-agent](https://github.com/noahwins-ng/equity-data-agent)), pointing the output directory at this repo's `data/`. Expected
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

# The retrieval eval -- prints the cloud rows of the results table. Paced at one query
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
Recorded during the OpenRouter period (ADR-0001). The flow is the same on Bedrock; only the
model-serving calls differ.

## Project docs

- [`docs/PRD.md`](docs/PRD.md) — spec: goals, seam contract, eval plan, budget.
- [`docs/decisions/0001-bedrock-to-openrouter.md`](docs/decisions/0001-bedrock-to-openrouter.md) —
  why model serving left Bedrock mid-project, the alternatives weighed, and what the pivot cost.
- [`docs/decisions/0002-bedrock-model-serving-restored.md`](docs/decisions/0002-bedrock-model-serving-restored.md) —
  the move back once the quota defect was fixed, and designing around its low quotas.
- [`docs/retros/`](docs/retros/) — one retrospective per phase, each with an invariant → guard audit.
- [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) — the system as built.
