# Equity RAG on AWS

A question-answering system over stock-market documents: news about 10 US companies and earnings
releases from NVIDIA and Apple. Ask *"What was NVIDIA's data center revenue last quarter?"* and it
finds the right earnings releases and answers *"$62.3 billion"* (Q4 FY2026).

The pipeline was first built and evaluated in
[equity-data-agent](https://github.com/noahwins-ng/equity-data-agent). This repo rebuilds it on
pay-per-request AWS (S3 Vectors, Lambda, Bedrock, all Terraform) and re-runs the **identical** eval
to measure what the move cost. Total spend: under $1. The stack is torn down after each demo.

[Demo video](https://youtu.be/fdJ5s8kmU-w) · [Eval write-up](eval/results/qnt-483-bedrock-eval.md) ·
[Spec](docs/PRD.md) · [Decision records](docs/decisions/)

## Result

Ranking quality (nDCG@10, higher is better) on the same 51 labeled questions:

| Documents | Original: vector only | Original: hybrid + rerank | AWS: vector + rerank |
|---|---|---|---|
| News (1,963 articles) | 0.521 | **0.786** | 0.547 |
| Earnings (1,934 chunks) | 0.531 | **0.834** | 0.673 |

- **Missing keyword search is the biggest cost.** S3 Vectors is vector-only, and reranking doesn't
  make up for it: AWS trails the original by 0.24 on news and 0.16 on earnings.
- **The embedding model matters most on news.** Switching to OpenAI's `text-embedding-3-small`
  lifts news to 0.679, closing about half the gap.
- **On earnings, the embedding model barely matters** (0.639 vs. 0.673), and AWS rerank adds only
  +0.04, versus +0.30 for the original's hybrid + rerank. The earnings gap most likely comes from
  losing keyword search, not from the embeddings.

## How it works

```
snapshot ──► S3 ──► index job (Lambda) ──► Titan V2 embeddings ──► S3 Vectors
                                              (one index per document set)

eval client ──► Function URL (IAM auth) ──► retrieval Lambda:
                  1. vector search, top 20 (S3 Vectors)
                  2. rerank (Cohere Rerank 3.5, Bedrock)
                  3. answer (gpt-oss-20b, Bedrock, optional)

Guardrails: $20 budget → automatic IAM deny · CloudWatch logs/metrics
```

| Original (Hetzner VPS) | AWS |
|---|---|
| Qdrant, always on | S3 Vectors: no idle cost, but no keyword search |
| Original embedding model | Bedrock Titan V2: a deliberately different embedding space |
| Cohere Rerank 3.5 | Same model via Bedrock, so rerank isn't a variable |
| gpt-oss-20b on Groq | Same model via Bedrock |
| App process on the VPS | Lambda + Function URL: scales to zero, private via IAM |

More detail: [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md).

## Engineering highlights

- **Self-enforcing $20 cap.** At $20, AWS Budgets attaches an IAM deny that blocks new Bedrock, S3
  Vectors and Lambda calls but not teardown ([`terraform/main.tf`](terraform/main.tf)).
- **Vendor outage, handled both ways.** Bedrock showed "authorized" while every call failed, so
  serving moved to OpenRouter, then back once AWS fixed it
  ([ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md), [ADR-0002](docs/decisions/0002-bedrock-model-serving-restored.md)).
- **Built for hard quotas.** With limits of 60 embedding and 3 rerank requests per minute, indexing
  runs in safe-to-retry slices and the eval paces itself.
- **Trustworthy eval.** Frozen labels and scoring code from the original project, results per
  document set, and caveats stated up front.
- **Verified teardown.** Everything is Terraform. After `terraform destroy`, the state is empty and
  no resources remain.

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

## Run it yourself

Needs AWS credentials with Bedrock access in `us-west-2`, Terraform, `uv`, and the corpus snapshot in
`data/` (produced by equity-data-agent's export script).

```sh
cp terraform/example.tfvars terraform/terraform.tfvars     # set alert email + IAM user
terraform -chdir=terraform init && terraform -chdir=terraform apply   # incl. $20 guard
# index both document sets (~65 min, sliced for Bedrock quotas; loop below)
uv run python eval/cloud_eval.py                           # ~18 min, prints results
terraform -chdir=terraform destroy                         # state list -> empty
```

<details>
<summary>Full step-by-step instructions</summary>

**Prerequisites**

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

**Stand up → index → query → eval → tear down**

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

# The retrieval eval -- prints the AWS rows of the full results table. Paced at one query
# per 21 s for Rerank 3.5's 3 req/min quota, so ~18 min.
uv run python eval/cloud_eval.py

cd terraform
terraform destroy
terraform state list   # must be empty
```

No console-created resources — everything is defined in `terraform/` and `terraform destroy`
returns the account to zero. Teardown is verified, not assumed: empty `terraform state list` plus
an empty next-day Cost Explorer.

</details>

## Cost

Under $1 in total: about $0.10 of AWS infrastructure and about $0.10 of Bedrock model calls. The
$20 budget guard covers all of it.

<details>
<summary>Cost breakdown</summary>

| Line item | Observed / estimated |
|---|---|
| S3 Vectors (storage + writes + queries) | ~$0.08 est. |
| Lambda + Function URL | ~$0 (perpetual free tier at this scale) |
| S3, CloudWatch, AWS Budgets | ~$0 |
| **AWS total** | **~$0.10** est.; next-day Cost Explorer after teardown showed ~$0 |
| Bedrock — Titan V2 embeddings (3,897 calls, one index build) | cents est. ($0.02/1M tokens) |
| Bedrock — Rerank 3.5 + gpt-oss-20b (eval sweep, spot checks) | ~$0.10 est. ($2.00/1K rerank queries) |
| *Historical:* OpenRouter (ADR-0001 period) — one index build + eval sweeps | ~$6.10 observed on the key's cumulative `/credits` usage — an upper bound |

Pricing basis: [`docs/PRD.md` §8](docs/PRD.md#8-budget-and-teardown).

</details>

## Docs

- [`docs/PRD.md`](docs/PRD.md) — spec: goals, seam contract, eval plan, budget.
- [`docs/decisions/0001-bedrock-to-openrouter.md`](docs/decisions/0001-bedrock-to-openrouter.md) —
  why model serving left Bedrock mid-project, the alternatives weighed, and what the pivot cost.
- [`docs/decisions/0002-bedrock-model-serving-restored.md`](docs/decisions/0002-bedrock-model-serving-restored.md) —
  the move back once the quota defect was fixed, and designing around its low quotas.
- [`docs/retros/`](docs/retros/) — one retrospective per phase, each with an invariant → guard audit.
- [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) — the system as built.
- Demo video: [youtu.be/fdJ5s8kmU-w](https://youtu.be/fdJ5s8kmU-w). Recorded during the OpenRouter
  period; the flow is the same on Bedrock.
