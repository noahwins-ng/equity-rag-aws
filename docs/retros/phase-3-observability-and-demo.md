# Retro — Phase 3: Observability & Demo Wrap-up

**Milestone:** Phase 3 — Observability & Demo Wrap-up (the project's final phase)
**Tickets:** QNT-271 (CloudWatch logs + metrics for the retrieval service), QNT-272 (demo
recording + verified teardown + README)
**Timeline:** 2026-08-26 16:55 (QNT-271 In Progress) → 2026-08-30 17:44 (QNT-272 Done), ~4.3
calendar days, mostly idle between the two tickets. Tracked ticket time: QNT-271 ~9 minutes
(16:55 In Progress → 17:03:57 Done, single-commit PR, one brief In Review→In Progress bounce for
the merge); QNT-272 ~3 days 4h16m (08-27 13:28:27 In Progress → 08-30 17:44:30 Done) — the ticket
where every previously-deferred loose end surfaced at once. QNT-272 then briefly flipped
Done → In Progress → Done again on 2026-08-31 at 14:04:17–14:04:21 (4 seconds) — triggered by PR
#17 (this retro's own PR), whose branch name (`noahwinsdev/qnt-272-retro-phase-3`) the
GitHub↔Linear integration parsed as a QNT-272 reference despite neither the commit message nor PR
title mentioning it. Self-resolved back to Done; a live recurrence of
[[feedback-linear-pr-autoclose]] caught only because this retro checked Linear directly after
reconnecting mid-session — see Surprises.
**PRs:** [#15](https://github.com/noahwins-ng/equity-rag-aws/pull/15) (QNT-271, merged
2026-08-26, 1 commit), [#16](https://github.com/noahwins-ng/equity-rag-aws/pull/16) (QNT-272,
merged 2026-08-30, 2 commits) — plus **two commits pushed directly to `main` after PR #16**,
outside any PR (`bcc4106`, `52ac9d9`, both 2026-08-31 — see Surprises).

## What shipped

- QNT-271: `aws_cloudwatch_log_group.retrieval_service` added to Terraform (14-day retention)
  and the pre-existing auto-created log group imported into state, so `terraform destroy` tears
  it down cleanly. Invocation/error/duration metrics needed no new resource — Lambda
  auto-publishes those to `AWS/Lambda` for the already-Terraform-managed function. Verified with
  a real invocation (`aws logs filter-log-events`, `aws cloudwatch get-metric-statistics`).
- QNT-272: the project's closing ticket.
  - Demo video recorded (stand-up → index → query → eval comparison → teardown), published to
    YouTube (unlisted) after two failed attempts at GitHub's native inline-video upload and a
    rejected release-asset link (forced download instead of inline playback).
  - Teardown verified: `terraform destroy` → empty `terraform state list` + ~$0 next-day Cost
    Explorer.
  - README finalized: cost model, per-corpus H1–H3 verdicts (pulled from
    `eval/results/qnt-270-cloud-eval.md`), repro steps, architecture diagram.
  - Pre-publish sweep (AC4) found the AWS account id committed in plaintext across three docs;
    redacted from current content and purged from git history via `git filter-repo`
    (branches rewritten, force-pushed). Four old merged PRs' GitHub-side diff caches (#8, #9,
    #11, #15) still show it — not fixable via git, accepted as low-severity (non-secret, no live
    resource) after discussion with the ticket owner.
  - Repo flipped **public**.

## Velocity

2 of 2 planned tickets shipped, milestone complete, zero rollover — the project's last milestone,
so also project-complete: all 8 delivery-plan tickets (QNT-265 monorepo dependency through
QNT-272) are done. QNT-271 was fast (single-commit PR, same-day merge). QNT-272 took longer and
kept generating follow-up commits after its own "done" mark (see Surprises) — consistent with it
being the ticket where every previously-deferred loose end (secrets, stale docs, a broken video
link) surfaces at once, because nothing gates publish-readiness until the publish step itself.

## Surprises / harder than expected

