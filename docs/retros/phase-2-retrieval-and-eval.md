# Retro — Phase 2: Retrieval & Eval

**Milestone:** Phase 2 — Retrieval & Eval
**Tickets:** QNT-269 (retrieval service — Lambda + Function URL, S3 Vectors + OpenRouter rerank +
generation), QNT-270 (recycle retrieval eval against the cloud endpoint)
**Timeline:** 2026-08-26 15:47 (QNT-269 In Progress) → 2026-08-26 16:41 (QNT-270 Done), ~54 minutes
of tracked ticket time, both same day. (An earlier prep commit, PR #5 "docs(plan): note Function
URL vs API Gateway consideration," merged 2026-08-19 — a scoping note ahead of implementation, not
counted as ticket start.)
**PRs:** [#12](https://github.com/noahwins-ng/equity-rag-aws/pull/12) (QNT-269, merged
2026-08-26), [#13](https://github.com/noahwins-ng/equity-rag-aws/pull/13) (QNT-270, merged
2026-08-26) — both merged, single commit each.

## What shipped

- QNT-269: the retrieval Lambda — dense search (S3 Vectors) → OpenRouter Cohere Rerank 3.5 →
  optional gpt-oss-20b generation — exposed via a Lambda Function URL (`AWS_IAM` auth, decided over
  API Gateway per the ticket's own recommended option). Joins S3 Vectors hits back to source text
  via a `point_id → row` cache loaded from the S3 corpus. No reserved-concurrency cap (account-wide
  Lambda concurrency quota is only 10 — see below).
- QNT-270: `eval/cloud_eval.py` — SigV4-signs one call per labeled topic against the deployed
  endpoint, reconstructs dense-only and dense+rerank rankings from a single sweep
  (`top_k=top_n=20`, `generate=false`), scores both per-corpus with the same `ir_measures` metrics
  as the in-repo baseline. Fills PRD §7's comparison table and confirms/refutes H1/H2/H3 — the
  project's core research deliverable. Full results: `eval/results/qnt-270-cloud-eval.md`.

## Velocity

2 of 2 planned tickets shipped, milestone complete, zero rollover. ~54 minutes of combined tracked
ticket time (QNT-269: 26 min, QNT-270: 15 min) — a sharp contrast to Phase 1's 4.3 elapsed days,
almost all of which was the Bedrock quota investigation. This phase moved fast because every Phase
1 lesson had already been folded into Phase 2's own acceptance criteria live (real-call
verification, concurrency-quota awareness, OpenRouter spend re-check), confirmed with no gaps by
the Phase 1 retro's own cross-reference — so there were no unresolved vendor unknowns left to burn
time on this phase.

## Surprises / harder than expected

- **Ticket-text vs. real API drift:** the ticket (and PRD/ADR-0001) say "Cohere Rerank 3.5," but
  OpenRouter's real model slug is `cohere/rerank-v3.5` (`cohere/rerank-3.5` 400s). Caught by AC4's
  real-invocation requirement before implementation — no wasted work, but a reminder that even
  internal spec text can drift from the literal API surface.
- **A quoted PRD baseline turned out stale.** The original "in-repo dense (Qdrant)" comparison row
  was a pre-relabel number blended across both corpora, not a news-only figure — the upstream
  `equity-data-agent` monorepo had relabeled 12/38 news topics after that number was recorded, and
  nobody had recomputed it since. Only surfaced because QNT-270 forced a fresh per-corpus
  recomputation from the current frozen label files; corrected with the user's confirmation before
  overwriting.
- **A results write-up shipped a wrong numeric claim on the first pass.** QNT-270's initial draft
  described the cloud rerank delta as positive across metrics including R@20 — but R@20 is
  structurally invariant to rerank given this eval's `top_k=top_n=20` design (rerank reorders the
  top-20 candidates but never changes membership, so its delta is exactly 0.000 by construction).
  Fresh-eyes review (`flow:flow-code-reviewer`) returned FIX FIRST on this before merge; the prose
  was corrected and re-verified by hand.
