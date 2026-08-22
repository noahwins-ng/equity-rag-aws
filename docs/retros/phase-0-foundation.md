# Retro — Phase 0: Foundation

**Milestone:** Phase 0 — Foundation
**Tickets:** QNT-266 (sole ticket)
**Timeline:** 2026-08-18 15:41 (In Progress) → 2026-08-22 05:30 (Done)
**PRs:** [#3](https://github.com/noahwins-ng/equity-rag-aws/pull/3) scaffold + budget alert,
[#4](https://github.com/noahwins-ng/equity-rag-aws/pull/4) pricing/region verification,
[#6](https://github.com/noahwins-ng/equity-rag-aws/pull/6) budget hard-stop,
[#7](https://github.com/noahwins-ng/equity-rag-aws/pull/7) plan doc note — all merged.

## What shipped

- Terraform skeleton: AWS provider pinned to `us-west-2`, local state backend (deliberate —
  solo/single-cycle project, avoids a remote-state bootstrap bucket that itself needs tearing down).
- AWS Budgets guard: USD 10 warning / USD 20 notification (`aws_budgets_budget.project_cap`).
- Budget hard-stop (scope addition, AC4): a Budgets Action auto-attaches an IAM deny policy to the
  operator's IAM user at USD 20 spend — scoped to only this project's billed actions (Bedrock
  invoke, S3 Vectors put/query, Lambda invoke, API Gateway invoke), never delete/terminate/
  `budgets:*`, so `terraform destroy` still works after it fires.
- README scaffold: Hetzner→AWS mapping table + dense-vs-hybrid tradeoff note.
- `docs/PRD.md` §8/§12 pricing and region-availability claims verified against current AWS docs
  (they were unverified placeholders at ship time — real numbers now: ~$2–5 estimated spend,
  `us-west-2` confirmed as 1 of only 3 regions where Titan V2 + Cohere Rerank 3.5 + gpt-oss-20b +
  S3 Vectors all co-locate).
- Real infra now live in AWS account `000000000000` (us-west-2) — the first non-planning resources
  this project has created. No compute/data resources yet.

## Velocity

1 ticket, 1 milestone, complete. Elapsed wall-clock time (~4 days) is not representative of active
work time — most of the gap was the user's own calendar time for AWS account/credential setup
between sessions, not stalled work.

## Surprises

- AC1 (terraform-apply) was blocked for most of the ship on missing AWS credentials — the user
  started with root-account access only and needed a full IAM-user bootstrap walkthrough.
- Scope grew organically and correctly: the ticket originally asked for budget *notifications*
  only; mid-ship cost-review conversation surfaced that alerts alone don't stop spend, so a real
  technical stop-gap was added as AC4 rather than shipped as a silent gap.
- Two tracker-reliability surprises, same shape (see invariant audit below): Linear's GitHub
  integration auto-transitioned issue status from PR merges independent of actual AC state, and
  this workspace hit its free-tier issue-creation limit mid-ship.

## Blockers

- External: AWS credential/IAM bootstrap (user-side, resolved).
- External: Linear free-tier issue-creation cap (resolved by folding new scope into QNT-266's own
  AC list instead of a new ticket).

## Invariant → guard audit

1. **Invariant:** dev-execution AC must have real command+output evidence before shipping.
   **Violation:** AC1 was initially BLOCKED (no AWS credentials in the ship sandbox) and shipped
   anyway on the user's explicit, logged override.
   **Guard:** `flow-ship-issue`'s AC-classification discipline (`references/ac-classification.md`)
   — already enforces this as a hard gate; the override was a deliberate, visible exception (asked
   via `AskUserQuestion`, documented in the tracker comment), not a silent gap. **Disposition:
   working as intended.**

2. **Invariant:** tracker status accurately reflects real completion state.
   **Violation:** Linear's GitHub integration auto-flipped QNT-266 to Done twice before all AC
   were actually proven, and flipped QNT-269 to In Progress from a docs-only PR that only added a
   planning note. Caught both times by the user asking to check, not by any automated signal.
   **Guard:** NONE — this is Linear platform behavior, not something this repo's CI can intercept
   (no CI configured yet; even with CI, this is an external SaaS auto-transition, not a check that
   runs in this repo). **Disposition: accepted risk.** Mitigation is procedural — spot-check
   tracker status after every PR merge that references a ticket ID, not just the closing one.
   Captured to memory ([[feedback-linear-pr-autoclose]]) so future sessions do this by default.

3. **Invariant:** the tracker has capacity to create a new ticket when new in-scope work is
   discovered mid-ship.
   **Violation:** `save_issue` (create) failed with "exceeded the free issue limit for this
   workspace" when attempting to file a ticket for the budget hard-stop work.
   **Guard:** NONE — external SaaS plan limit; this project's own taxonomy has no ops/reliability
   milestone to file a guard-ticket into anyway (`ops_milestone: ""`, ephemeral-by-design).
   **Disposition: accepted risk.** Mitigation used this time: fold new scope into the open ticket
   whose domain covers it, as an additional AC (QNT-266's AC4). Captured to memory.

4. **Invariant:** the spec (`docs/PRD.md`) is verified against current reality before a ticket
   that owns that verification is called done, not carried forward as an unverified placeholder.
   **Violation:** §8's budget estimate and §12's reference list both explicitly said "verify real
   pricing / current docs during QNT-266" — this was missed on the first ship pass (shipped
   without checking) and only closed out because the user asked follow-up questions about cost and
   region alternatives.
   **Guard:** NONE automated. **Disposition: accepted risk, with a concrete process lesson**
   (captured to memory): before closing a ticket, grep the spec doc for that ticket's ID — a
   "verify/TBD/TODO at `<this ticket>`" hit is an implicit AC even when it isn't in the ticket's
   own checklist.

**Same-shape clustering:** findings 2 and 3 are the same shape — assuming a tracker platform's
automated/available behavior instead of verifying it. Both got the same treatment (accepted risk +
memory capture) rather than inventing infrastructure this solo, no-CI, ephemeral project doesn't
warrant.

## Lessons captured to memory

- [[feedback-linear-pr-autoclose]] — any PR referencing a ticket ID can auto-flip its Linear
  status; verify after every merge, not just the closing one.
- [[project-equity-rag-aws]] — Linear issue-creation cap and fold-in fallback; PRD
  self-verification TODOs need grepping for by ticket ID; the still-open Bedrock model-access gap
  (see Phase 1 review below); user's AWS starting state (root-only → IAM user bootstrapped).
- [[feedback-real-stopgaps]] — user prefers real technical enforcement over alert-only controls
  for cost/safety-relevant work; lean toward recommending and defaulting to auto-apply enforcement
  when both options exist.

## Phase 1 review (QNT-267, QNT-268)

Cross-referencing this retro's findings against the next milestone surfaced one concrete,
pre-existing gap and one discovered dependency:

- **Gap:** `docs/PRD.md` §11's risk table says "Bedrock model access requires per-model
  enablement (Titan / Cohere / gpt-oss) — request access during QNT-266, before any dependent
  work." This was never actually executed during QNT-266's ship. It's a live blocker risk for
  QNT-268 (needs Titan Embeddings V2 access) and QNT-269 (needs Cohere Rerank 3.5 + gpt-oss-20b
  access) — Bedrock per-model access approval isn't necessarily instant, so leaving this for
  QNT-268 itself risks silently blocking that ticket's AC1.
- **Discovered dependency:** QNT-267 needs the actual frozen snapshot bundle from the
  `equity-data-agent` monorepo export (QNT-265, shipped there) staged locally under this repo's
  gitignored `data/` — that directory doesn't exist yet in this checkout. This isn't something
  fixable in this repo; it's an external precondition to confirm before QNT-267 can start.

**Recommendation (pending approval, not yet actioned):**
`modify QNT-267/QNT-268: request AWS Bedrock model access for Titan Embeddings V2, Cohere Rerank
3.5, and gpt-oss-20b now (or as an explicit pre-check AC on QNT-268) — Reason: PRD §11's own
mitigation was never executed; resolving it now removes a blocking risk from Phase 1/2 before
those tickets start.`

## Next up

QNT-267 — frozen corpus snapshot into S3 (Phase 1 — Corpus & Index), pending confirmation that the
QNT-265 snapshot bundle is available to stage locally, and pending a decision on the Bedrock
model-access recommendation above.
