# Architecture Snapshot

> **SNAPSHOT NOTICE**
> This document reflects the repo state at the time of writing.
> Authoritative sources: `validate_run.py` (contracts), `agents/orchestrator_agent.py` (pipeline), `config/strategy.yaml` (defaults).
> If discrepancies exist, treat code as source of truth.

This is a snapshot of the current system shape. Keep it updated after major merges.

## Pipeline Order

**Authoritative pipeline**: `agents/orchestrator_agent.py`. Agent ordering and mode-dependent insertion (e.g., ShadowMonitorAgent in shadow mode) are defined in the orchestrator.

The high-level grouping is: Data ingestion → Feature engineering → Regime detection → Event modeling → Strategy signals → Backtesting → Robustness validation → Decision/Risk → Drift analysis → Portfolio → Dashboard → Memory/Learning.

Mode-dependent agents (e.g., ShadowMonitorAgent, DriftAgent) are conditionally inserted by the orchestrator. Do not hard-code agent counts here; refer to the orchestrator source for the current pipeline.

## Run Directory Shape (High Level)

Each run produces `runs/<TICKER>/<RUN_ID>/` with per-agent subdirectories and root-level metadata/config/report files.

**Contractual artifacts** (required for validity) are defined by `artifacts/contract.py` (`CRITICAL_ARTIFACTS` / `OPTIONAL_ARTIFACTS`). `validate_run.py` imports these lists: missing CRITICAL = FAIL, missing OPTIONAL = WARN. Shadow and drift artifacts are validated only when their agent folder exists. See `AGENT_CONTRACTS.md` for the per-agent breakdown.

Additional root-level files (e.g., `_meta.json`, `config_snapshot.yaml`, `run_summary.json`, `edge_summary.json`) and per-agent outputs (`<AgentName>/output.json`) are produced as implemented by the orchestrator and agents. Mode-dependent folders (e.g., ShadowMonitorAgent, DriftAgent) may appear depending on run mode and history.

## Data Snapshot Layer

* `data/snapshot_store.py` provides deterministic save/load/hash for DataFrames.
* Every run saves `DataAgent/data_snapshot.parquet` + `DataAgent/snapshot_hash.txt`.
* Replay mode (`--replay-from <path>`) loads the frozen snapshot — no live data fetch. Accepts both a run directory or a direct `.parquet` path.
* Snapshot hash method: `canonical_df_v1` — columns in deterministic order, NaN-normalized, DatetimeIndex in ISO format, stable dtypes. Not dependent on parquet bytes.

## Artifact Contract

* `artifacts/contract.py` defines `CRITICAL_ARTIFACTS`, `OPTIONAL_ARTIFACTS`, `CONTENT_HASH_TARGETS`, `VALID_DECISIONS`, `PARITY_IGNORE`, and schema required-keys lists.
* `tools/compare_runs.py` compares two run directories for replay parity using canonical JSON hashes and snapshot hashes. `PARITY_IGNORE` lists files excluded from comparison (e.g., `final_report.html` contains timestamps; deterministic content is verified via `final_report.json`).
* Regime-dependent artifacts (shadow, drift) are OPTIONAL — a no-trade or ABSTAIN regime must not cause validation failure.

## Canonical JSON Writer

* `determinism.dump_canonical_json(path, obj, *, default=None)` is the **single authoritative writer** for all JSON artifacts on the critical path.
* Format: `indent=2`, `sort_keys=True`, `ensure_ascii=False`, trailing newline.
* The optional `default` parameter (e.g., `default=str`) allows serialization of non-standard types such as numpy scalars or datetime objects.
* All agent write sites use this function: `BaseAgent.save_output()`, `BaseAgent.save_artifact()`, `DashboardAgent` (final_report.json), `OrchestratorAgent` (status.json), `DriftAgent._write_json()`, `ShadowMonitorAgent._write_json()`, and `run.py` (_meta.json, run_summary.json, edge_summary.json).

## Validation

* `validate_run.py` must pass for any "SUCCESS" run.
* Content hash integrity (`content_hash_sha256`) is checked on key JSON artifacts (step 8).
* Data snapshot hash integrity is checked (step 8b).
* Parity/replay checks via `tools/compare_runs.py` compare canonical artifacts across runs. `validate_run.py --compare-to <run_dir>` integrates parity into the validation pipeline.

## Thread / Env Determinism Pins

* `run.py` sets `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`, `VECLIB_MAXIMUM_THREADS=1` before any numeric library import, plus `PYTHONHASHSEED=0`.
* All CI workflows and `scripts/determinism_check.sh` mirror the same env vars.
* Test coverage: `tests/test_normalize_json.py::TestDeterminismEnvVars` verifies the pin block is complete.
