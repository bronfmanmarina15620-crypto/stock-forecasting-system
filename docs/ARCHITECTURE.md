# Architecture: Stock Forecasting System (PLTR)

## System Brain (Source of Truth)

* docs/00_SYSTEM_BRAIN/SYSTEM_INVARIANTS.md
* docs/00_SYSTEM_BRAIN/AGENT_CONTRACTS.md
* docs/00_SYSTEM_BRAIN/ARCHITECTURE_SNAPSHOT.md
* docs/00_SYSTEM_BRAIN/CONTEXT_HANDOFF.md

## Overview

Single-ticker (PLTR) edge-gated trading system. The pipeline runs daily,
computes a decision (ENTER or ABSTAIN), and produces an auditable run folder
with every artifact needed to reconstruct the reasoning.

**Core Rule**: Never trade unless the edge is proven and conditions fit.
Default action is always ABSTAIN.

---

## Pipeline Stages

**Authoritative pipeline**: see `agents/orchestrator_agent.py`. Mode-dependent pipeline (e.g., shadow vs normal) uses conditional insertion defined in the orchestrator.

The high-level flow is:

```
Data -> Features -> Regime -> VolatilityRegime -> EventModel -> Strategy -> Backtest -> Robustness -> Decision/Risk -> [Drift] -> Portfolio -> [ShadowMonitor] -> Dashboard -> Memory
```

The `OrchestratorAgent` coordinates execution. No agent calls another directly. Agent ordering and mode-dependent insertion (e.g., ShadowMonitorAgent in shadow mode) are implemented in the orchestrator; docs should not hard-code counts or exact ordering.

---

## File Map

### Source Code

| File                              | Role                                        |
|-----------------------------------|---------------------------------------------|
| `run.py`                          | CLI entrypoint, creates run_id, invokes orchestrator |
| `config.py`                       | Dataclass configs (Data/Feature/Regime/Event/Backtest/Decision/Portfolio/Memory) |
| `utils.py`                        | Logging, run_id generation, directory setup, helpers |
| `validate_run.py`                 | Post-run validator (artifacts, sanity, metrics, schema) |
| `agents/base_agent.py`           | Abstract base: save_output, save_artifact, load_agent_output |
| `agents/orchestrator_agent.py`   | Sequential agent execution, status.json writing |
| `agents/data_agent.py`           | Yahoo/Stooq fetch with quality validation    |
| `agents/feature_agent.py`        | As-of feature generation (all shifted by 1)  |
| `agents/regime_agent.py`         | MA20/MA50 trend + vol regime labeling        |
| `agents/event_model_agent.py`    | Logistic regression + isotonic calibration   |
| `agents/backtest_agent.py`       | Walk-forward backtest with cost modeling     |
| `agents/decision_risk_agent.py`  | Signal generation, PnL, abstain stats        |
| `agents/portfolio_agent.py`      | PASSIVE portfolio plan                       |
| `agents/shadow_monitor_agent.py` | Shadow mode drift metrics (Phase 7)          |
| `agents/drift_agent.py`         | Cross-run drift analysis (Phase 8)           |
| `analytics/drift_metrics.py`    | Pure drift metric functions (z-score, history)|
| `agents/dashboard_agent.py`      | HTML + JSON report generation                |
| `agents/memory_learning_agent.py`| SQLite persistence, suggestions              |
| `datasources/yahoo_finance.py`   | yfinance adapter with caching                |
| `datasources/stooq.py`           | Stooq adapter (stub)                         |
| `datasources/base.py`            | Abstract data source interface               |

### Config

| File                  | Role                                               |
|-----------------------|----------------------------------------------------|
| `config.py`           | Default configuration (SystemConfig dataclass)      |
| `example_config.json` | Example JSON config for `--config` flag             |

### Automation

