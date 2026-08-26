# Docs index

## Architecture
- [System overview](architecture/system-overview.md) — how the system works now

## Planning
- [Requirements](PRD.md) — what & why (the PRD is the spec, per profile.docs.spec)
- [Plan](project-plan.md) — execution tracker

## Decisions (ADRs)
<!-- One line per ADR, newest last. change-scope/sync-plan/retro append here. -->
- [ADR template](decisions/TEMPLATE.md)
- [ADR-0001: Drop AWS Bedrock for OpenRouter as the model-serving layer](decisions/0001-bedrock-to-openrouter.md) — 2026-08-26, unresolved AWS Bedrock account-quota provisioning defect

## Retrospectives
<!-- One per completed milestone; retro appends here. -->
- [Phase 0 — Foundation](retros/phase-0-foundation.md) — QNT-266 shipped; invariant/guard audit, Bedrock model-access gap surfaced for Phase 1
- [Phase 1 — Corpus & Index](retros/phase-1-corpus-and-index.md) — QNT-267/QNT-268 shipped; Bedrock→OpenRouter pivot (ADR-0001), vendor-entitlement lesson, no gaps found for Phase 2
