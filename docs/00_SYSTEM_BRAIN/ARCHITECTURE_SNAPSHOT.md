# Architecture Snapshot

This is a snapshot of the current system shape. Keep it updated after major merges.

## Pipeline Order (Current)

Defined in `agents/orchestrator_agent.py`. All agents run in every backtest-mode run.

1. DataAgent
2. FeatureAgent
3. RegimeAgent
4. VolatilityRegimeAgent
5. EventModelAgent
6. StrategyAgent
7. BacktestAgent
8. RobustnessAgent
9. DecisionRiskAgent
10. DriftAgent
11. PortfolioAgent
12. DashboardAgent
13. MemoryLearningAgent

In shadow mode (`--mode shadow`), ShadowMonitorAgent is inserted before DashboardAgent.

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