| File                                    | Role                             |
|-----------------------------------------|----------------------------------|
| `.github/workflows/nightly_pltr.yml`    | Nightly scheduled run + Telegram |
| `.github/workflows/nightly_pltr_shadow.yml` | Nightly shadow mode run + Telegram |
| `scripts/smoke_test_10_runs.sh`         | 10-run stability gate            |
| `scripts/daily_run.sh`                  | Daily pipeline + validation      |

---

## Run Directory Structure

Every run produces a folder under `runs/<TICKER>/<RUN_ID>/` with per-agent subdirectories.

### Contractual artifacts (required for validity)

Enforced by `validate_run.py` `REQUIRED_ARTIFACTS`. Missing contractual artifacts cause validation failure.

| Scope | Examples |
|-------|---------|
| Root-level | `status.txt`, `status.json`, `config.json`, `config_snapshot.yaml`, `final_report.html`, `final_report.json` |
| BacktestAgent | `trades.parquet`, `pnl_series.parquet`, `metrics.json`, `costs_assumptions.json`, `risk_explain.json` |
| DecisionRiskAgent | `signals.csv`, `abstain_stats.json`, `decision_action.json`, `decision_explain.json` |
| RobustnessAgent | `summary.json`, `monte_carlo.json` |
| ShadowMonitorAgent (shadow mode) | `shadow_metrics.json`, `shadow_summary.json` (validated only when folder exists) |
| DriftAgent (when present) | `drift_summary.json` (validated only when folder exists) |

> **Authoritative list**: `validate_run.py` `REQUIRED_ARTIFACTS`, `SHADOW_ARTIFACTS`, and `DRIFT_ARTIFACTS` dicts.

### Optional / debug artifacts

Each agent may emit additional files (logs, HTML reports, parquet analysis files, model artifacts) for debugging and analysis. These are not enforced by validation and may change between releases. See each agent's implementation for the current set.

---

## Integrity: GREEN vs RED

**Integrity** is computed by `validate_run.py` and stored in `status.json`.

### GREEN (all must pass)

`validate_run.py` runs a series of validation steps (artifact completeness, sanity tests, required metrics, content hash integrity, edge gates, and others). See `validate_run.py` for the authoritative step list and thresholds.

### RED (any failure)

Any validation step failure causes RED. Common failure classes include missing required artifacts, sanity test leakage detection, content hash mismatches, and edge gate failures. See `validate_run.py` for the authoritative failure conditions and thresholds.

### Where computed

- **Per-agent**: Each agent sets `status` in its `output.json`
- **Pipeline-level**: `OrchestratorAgent` aggregates into `status.json`
- **Post-run**: `validate_run.py` performs independent validation (authoritative gate)

---

## Determinism

- `random_seed: 42` set via `set_random_seeds()` before every run
- All scikit-learn models use `random_state=42`
- Run ID includes timestamp + random suffix for uniqueness
- Config snapshot frozen at run start

---

## Data Flow (Simplified)

High-level flow showing key artifacts. For the complete pipeline and mode-dependent agents, see `agents/orchestrator_agent.py`.

```
Yahoo Finance API
       |
       v
  DataAgent (bars_adj.parquet)
       |
       v
  FeatureAgent (features_v1.parquet)  <-- all features shifted by 1 day
       |
       v
  RegimeAgent / VolatilityRegimeAgent <-- market regime classification
       |
       v
  EventModelAgent (event_model.pkl)   <-- logistic + isotonic calibration
       |
       v
  StrategyAgent (strategy_signals)    <-- MA150+ATR signals
       |
       v
  BacktestAgent (trades/pnl/metrics)  <-- walk-forward, no leakage
       |
       v
  RobustnessAgent (summary.json)     <-- robustness validation
       |
       v
  DecisionRiskAgent (decision_action) <-- ENTER/ABSTAIN + because
       |
       v
  [DriftAgent / ShadowMonitorAgent]   <-- mode-dependent
       |
       v
  PortfolioAgent (portfolio_plan)     <-- PASSIVE sizing
       |
       v
  DashboardAgent (final_report)       <-- everything aggregated
       |
       v
  MemoryLearningAgent (suggestions)   <-- learning, never auto-applied
```
