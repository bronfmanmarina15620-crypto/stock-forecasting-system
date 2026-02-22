# System Invariants

These are non-negotiable. Any change that violates these requires an explicit PR, documentation update, and validation.

## Determinism

* Same input data + same config + same code version => same outputs and decisions.
* JSON artifacts must be canonical (sorted keys; stable ordering) where applicable.
* No hidden randomness. Any randomness must be seeded and documented.

### Full Deterministic Mode

* **Thread/env pinning**: `run.py` sets `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`, `VECLIB_MAXIMUM_THREADS=1`, and `PYTHONHASHSEED=0` before any numeric library import. All CI workflows (`nightly_pltr.yml`, `determinism.yml`) set the same env vars. The determinism check script (`scripts/determinism_check.sh`) also sets them and accepts a configurable `PYTHON` binary.
* **As-of date**: Every run has a frozen `as_of_date` (end date for data window). Precedence: `--as-of` CLI flag > `AS_OF_DATE` env var > today. Persisted in `_meta.json` and `config_snapshot.yaml`.
* **Data snapshots**: DataAgent saves a normalized `data_snapshot.parquet` + `snapshot_hash.txt` every run. The snapshot hash (method: `canonical_df_v1`) is computed from the DataFrame's logical content (columns, dtypes, sorted index in ISO format, NaN-normalized values) — not parquet bytes — for cross-environment stability. The hash method is recorded in `data_snapshot_hash_method` in run metadata.
* **Replay mode**: `--replay-from <path>` loads data from a prior run's snapshot instead of fetching live data. Accepts both a run directory or a direct `.parquet` file path. No network calls in replay mode.
* **Canonical JSON**: All critical-path JSON writes use `determinism.dump_canonical_json()` (sorted keys, indent=2, ensure_ascii=False, trailing newline) for globally consistent serialization. This includes `BaseAgent.save_output()`, `BaseAgent.save_artifact()`, `DashboardAgent`, `OrchestratorAgent`, `DriftAgent`, `ShadowMonitorAgent`, and all `run.py` metadata writes. The function accepts an optional `default` parameter for non-standard types.
* **Replay parity gate**: `tools/compare_runs.py` compares canonical JSON hashes and snapshot hashes between two runs. Exit code 0 = parity PASS, 1 = FAIL. `final_report.html` is excluded from parity comparison (contains generation timestamps); deterministic content is verified via `final_report.json`.
* **Determinism check**: `bash scripts/determinism_check.sh [TICKER] [AS_OF_DATE]` runs live + replay and verifies parity end-to-end. Configurable via `PYTHON` env var.
* **CI smoke test**: `determinism.yml` includes a `determinism-smoke` job (manual dispatch only) that runs a pinned-date determinism check.
* **Nightly replay parity**: The nightly workflow runs a live run, then a replay from its snapshot, and compares both for parity. Replay validation uses `--skip-edge` (structural only). Parity failure triggers Telegram notification.
* **Determinism CI isolation**: `determinism_check.sh` and CI smoke runs use `validate_run.py --skip-edge` so that determinism verification fails ONLY on reproducibility/parity/schema/hash issues — never on edge gate results. Edge gating is enforced separately at run time (`run.py`) and in nightly primary validation.

## Strategy Scope

* Single trading strategy only: MA150 + ATR.
* No additional strategies, ensembles, or ML-driven entry/exit logic unless explicitly planned and documented.

## No Implicit Fallbacks

* No silent fallback for missing data, missing artifacts, or missing upstream outputs.
* Fail fast with explicit error when required inputs are absent.

## Artifact Integrity

* Required artifacts must be produced for every run, and validated by `validate_run.py`.
* Any artifact hashing/integrity checks must be stable and reproducible.
* The canonical artifact contract is defined in `artifacts/contract.py` (`CRITICAL_ARTIFACTS`, `OPTIONAL_ARTIFACTS`, `CONTENT_HASH_TARGETS`, `VALID_DECISIONS`, `PARITY_IGNORE`, schema key lists).
* `validate_run.py` imports from `artifacts/contract.py`: missing CRITICAL artifacts FAIL validation; missing OPTIONAL artifacts produce a WARNING only.
* `validate_run.py` verifies data snapshot hash integrity (step 8b) in addition to JSON content hashes (step 8).

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
* **Hard failure enforcement at run time:** edge exit_code 1 (gates fail) or 2 (missing/invalid artifacts) must prevent run status SUCCESS. `run.py` runs edge validation before writing the final status; failure marks the run FAILED with a non-zero program exit code. No fallback path can produce SUCCESS when edge_exit_code != 0.
* **Decoupled from determinism CI:** Determinism verification (`determinism_check.sh`, CI smoke runs) uses `validate_run.py --skip-edge` so that reproducibility checks are independent of edge/performance gating. Edge is enforced at run time (`run.py`) and in the nightly primary validation step (without `--skip-edge`).
* **Exit code semantics:** 0 = edge PASS, 1 = edge computed but gates FAIL, 2 = missing/invalid artifacts.

## Change Control

* Any change to contracts/invariants must:

  1. update this file
  2. update relevant contract docs
  3. include validation steps and acceptance criteria

* Documentation must not hard-code implementation details that are likely to evolve (agent counts, artifact lists, parameter values) unless they are contractual. Reference source files (e.g., `agents/orchestrator_agent.py`, `config/strategy.yaml`) as the source of truth.
