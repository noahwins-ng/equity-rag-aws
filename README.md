# Equity RAG on AWS

A question-answering system over stock-market documents: news about 10 US companies and earnings
releases from NVIDIA and Apple. Ask *"What was NVIDIA's data center revenue last quarter?"* and it
finds the right earnings releases and answers *"$62.3 billion"* (Q4 FY2026).

The pipeline was first built and evaluated in
[equity-data-agent](https://github.com/noahwins-ng/equity-data-agent). This repo rebuilds it on
pay-per-request AWS (S3 Vectors, Lambda, Bedrock, all Terraform) to test whether a scale-to-zero
serverless stack can match a tuned self-hosted one, scored with the **identical** eval. AWS +
Bedrock spend: under $1 (plus ~$6 on OpenRouter while Bedrock was broken). The stack is torn down
after each demo.

**Stack:** Terraform · AWS Lambda · S3 Vectors · Bedrock (Titan V2, Cohere Rerank 3.5,
gpt-oss-20b) · Python · IR evaluation (`ir_measures`: nDCG, MRR, recall)

[Demo video](https://youtu.be/fdJ5s8kmU-w) · [Eval write-up](eval/results/qnt-312-hybrid-eval.md) ·
[Spec](docs/PRD.md) · [Decision records](docs/decisions/)

## Result

Ranking quality (nDCG@10, 0–1, higher is better) on the same 51 labeled questions:

| | News | Earnings |
|---|---|---|
| Original: hybrid + rerank | 0.786 | 0.834 |
| AWS first build: vector search + rerank | 0.547 | 0.673 |
| + search only the question's company | 0.679 | 0.751 |
| **+ BM25 keyword search (final)** | **0.787** | **0.765** |

**Bottom line:** the serverless rebuild matches the original on news and gets within 0.07
on earnings, at almost no idle cost.

- **Company scoping was the biggest fix.** The original filters every search to the
  question's ticker; the first AWS build searched all companies, so other companies'
  documents crowded out the right ones.
- **Keyword search runs inside the Lambda.** S3 Vectors is vector-only, so BM25 is built
  in memory: no new infrastructure, still zero idle cost.

Caveats: the labels are keyword-based, which favors BM25. The remaining earnings gap may
come from release titles missing from the snapshot, plus noise from only 13 questions.

## How it works

```
snapshot ──► S3 ──► index job (Lambda) ──► Titan V2 embeddings ──► S3 Vectors
                                              (one index per document set)

eval client ──► Function URL (IAM auth) ──► retrieval Lambda:
                  1. vector search, top 20 (S3 Vectors, filtered to the company)
                  2. + BM25 keyword search in memory, merged with RRF
                  3. rerank (Cohere Rerank 3.5, Bedrock)
                  4. answer (gpt-oss-20b, Bedrock, optional)

Guardrails: $20 budget → automatic IAM deny · CloudWatch logs/metrics
```

| Original (Hetzner VPS) | AWS |
|---|---|
| Qdrant, always on | S3 Vectors: no idle cost, vector-only |
| BM25 in the app | BM25 in the Lambda, built from rows already in memory |
| Original embedding model | Bedrock Titan V2: a deliberately different embedding space |
| Cohere Rerank 3.5 | Same model via Bedrock, so rerank isn't a variable |
| gpt-oss-20b on Groq | Same model via Bedrock |
| App process on the VPS | Lambda + Function URL: scales to zero, private via IAM |

More detail: [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md).

## Engineering highlights

- **Self-enforcing $20 cap.** At $20, AWS Budgets attaches an IAM deny that blocks new Bedrock, S3
  Vectors and Lambda calls but not teardown ([`terraform/main.tf`](terraform/main.tf)).
- **Vendor defect, handled both ways.** Bedrock reported access granted while every call failed
  (a zero-quota defect on the account), so serving moved to OpenRouter, then back once AWS fixed it
  ([ADR-0001](docs/decisions/0001-bedrock-to-openrouter.md), [ADR-0002](docs/decisions/0002-bedrock-model-serving-restored.md)).
- **Built for hard quotas.** With limits of 60 embedding and 3 rerank requests per minute, indexing
  runs in safe-to-retry slices and the eval paces itself.
- **Trustworthy eval.** Frozen labels and scoring code from the original project, results per
  document set, and caveats stated up front.
- **Verified teardown.** Everything is Terraform. After `terraform destroy`, the state is empty and
  no resources remain.

## Full results

<details>
<summary>All four metrics, every cloud run, hypothesis verdicts and caveats</summary>

51 labeled topics (38 news, 13 earnings), TREC qrels, `ir_measures`. The labels, metrics and
scoring code are the same as the original project's CI gate. Corpus: 1,963 news articles across
10 US tickers and 1,934 earnings-release chunks (EDGAR 8-K, NVDA and AAPL). The
*ticker-scoped* rows are the final build. The *unscoped* rows are the first build, searching
all companies, on Titan V2. The *earlier run* rows are the first build with
`text-embedding-3-small` via OpenRouter, used while Bedrock was unavailable.

| Corpus | Config | R@5 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| news | original dense (Qdrant) | 0.295 | 0.612 | 0.620 | 0.521 |
| news | original hybrid+rerank (Qdrant) | 0.527 | 0.799 | 0.857 | 0.786 |
| news | **cloud dense (ticker-scoped)** | 0.317 | 0.623 | 0.660 | 0.540 |
| news | **cloud dense+rerank (ticker-scoped)** | 0.426 | 0.623 | 0.798 | 0.679 |
| news | **cloud hybrid+rerank (ticker-scoped)** | 0.524 | 0.807 | 0.866 | 0.787 |
| news | cloud dense (unscoped) | 0.258 | 0.488 | 0.622 | 0.483 |
| news | cloud dense+rerank (unscoped) | 0.304 | 0.488 | 0.700 | 0.547 |
| news | *earlier run: cloud dense (text-embedding-3-small)* | 0.310 | 0.654 | 0.641 | 0.544 |
| news | *earlier run: cloud dense+rerank (OpenRouter)* | 0.411 | 0.654 | 0.806 | 0.679 |
| earnings | original dense (Qdrant) | 0.335 | 0.529 | 0.671 | 0.531 |
| earnings | original hybrid+rerank (Qdrant) | 0.529 | 0.674 | 1.000 | 0.834 |
| earnings | **cloud dense (ticker-scoped)** | 0.395 | 0.638 | 0.850 | 0.675 |
| earnings | **cloud dense+rerank (ticker-scoped)** | 0.406 | 0.638 | 0.892 | 0.751 |
| earnings | **cloud hybrid+rerank (ticker-scoped)** | 0.423 | 0.712 | 0.933 | 0.765 |
| earnings | cloud dense (unscoped) | 0.364 | 0.551 | 0.769 | 0.630 |
| earnings | cloud dense+rerank (unscoped) | 0.375 | 0.551 | 0.769 | 0.673 |
| earnings | *earlier run: cloud dense (text-embedding-3-small)* | 0.321 | 0.534 | 0.789 | 0.629 |
| earnings | *earlier run: cloud dense+rerank (OpenRouter)* | 0.364 | 0.534 | 0.761 | 0.639 |

**Hypotheses, stated before running ([PRD §7](docs/PRD.md#7-eval-plan)), judged on the
first (unscoped) build:**

- **H1 (news): cloud vector + rerank lands between the original's vector-only and hybrid +
  rerank. — Partially confirmed** (3 of 4 metrics; R@20 missed). The final build goes further
  and matches the original.
- **H2 (earnings): rerank barely helps, because earnings is "dense-saturated". — Refuted.**
  The original's earnings lift is the largest of any config (MRR 1.000), and scoping raises
  the cloud rerank lift too.
- **H3 (embeddings): vector-only scores differ, but rerank moves metrics the same way. —
  Confirmed for news, consistent for earnings.**

**Caveats.**

- **The labels favor keyword search.** A document is relevant if it contains one of the
  topic's anchor terms, so the BM25 gain is an upper bound for paraphrased questions.
- **The earnings sample is small.** With 13 topics, one query slipping from rank 1 to rank 2
  shifts MRR by about 0.04. No confidence intervals or paired tests were computed.
- **Scoping assumes the company is known.** Every topic names its ticker, as in the
  original's served path. A free-text question would need company detection first.
- **The unscoped embedding comparison is confounded.** The earlier run's
  `text-embedding-3-small` beat Titan V2 on news, but both were unscoped. Scoped, Titan V2
  vector-only (0.540) is on par with the original's (0.521).

Full reasoning: [`eval/results/qnt-312-hybrid-eval.md`](eval/results/qnt-312-hybrid-eval.md)
(final build), [`eval/results/qnt-483-bedrock-eval.md`](eval/results/qnt-483-bedrock-eval.md)
(unscoped, Titan V2) and [`eval/results/qnt-270-cloud-eval.md`](eval/results/qnt-270-cloud-eval.md)
(earlier run).

</details>

## Run it yourself

Needs AWS credentials with Bedrock access in `us-west-2`, Terraform, `uv`, and the corpus snapshot in
`data/` (produced by equity-data-agent's export script).

```sh
cp terraform/example.tfvars terraform/terraform.tfvars     # set alert email + IAM user
terraform -chdir=terraform init && terraform -chdir=terraform apply   # incl. $20 guard
# index both document sets (~65 min, sliced for Bedrock quotas; loop below)
uv run python eval/cloud_eval.py                           # ~36 min, prints results
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

# Sample query (SigV4-signed POST to the IAM-authenticated Function URL). Optional ticker
# scope and mode (dense | hybrid):
uv run python scripts/invoke_retrieval.py news "Did Apple strike a chip deal with Intel?" AAPL hybrid

# The retrieval eval -- prints the ticker-scoped AWS rows of the full results table. Two calls
# per topic (dense, hybrid), paced at one per 21 s for Rerank 3.5's 3 req/min quota: ~36 min.
uv run python eval/cloud_eval.py

cd terraform
terraform destroy
terraform state list   # must be empty
```

No console-created resources — everything is defined in `terraform/` and `terraform destroy`
returns the account to zero. Teardown is verified, not assumed: empty `terraform state list` plus
an empty next-day Cost Explorer.

</details>

## Repo layout

```
terraform/   all AWS infrastructure: S3, S3 Vectors, Lambda, IAM, Budgets, CloudWatch
lambda/      index_job/ (embed + write vectors), retrieval_service/ (search, rerank, answer)
eval/        scoring code, frozen labels, results write-ups
scripts/     sample query, S3 checksum check
docs/        spec, architecture, decision records, retros
```

## Cost

About $0.20 on AWS: about $0.10 of infrastructure and about $0.10 of Bedrock model calls, all
under the $20 budget guard. Separately, about $6 went to OpenRouter while Bedrock was broken.

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
