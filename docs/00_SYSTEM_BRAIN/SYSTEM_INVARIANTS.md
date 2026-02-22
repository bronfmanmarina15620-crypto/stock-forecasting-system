# System Invariants

These are non-negotiable. Any change that violates these requires an explicit PR, documentation update, and validation.

## Determinism

* Same input data + same config + same code version => same outputs and decisions.
* JSON artifacts must be canonical (sorted keys; stable ordering) where applicable.
* No hidden randomness. Any randomness must be seeded and documented.

## Strategy Scope

* Single trading strategy only: MA150 + ATR.
* No additional strategies, ensembles, or ML-driven entry/exit logic unless explicitly planned and documented.

## No Implicit Fallbacks

* No silent fallback for missing data, missing artifacts, or missing upstream outputs.
* Fail fast with explicit error when required inputs are absent.

## Artifact Integrity

* Required artifacts must be produced for every run, and validated by `validate_run.py`.
* Any artifact hashing/integrity checks must be stable and reproducible.

## Pipeline Contract

* Agent pipeline order must remain stable unless explicitly changed and documented.
* Each agent reads only its declared inputs and writes only its declared outputs.

## Nightly/Automation Safety

* Nightly runs must not mutate repo state.
* Notifications must reflect true run status (success/failure) based on validated artifacts.
* Nightly trading workflows (standard + shadow) run Mon–Fri only (stock-only, daily bars — no new data on weekends). Schedule is `21:00 UTC` (cron `0 21 * * 1-5`); local Israel time varies with DST (23:00 IST winter / 00:00 IDT summer next-day). Day-of-week is evaluated in UTC, so Friday's run always fires on Friday UTC regardless of local offset.
* A separate daily health check workflow runs 7/7 for infra/runtime breakage detection. It must NOT execute `run.py` or produce `runs/` artifacts.

## Edge Validation

* `tools/edge_validate.py` provides a formal, quantitative edge gate for the MA150+ATR strategy.
* Edge metrics (expectancy, profit factor, drawdown in R, rolling stability, walk-forward stability) are computed deterministically from existing run artifacts only.
* Thresholds are defined in `config/edge.yaml` (runtime source of truth) and documented in `EDGE_DEFINITION.md`.
* Missing or invalid artifacts must cause validation failure (exit code 2), never silent fallback.
* Kill-switch conditions (rolling edge breakdown, drawdown shock) force ABSTAIN until explicit reset criteria are met.
* **Hard failure enforcement:** edge exit_code 1 (gates fail) or 2 (missing/invalid artifacts) must prevent run status SUCCESS. `run.py` runs edge validation before writing the final status; failure marks the run FAILED with a non-zero program exit code. No fallback path can produce SUCCESS when edge_exit_code != 0.
* **Exit code semantics:** 0 = edge PASS, 1 = edge computed but gates FAIL, 2 = missing/invalid artifacts.

## Change Control

* Any change to contracts/invariants must:

  1. update this file
  2. update relevant contract docs
  3. include validation steps and acceptance criteria

* Documentation must not hard-code implementation details that are likely to evolve (agent counts, artifact lists, parameter values) unless they are contractual. Reference source files (e.g., `agents/orchestrator_agent.py`, `config/strategy.yaml`) as the source of truth.
