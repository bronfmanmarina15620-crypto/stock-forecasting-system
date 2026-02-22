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

---

* Date: 2026-02-22
* Decision: Implement formal edge validation gate (EDGE_DEFINITION.md + tools/edge_validate.py).
* Rationale: No quantitative gate existed to verify the MA150+ATR strategy has a statistical edge before producing ENTER decisions. The edge validator reads existing run artifacts (trades.parquet, walk_forward.json, monte_carlo.json, regime_contribution.json) and checks against configurable thresholds (config/edge.yaml). Missing artifacts fail validation (exit 2); no silent fallbacks.
* Alternatives considered: Wire directly into DecisionRiskAgent (rejected — larger diff, requires edge tool to run inside pipeline; keep as standalone validation step first). Extend validate_run.py (rejected — separate concern; edge validation is quantitative, not structural).
* Impacted files: `tools/edge_validate.py` (new), `config/edge.yaml` (new), `docs/00_SYSTEM_BRAIN/EDGE_DEFINITION.md` (new), `docs/00_SYSTEM_BRAIN/SYSTEM_INVARIANTS.md`, `docs/00_SYSTEM_BRAIN/AGENT_CONTRACTS.md`, `docs/00_SYSTEM_BRAIN/OPERATOR_PLAYBOOK.md`, `tests/test_edge_validate.py` (new).
* Validation: `python -m pytest tests/test_edge_validate.py -q` passes; `python tools/edge_validate.py --run <path>` prints report with correct exit codes.

---

* Date: 2026-02-22
* Decision: Integrate edge validation into run pipeline and validate_run.py.
* Rationale: Edge validation was standalone; now it runs automatically in two places: (1) `run.py` persists `edge_report.txt` + `edge_summary.json` after every successful run; (2) `validate_run.py` Step 10 checks edge gates and fails validation if gates fail. CI/nightly Telegram notifications now include edge status (PASS/FAIL, N, E, PF, MDD_R). DecisionRiskAgent wiring deferred — edge gate is enforced at validation time only.
* Alternatives considered: Wire edge gates into DecisionRiskAgent (deferred — requires pipeline restructuring since edge depends on RobustnessAgent which runs after DecisionRiskAgent).
* Impacted files: `validate_run.py`, `run.py`, `.github/workflows/nightly_pltr.yml`, `.github/workflows/nightly_pltr_shadow.yml`, `tests/test_edge_validate.py`, System Brain docs.
* Validation: `python -m pytest tests/ -q` passes; edge artifacts created on run; validate_run Step 10 propagates edge failures.
