# Release Notes (System Brain)

Use this file to record documentation-only releases and major documentation updates.

## 2026-02-22 — Governance Closure (Docs + CI)

- PR #22 merged (squash) → a008f2f
- Tag: docs-freeze-2026-02-22 (anchored to a008f2f)
- CI smoke-run: market-dependent edge failures are tolerated (structural pass remains enforced)
- Branch protections verified in GitHub UI: PR required, status checks required (smoke-run, test), up-to-date required, bypass disabled, force-push disabled

* 2026-02-22: Final drift-hardening pass — removed hard-coded step numbers, added SNAPSHOT NOTICE headers, made calibration/validation references code-authoritative, fixed QUICKSTART.md silent-fallback language and outdated decision criteria.
* 2026-02-22: Added docs/00_SYSTEM_BRAIN bundle (contracts, invariants, playbook, handoff).
