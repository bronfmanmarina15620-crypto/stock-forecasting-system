# Decision Log

Record only decisions that change contracts, invariants, or pipeline behavior.

Template:

* Date:
* Decision:
* Rationale:
* Alternatives considered:
* Impacted files:
* Validation / acceptance:

Initial entries:

* Date: 2026-02-22
* Decision: Introduce System Brain documentation bundle under docs/00_SYSTEM_BRAIN/
* Rationale: Prevent context drift; define stable contracts outside chat context.
* Alternatives considered: Keep decisions in chat only (rejected).
* Impacted files: docs/00_SYSTEM_BRAIN/*
* Validation: markdown added; no code changes.

---

* Date: 2026-02-22
* Decision: Restrict nightly trading workflows to weekdays; add daily health check workflow.
* Rationale: Stock-only system uses daily bars — no new market data on Sat/Sun, so weekend trading runs are redundant. Health check (7/7) catches infra/runtime breakage without generating trading artifacts.
* Alternatives considered: Keep 7/7 nightly schedule (rejected — wastes CI minutes on duplicate data).
* Impacted files: `.github/workflows/nightly_pltr.yml`, `.github/workflows/nightly_pltr_shadow.yml`, `.github/workflows/health_check.yml`, `docs/00_SYSTEM_BRAIN/SYSTEM_INVARIANTS.md`
* Validation: cron day-of-week changed to `1-5`; health check runs import smoke + unit tests only; no `run.py` invocation; `workflow_dispatch` preserved on all workflows.