- **The core research question resolved in a genuinely mixed way — a research outcome, not a
  defect.** H1 (news) confirmed cleanly. H2 (earnings rerank lift stays marginal on cloud) was
  refuted *on its own premise* — in-repo earnings rerank lift turned out to be the largest of any
  corpus/config, so the small cloud lift is a substrate effect (plausibly Cohere Rerank 3.5 behaving
  differently on pure-dense candidates vs. the in-repo's hybrid-fused candidate set), not evidence
  the corpus is dense-saturated. H3 confirmed for news but partially refuted for earnings (the MRR
  delta sign flips negative on cloud). Two of three hypotheses did not confirm cleanly — worth
  surfacing explicitly rather than letting the "H1 confirmed" framing imply a clean sweep.

## Blockers

None external this phase — the only external blocker in the project (AWS Bedrock's account-wide
quota defect) belongs to Phase 1 and was already resolved (by dropping Bedrock, not by AWS fixing
it) before Phase 2 started.

## Invariant → guard audit

1. **Invariant:** internal spec/ticket text (a vendor's model name) matches the literal API
   identifier needed to call it.
   **Violation:** "Cohere Rerank 3.5" (ticket/PRD/ADR text) vs. the real OpenRouter slug
   `cohere/rerank-v3.5`.
   **Guard:** QNT-269's AC4 (real invocation required before implementation) caught it at zero
   cost. **Disposition: guarded** — same executable-AC pattern from the Phase 1 retro, working as
   intended, no new gap.

2. **Invariant:** a number quoted in the spec as a baseline/comparison value still matches the
   current state of the source it was derived from.
   **Violation:** the PRD's original in-repo dense baseline was a stale, pre-relabel, blended
   number — the upstream monorepo's "frozen" export had itself changed (relabeling) after the
   number was recorded, and nothing re-checked it since.
   **Guard:** NONE — there is no mechanism that re-validates a quoted number against its source
   over time; it was only caught because QNT-270 happened to need a fresh recomputation anyway.
   **Disposition: accepted risk.** The project has no further tickets that pull a new baseline
   number from the upstream monorepo (Phase 3 only reports and finalizes README numbers already
   corrected here), so there's no remaining surface for this specific recurrence in this project.
   Captured to memory generally for reuse elsewhere ([[lesson-verify-before-trusting-quoted-claims]]).

3. **Invariant:** a results write-up's numeric claims are consistent with the measurement design
   (a metric that's fixed by construction shouldn't be described as showing a directional result).
   **Violation:** QNT-270's first draft attributed a positive delta to R@20, which cannot change
   under this eval's `top_k=top_n=20` design.
   **Guard:** the mandatory fresh-eyes review step (already a hard gate in the ship pipeline) caught
   it before merge — this is a working, if manual, guard. **Disposition: guarded**, no stronger
   (automated) guard proposed: this is a one-off analysis write-up in a project that's ending after
   Phase 3, so building a linting/assertion layer for eval-design invariants isn't worth it here.

**Same-shape clustering:** findings 2 and 3 (this phase) and the Phase 1 vendor-entitlement finding
are all the same shape — "a claim that looks settled (an entitlement status, a quoted number, a
computed delta) is not the same claim as independently re-checking it right now." Three instances
across two phases is enough to treat this as the project's recurring meta-lesson rather than three
unrelated one-offs; captured as a single generalized memory
([[lesson-verify-before-trusting-quoted-claims]]) linked back to the original
([[lesson-vendor-entitlement-verification]]). No single new guard replaces all three — the guards
that exist (real-call ACs, review gates) already cover each concretely; the value of clustering is
recognizing the pattern for future projects, not building one more mechanism here.

## Lessons captured to memory

- [[project-equity-rag-aws]] — updated: Phase 2 velocity and cause (Phase 1 lessons already
  retired as ACs before Phase 2 started), plus the project's H1/H2/H3 results now that the core
  research question is answered.
- [[lesson-verify-before-trusting-quoted-claims]] — new memory: a quoted baseline and a write-up's
  own numeric claim both turned out wrong on inspection in the same session; recompute/re-derive
  before trusting any previously-recorded figure or analytical claim, not just vendor status.
- [[lesson-vendor-entitlement-verification]] — updated: cross-linked to the broader recurrence
  above.

## Phase 3 review (QNT-271, QNT-272)

Cross-referencing this retro's findings against Phase 3 found **no gaps requiring scope changes**:

- QNT-271 (CloudWatch logs + metrics) has no dependency on anything that changed this phase —
  Lambda logging/metrics work identically whether fronted by a Function URL or API Gateway, and
  OpenRouter spend is explicitly out of CloudWatch's reach regardless (already the accepted-risk
  disposition from the Phase 1 retro's guard #3).
- QNT-272 (demo + verified teardown + README)'s AC4 (pre-publish sweep: "no tfvars/state, no AWS
  account ids in text or screenshots, no secrets in history") already anticipates exactly the two
  new facts this project picked up across Phases 1–2: the OpenRouter API key (ADR-0001's new
  secret) and the AWS account id `000000000000`, which currently appears in plain text in
  `docs/architecture/system-overview.md`. No AC change needed — flagging it here only so the sweep
  isn't a surprise when QNT-272 starts.
- QNT-272's AC3 (README finalized with H1–H3 verdicts) can pull directly from
  `eval/results/qnt-270-cloud-eval.md` — already written, including the mixed (not clean-sweep)
  H2/H3 outcomes flagged above.

**No `add`/`drop`/`modify` recommendations for Phase 3.**

## Architecture overview

No changes needed — `docs/architecture/system-overview.md` already reflects QNT-269 (retrieval
service, Function URL decision) and QNT-270 (eval client) as shipped; it was kept current live
during each ship rather than left for this retro to catch up.

## Plan sync

Mechanical gap sweep (tracker issues vs. `docs/project-plan.md` identifiers): no gap. All 7 project
issues (QNT-266 through QNT-272) appear in the plan; QNT-266–270 are checked, QNT-271–272 remain
unchecked in Backlog, matching Linear exactly. Nothing to sync.

## Next up

Phase 3 — Observability & Demo Wrap-up, the project's final phase: QNT-271 (CloudWatch logs +
metrics for the retrieval Lambda), then QNT-272 (demo recording, verified teardown, README
finalization with the H1–H3 verdicts, and the public-visibility flip after a pre-publish sweep).