- **A Lambda-auto-created resource almost escaped Terraform.** AWS auto-creates a CloudWatch log
  group the first time a Lambda runs, if none is pre-declared. QNT-271 found this log group
  already existed outside Terraform's state and had to `terraform import` it before `destroy`
  would fully tear it down. Caught within the same ticket, before merge — no lost work, but it's
  a second instance (after QNT-269's Lambda-concurrency quota surprise) of "AWS does something
  automatically that Terraform doesn't know about by default."
- **Secrets/account-id exposure accumulated silently across four prior tickets, caught only at
  the final pre-publish sweep.** The AWS account id had been committed in plaintext since at
  least Phase 0, across three docs, through PRs #8, #9, #11, and #15, with no check catching it
  until QNT-272 AC4's manual sweep — by which point it required a `git filter-repo` history
  rewrite plus a force-push to fully address, and four PRs' diff caches still carry it
  irrecoverably. Nothing else in the pipeline (no CI, no pre-commit hook, no secret scanner) was
  positioned to catch this earlier.
- **Two commits landed directly on `main` after PR #16 merged, bypassing the branch+PR workflow
  entirely** (`bcc4106`: fix a stale "Bedrock" repo description + add the architecture diagram;
  `52ac9d9`: swap the demo link from a broken GitHub release-asset download to a working YouTube
  embed). Both are legitimate, low-risk README fixes discovered only after the repo went public
  — but CLAUDE.md's Git Workflow section is explicit ("one branch per issue," "merge via `gh pr
  merge`"), and nothing technical enforces it: `main` has no branch protection
  (`gh api .../branches/main/protection` → 404 "Branch not protected"). This is the same
  category of gap as the secrets sweep — a written rule with no executable guard — and it
  surfaced at exactly the point (project tail-end, solo operator, "it's just docs") where the
  temptation to skip process is highest and the perceived cost of skipping it is lowest.
- **Video hosting needed two pivots.** GitHub's inline video-attachment upload failed twice with
  a generic, unresolved error; the release-asset fallback played by forcing a download instead of
  inline playback. YouTube (unlisted, click-to-play thumbnail) was the working third option.
- **The Linear PR auto-close drift recurred, live, during this retro.** This session's Linear MCP
  connection dropped partway through the retro; once reconnected, QNT-272's state history showed
  it had flipped `Done → In Progress → Done` again (2026-08-31 14:04:17–14:04:21) the moment this
  retro's own PR (#17) merged — the GitHub↔Linear integration parsed the branch name
  `noahwinsdev/qnt-272-retro-phase-3` as a QNT-272 reference, despite neither the commit message
  nor the PR title mentioning it. Self-resolved in 4 seconds, no correction needed, but it's the
  exact drift [[feedback-linear-pr-autoclose]] already warns about — caught only because this
  retro happened to check Linear directly after reconnecting, not because anything is watching
  for it.

## Blockers

None external this phase. (The only external blocker in the project — AWS Bedrock's account-wide
quota defect — belongs to Phase 1 and was resolved there by moving to OpenRouter.)

## Invariant → guard audit

1. **Invariant:** every AWS resource a Lambda touches is tracked in Terraform state, so
   `terraform destroy` returns the account to zero.
   **Violation:** the CloudWatch log group Lambda auto-creates on first invocation existed
   outside Terraform's state.
   **Guard:** caught and fixed within QNT-271 itself (`terraform import` + `terraform plan
   -destroy` re-verified full teardown, 0 orphans) before merge.
   **Recurrence (found 2026-09-04, post-close):** the "0 orphans" claim was off by one. QNT-271
   fixed only the retrieval-service group; the index-job Lambda's auto-created group
   (`/aws/lambda/equity-rag-aws-index-job`, 7.7 KB, no retention) survived the QNT-272
   `terraform destroy` because it was never declared or imported. Deleted by hand and
   `aws_cloudwatch_log_group.index_job` added to Terraform so a future stand-up tears it down.
   Lesson sharpened: the fix must cover *every* Lambda in the stack, not just the one the ticket
   is about — grep for `aws_lambda_function` and check each has a matching log group.
   **Disposition: guarded, no new gap** — this project has no further Terraform work coming (it's
   complete), so there's no remaining surface for recurrence here. Generalized to memory for
   future Terraform+Lambda projects: declare the log group explicitly and import on first apply,
   don't wait for a destroy-plan to reveal the gap.

2. **Invariant:** no secrets or account identifiers are ever committed to git, at the moment
   they're written, not just before publish.
   **Violation:** the AWS account id sat in plaintext across three docs for four merged PRs
   (#8, #9, #11, #15) before being caught.
   **Guard:** NONE at commit time — this repo has no CI, no pre-commit hook, and no secret
   scanner; the only check was a single manual sweep gated behind QNT-272's own AC4, i.e. the
   very last ticket of the project.
   **Disposition: accepted risk for this project** — it's complete, the AWS stack is torn down
   (no live resource is exposed), and the account id is not a credential (residual exposure in
   4 PRs' diff caches is non-actionable and low-severity, already discussed with the ticket
   owner in PR #16). **Not accepted as a pattern going forward** — captured to memory
   ([[lesson-defer-secrets-sweep-to-final-ticket]]) as a recommendation for `flow-init` to offer
   a lightweight secret/account-id pre-commit hook by default, so the next project doesn't rely
   on a single end-of-project AC to catch a leak that accumulated ticket by ticket.

3. **Invariant:** all changes to `main` land through a reviewed PR (CLAUDE.md's Git Workflow
   section, stated as unconditional).
   **Violation:** two commits (`bcc4106`, `52ac9d9`) went straight to `main` after PR #16 merged
   — no branch, no PR, no review.
   **Guard:** NONE — `main` has no branch protection (confirmed via the GitHub API: 404 "Branch
   not protected").
   **Disposition: accepted risk for this project** — it's finished, solo-operator, and these two
   commits were low-risk doc fixes with no functional or cost impact. **Flagged as a forward
   lesson**, not fixed here: a written-only process rule is exactly as reliable as the operator's
   discipline at the moment discipline is cheapest to drop (project tail-end, "just a README
   fix"). Captured to memory ([[lesson-pr-bypass-at-project-close]]) for future flow-owned
   projects — branch protection is cheap to turn on and the retro's own audit only exists because
   nothing else would have caught this.

4. **Invariant:** an issue's tracked status reflects real work state — reopening means work
   resumed.
   **Violation:** QNT-272 flipped `Done → In Progress → Done` a second time (08-31, 4 seconds
   apart) with zero actual work done, because PR #17's branch name happened to contain "qnt-272".
   **Guard:** NONE — this is a known, already-memorized gap ([[feedback-linear-pr-autoclose]] from
   a prior ship) that recurred unchanged; nothing was built after the first occurrence to prevent
   it.
   **Disposition: accepted risk, unchanged from the existing memory's disposition** — the
   integration's auto-linking is a Linear/GitHub product behavior, not something this project can
   fix; the existing guidance ("verify status after every merge") already covers it and worked
   here (self-resolved, caught on inspection). No new ticket — this project is complete and has no
   further merges coming.

**Same-shape clustering:** findings 2 and 3 are the same shape — *a rule that exists only as
written guidance (an AC, a CLAUDE.md sentence) has no enforcement once nobody is deliberately
checking it, and both gaps surfaced at the exact same moment: right after the project was
declared "done."* One deeper lesson covers both: **treat project close-out as the highest-risk
window for process shortcuts, not the lowest** — it's when the fewest checks are left engaged and
the strongest urge exists to just push the fix. Captured as a single generalized memory rather
than two narrow ones. Finding 4 is a different shape (a tooling quirk, not a discipline gap) but
worth noting alongside them since it's the same *retro* surfacing it — three distinct gap types,
all only visible because this milestone happened to be the one where nobody was watching closely.

## Lessons captured to memory

- [[project-equity-rag-aws]] — updated: project complete, all 8 tickets shipped, teardown
  verified, repo public; residual AWS-account-id exposure in 4 old PR diff caches (accepted,
  non-secret, no live resource).
- [[lesson-defer-secrets-sweep-to-final-ticket]] — new: a secrets/account-id sweep deferred
  entirely to the project's last ticket let an exposure accumulate for four PRs before being
  caught; recommend `flow-init` wire a lightweight pre-commit secret/account-id scan by default
  instead of relying on a single end-of-project AC.
- [[lesson-pr-bypass-at-project-close]] — new: two commits bypassed the branch+PR workflow
  directly after the project's closing ticket merged, with no branch protection to stop it —
  process discipline is weakest exactly when a project is being wrapped up; turn on branch
  protection (or accept the risk explicitly) rather than relying on the written convention alone.
- [[feedback-linear-pr-autoclose]] — updated: 4th recurrence, sharpened — branch name alone
  (`noahwinsdev/qnt-272-retro-phase-3`) triggered the auto-close drift with no ticket-ID mention
  anywhere in the PR title or commit messages; a clean title/commit history doesn't prevent it.

## Phase review (next milestone)

**There is no next phase.** QNT-272 was the last ticket in the PRD §9 delivery plan; this
project is complete. Nothing to cross-reference forward, and no `add`/`drop`/`modify`
recommendations apply.

## Architecture overview

Updated `docs/architecture/system-overview.md`'s status header: replaced the phase-by-phase
"live/done" framing with a project-complete statement, and added that the AWS stack is now torn
down (verified) — the document describes the architecture as built and reproducible from a clean
`terraform apply`, not currently-running infrastructure.

## Plan sync

Mechanical gap sweep (tracker set vs. `grep -oE 'QNT-[0-9]+' docs/project-plan.md`): tracker set
{QNT-266..272} (Linear `list_issues` for the project, all `Done`) vs. plan set {QNT-265..272}. Gap
= tracker − plan = **empty**. (QNT-265 is in the plan set but not the tracker set by design — it's
the monorepo dependency, tracked in a different repo — already documented as such in the plan.)
Nothing to sync.

## Next up

Nothing — this was the project's final milestone. Remaining open items are the two accepted-risk
dispositions above (no secret-scan guard, no branch protection), both explicitly deferred as
forward-looking lessons rather than new work on a finished project. If the repo takes on further
contributions, revisit both before the next commit lands.
