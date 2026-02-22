# Architecture Snapshot

This is a snapshot of the current system shape. Keep it updated after major merges.

## Pipeline Order

**Authoritative pipeline**: `agents/orchestrator_agent.py`. Agent ordering and mode-dependent insertion (e.g., ShadowMonitorAgent in shadow mode) are defined in the orchestrator.

The high-level grouping is: Data ingestion → Feature engineering → Regime detection → Event modeling → Strategy signals → Backtesting → Robustness validation → Decision/Risk → Drift analysis → Portfolio → Dashboard → Memory/Learning.

Mode-dependent agents (e.g., ShadowMonitorAgent, DriftAgent) are conditionally inserted by the orchestrator. Do not hard-code agent counts here; refer to the orchestrator source for the current pipeline.

## Run Directory Shape (High Level)

* runs/<TICKER>/<RUN_ID>/

  * `_meta.json` — run metadata (ticker, run_id, git SHA, created_utc)
  * `config.json` — frozen config (JSON)
  * `config_snapshot.yaml` — frozen config (YAML)
  * `status.json` — per-stage pass/fail with timestamps and integrity flag
  * `status.txt` — human-readable status (legacy format)
  * `run_summary.json` — ticker, decision, status, timestamps
  * `final_report.html` — dashboard HTML report
  * `final_report.json` — machine-readable report
  * `<AgentName>/output.json` — per-agent output metadata

Top-level required artifacts are defined by `validate_run.py` `REQUIRED_ARTIFACTS`; additional agent-specific artifacts may exist beyond those. Mode-dependent folders (e.g., ShadowMonitorAgent, DriftAgent) may appear depending on run mode and history.

## Validation

* `validate_run.py` must pass for any "SUCCESS" run.
* Content hash integrity (`content_hash_sha256`) is checked on key JSON artifacts.
* Parity/replay checks (as implemented) compare canonical artifacts across runs.
