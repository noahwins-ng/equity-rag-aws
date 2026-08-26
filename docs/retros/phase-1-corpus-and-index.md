# Retro — Phase 1: Corpus & Index

**Milestone:** Phase 1 — Corpus & Index
**Tickets:** QNT-267 (frozen corpus snapshot into S3), QNT-268 (index job — OpenRouter embeddings
into S3 Vectors)
**Timeline:** 2026-08-22 07:18 (QNT-267 In Progress) → 2026-08-26 15:29 (QNT-268 Done), ~4.3
elapsed days
**PRs:** [#9](https://github.com/noahwins-ng/equity-rag-aws/pull/9) (QNT-267, merged 2026-08-22),
[#10](https://github.com/noahwins-ng/equity-rag-aws/pull/10) (QNT-268, merged 2026-08-26) — both
merged, single commit each.

## What shipped

- QNT-267: the frozen QNT-265 monorepo snapshot (`corpus/{news,earnings}.jsonl`,
  `labels/retrieval.yaml`, `labels/retrieval_qrels.trec`, `manifest.json`) seeded into S3 via
  Terraform, checksums verified against the manifest; the `ir_measures` scoring core + labels
  copied into this repo (`eval/`).
- QNT-268: S3 Vectors bucket with two indices (news, earnings), 512-dim cosine, populated
  end-to-end from the S3 corpus via an embedding model, vectors keyed verbatim by `point_id`.
  **Scope change:** the embedding model host moved from AWS Bedrock (Titan Embeddings V2, as
  originally planned) to OpenRouter (`openai/text-embedding-3-small`) — see ADR-0001.

## Velocity

2 of 2 planned tickets shipped, milestone complete. QNT-267 took 13 minutes of ticket time
(near-trivial as scoped). Nearly all of the phase's ~4.3-day elapsed time sits inside QNT-268,
and nearly all of *that* was one external investigation (below), not implementation — the actual
index-job code (Lambda handler, Terraform, docs) is a single commit once the substrate was
decided.

## Surprises

- **Major:** every AWS Bedrock `InvokeModel` call failed (`ThrottlingException` /
  `AccessDeniedException`) despite entitlement APIs reporting `AVAILABLE`/`AUTHORIZED` for every
  model. Investigation (spanning several days, two unresolved AWS Support cases) traced this to
  an account-wide on-demand throughput quota stuck at 0 — a known, undocumented AWS
  account-provisioning defect with no self-service fix. QNT-268 pivoted the entire model-serving
  layer to OpenRouter mid-ticket (ADR-0001); QNT-269 was updated the same day to match.
- This was a *predicted* risk — the Phase 0 retro flagged "Bedrock model access" as a live
  blocker for QNT-268/269 and recommended requesting access ahead of time — but the
  recommendation was left "pending approval" and never actually executed before QNT-268 started.
  In practice the actual failure mode (quota=0, not access/entitlement denial) likely wouldn't
  have been caught by an early access *request* alone anyway — entitlement was already granted;
  only a real invocation call surfaces the quota defect. Earlier action would have surfaced the
  same problem a few days sooner (during QNT-266's window), not prevented it outright.
  See [[project-equity-rag-aws]].
- The project now has its first secret (OpenRouter API key, Lambda env var sourced from a
  gitignored `.tfvars`) — the architecture was pure-IAM/zero-secrets through Phase 0.
  `docs/architecture/system-overview.md` updated with a dedicated "Secrets" note.
- The AWS Budgets $20 hard-stop (QNT-266) has no visibility into OpenRouter spend — a new,
  uncovered cost surface. Mitigated the same ship: OpenRouter dashboard spend limit
  (auto-topup disabled, finite balance) as QNT-268 AC5, with a volume re-check folded into
  QNT-269 AC5 for its higher call volume.
- No tracker-status auto-close drift this phase (unlike Phase 0) — both issues' Done timestamps
  match actual completion; the spot-check habit from [[feedback-linear-pr-autoclose]] held.

## Blockers

- External: AWS Bedrock account-level quota-provisioning defect — unresolved via two AWS Support
  cases (Basic support tier has no Technical case type / Support API access), no confirmed
  resolution timeline. Resolved for this project by dropping Bedrock entirely (ADR-0001), not by
  the defect itself getting fixed.

## Invariant → guard audit

1. **Invariant:** a vendor's reported entitlement/access status implies its API calls will
   actually work.
   **Violation:** Bedrock's `GetFoundationModelAvailability` showed `AVAILABLE`/`AUTHORIZED` for
   every model while every real `InvokeModel` call failed — the account-wide quota defect was
   invisible to status/entitlement checks.
   **Guard:** the lesson was converted into an executable AC live, not left as prose — QNT-268's
   AC4 ("OpenRouter API key verified working via a real embedding call... not just 'key exists'")
   and QNT-269's AC4 (same pattern, both OpenRouter models) both require a real minimal
   invocation before building further or running at scale. **Disposition: guarded, ad hoc.** Not
   generalized into `docs/AC-templates.md` as a standing template row — QNT-269 is the last
   ticket in this project that adds a new vendor integration, so a reusable template row has no
   further use here. Captured to memory instead ([[lesson-vendor-entitlement-verification]]) for
   reuse in other projects.

2. **Invariant:** a retro's cross-milestone recommendation gets actioned or explicitly rejected
   before the next milestone starts.
   **Violation:** the Phase 0 retro's recommendation ("request Bedrock model access now, or as an
   explicit pre-check AC on QNT-268") was left "pending approval, not yet actioned" and nobody
   circled back — QNT-268 simply started without it being resolved either way.
   **Guard:** NONE — there's no tracker/CI mechanism forcing a pending retro recommendation to be
   revisited; the only safety net is the next retro re-reading the previous one (which is what
   surfaced this). **Disposition: accepted risk** for a solo, no-CI, ephemeral project. Same
   shape as two Phase 0 findings (Linear auto-close drift, PRD self-verify TODOs) — a written
   intention with no forcing function to execute it. No new mitigation proposed beyond what
   Phase 0 already captured; this retro itself is the forcing function this time, and it worked.

3. **Invariant:** every real-money spend surface has a technical, not merely advisory, stop-gap
   (per [[feedback-real-stopgaps]]).
   **Violation:** OpenRouter spend has no AWS-Budgets-side coverage at all (the hard-stop only
   denies AWS API actions).
   **Guard:** OpenRouter has no IAM-deny equivalent, but disabling auto-topup against a finite
   prepaid balance is a real (non-advisory) stop — once the balance is exhausted, further calls
   fail closed, not just alert. Applied as QNT-268 AC5, re-checked for QNT-269's added volume as
   its own AC5. **Disposition: guarded**, with the caveat that "real" here means "vendor-side hard
   stop," the closest available equivalent since OpenRouter has no AWS-Budgets-Action analog.

**Same-shape clustering:** findings 2 is the same shape as Phase 0's tracker-drift and
PRD-TODO-grepping findings (a written intention, no execution forcing function) — no new guard
invented for it this time either; same accepted-risk disposition applies project-wide.

## Lessons captured to memory

- [[lesson-vendor-entitlement-verification]] — new memory: vendor entitlement/access status APIs
  can report fine while real calls fail; always verify with one real minimal call before building
  on top or running at scale.
- [[project-equity-rag-aws]] — updated: the Bedrock-access risk note is superseded by ADR-0001's
  Bedrock→OpenRouter pivot; added the first-secret and OpenRouter-spend-guard facts.

## Phase 2 review (QNT-269, QNT-270)

Cross-referencing this retro's findings against Phase 2 found **no gaps** — QNT-269 already
carries every lesson from this phase as explicit acceptance criteria, folded in live during
QNT-268's own ship (same-day, 2026-08-26) rather than left for this retro to catch:

- AC4: real invocation calls for both OpenRouter models (Cohere Rerank 3.5, gpt-oss-20b) required
  before implementation — the entitlement-vs-real-call lesson, already applied.
- AC5: explicit re-check that the OpenRouter dashboard spend limit set in QNT-268 still covers
  QNT-269's added call volume, raising it if not.
- A found-during-review note already schedules removing the now-stale `bedrock:InvokeModel` deny
  statements from QNT-266's IAM policy as part of QNT-269's own work.

QNT-270 (cloud eval) needs no changes — it has no Bedrock references and no new vendor
dependencies.

**No `add`/`drop`/`modify` recommendations for Phase 2.**

## Architecture overview

Updated `docs/architecture/system-overview.md`: status line now reflects QNT-268 as shipped (not
just QNT-267), the index-job row in the components table is marked shipped, the S3 Vectors data
store note mentions the OpenRouter embedding model that populates it, and a new "Secrets"
bullet documents the OpenRouter API key as the project's first secret.

## Plan sync

`docs/project-plan.md` already matched the tracker exactly (Phase 1 items checked with the
ADR-0001 scope-change note, Phase 2+ unchecked, matching Linear's Backlog state) — no changes
needed.

## Next up

Phase 2 — Retrieval & Eval: QNT-269 (retrieval service — Lambda + API Gateway, S3 Vectors +
OpenRouter rerank + generation), then QNT-270 (cloud eval, fills the PRD §7 comparison table).
