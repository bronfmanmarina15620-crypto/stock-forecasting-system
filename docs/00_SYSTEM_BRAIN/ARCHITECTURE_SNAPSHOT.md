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

**Contractual artifacts** (required for validity) are defined by `validate_run.py` `REQUIRED_ARTIFACTS`, `SHADOW_ARTIFACTS`, and `DRIFT_ARTIFACTS` dicts. See `AGENT_CONTRACTS.md` for the per-agent breakdown.

Additional root-level files (e.g., `_meta.json`, `config_snapshot.yaml`, `run_summary.json`, `edge_summary.json`) and per-agent outputs (`<AgentName>/output.json`) are produced as implemented by the orchestrator and agents. Mode-dependent folders (e.g., ShadowMonitorAgent, DriftAgent) may appear depending on run mode and history.

## Validation

* `validate_run.py` must pass for any "SUCCESS" run.
* Content hash integrity (`content_hash_sha256`) is checked on key JSON artifacts.
* Parity/replay checks (as implemented) compare canonical artifacts across runs.
