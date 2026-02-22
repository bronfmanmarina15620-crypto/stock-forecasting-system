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

```
Data -> Features -> Regime -> EventModel -> Backtest -> Decision/Risk -> Drift -> Portfolio -> [ShadowMonitor] -> Dashboard -> Memory
```

| # | Stage           | Agent                | Purpose                                    |
|---|-----------------|----------------------|--------------------------------------------|
| 1 | Data            | `DataAgent`          | Fetch OHLCV from Yahoo (primary), Stooq (backup) |
| 2 | Features        | `FeatureAgent`       | Generate as-of features (returns, vol, ATR, MA) |
| 3 | Regime          | `RegimeAgent`        | Label market regime (TREND/RANGE x LOW/HIGH VOL) |
| 4 | Event Model     | `EventModelAgent`    | Train logistic model for 5-day +2% event   |
| 5 | Backtest        | `BacktestAgent`      | Walk-forward OOS evaluation with costs      |
| 6 | Decision/Risk   | `DecisionRiskAgent`  | ENTER/ABSTAIN logic + P&L + abstain stats   |
| 7 | Portfolio       | `PortfolioAgent`     | Position sizing (PASSIVE mode, no execution)|
| 7b| Shadow Monitor  | `ShadowMonitorAgent` | Drift metrics + monitoring (shadow mode only, Phase 7) |
| 7c| Drift Analysis  | `DriftAgent`         | Cross-run drift z-scores from shadow history (Phase 8) |
| 8 | Dashboard       | `DashboardAgent`     | Generate final_report.html + final_report.json |
| 9 | Memory          | `MemoryLearningAgent`| Store run metrics, generate suggestions     |

The `OrchestratorAgent` coordinates execution. No agent calls another directly.
In shadow mode (`--mode shadow`), `ShadowMonitorAgent` is inserted before `DashboardAgent`.

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

Every run produces:

```
runs/PLTR/<RUN_ID>/
  config_snapshot.yaml         # Frozen config for this run
  config.json                  # Frozen config (JSON format)
  status.json                  # Per-stage pass/fail with timestamps
  status.txt                   # Human-readable status (legacy)
  final_report.html            # Dashboard HTML
  final_report.json            # Machine-readable report
  DataAgent/
    output.json                # Agent output metadata
    agent.log                  # Agent log
    bars_raw.parquet           # Raw OHLCV
    bars_adj.parquet           # Adjusted OHLCV
    quality_report.json        # Data quality checks
  FeatureAgent/
    output.json
    features_v1.parquet        # Generated features
    feature_manifest.json      # Feature descriptions + stats
  RegimeAgent/
    output.json
    regime_series.parquet      # Regime label per date
    regime_definition.json     # Regime definitions + counts
  EventModelAgent/
    output.json
    event_model.pkl            # Trained model
    calibration.json           # Calibration stats
    model_card.md              # Model documentation
  BacktestAgent/
    output.json
    predictions_oos.parquet    # OOS predictions
    trades.parquet             # Trade records
    pnl_series.parquet         # Cumulative P&L
    metrics.json               # Performance metrics
    sanity_tests.json          # Leakage detection results
    costs_assumptions.json     # Trading cost details
    backtest_report.html       # Backtest visual report
  DecisionRiskAgent/
    output.json
    signals.csv                # All signals with actions
    decision_action.json       # Current decision (latest)
    decision_explain.json      # Decision statistics
    strategy_pnl.parquet       # Strategy P&L series
    abstain_stats.json         # Abstain/Enter ratios
  PortfolioAgent/
    output.json
    portfolio_plan.json        # Allocation plan
    portfolio_report.html      # Portfolio visual report
    risk_summary.json          # Risk metrics
  DriftAgent/
    output.json                # Agent output metadata
    drift_summary.json         # Z-scores, drift flag, coverage counts, debug samples, drift_reason_summary
    drift_timeseries.parquet   # Per-run history with z-scores
    status.txt                 # One-line status summary
  DashboardAgent/
    output.json                # Agent output metadata
  MemoryLearningAgent/
    output.json
    lessons_learned.md         # Run insights
    suggestions.json           # Improvement suggestions
  OrchestratorAgent/
    output.json                # Orchestrator summary
```

---

## Integrity: GREEN vs RED

**Integrity** is computed by `validate_run.py` and stored in `status.json`.

### GREEN (all must pass)

1. **Artifacts complete**: All required files exist per agent
2. **Sanity tests pass**: shuffled_labels_auc <= 0.55 AND future_shift_auc <= 0.55
3. **Metrics present**: EV_per_trade, max_drawdown, win_rate, avg_trades_per_month all present in metrics.json
4. **Abstain stats present**: abstain_ratio, enter_count, abstain_count, signals_per_month present
5. **OOS sample count**: >= 20 minimum (warning if < 250)
6. **JSON schema valid**: final_report.json passes schema validation
7. **Data quality**: DataAgent quality_report.passed == true

### RED (any failure)

- Missing required artifact -> RED
- Sanity test AUC above threshold -> RED (possible leakage)
- Missing metric fields -> RED
- Agent status == FAILED -> RED

### Where computed

- **Per-agent**: Each agent sets `status` in its `output.json`
- **Pipeline-level**: `OrchestratorAgent` aggregates into `status.json`
- **Post-run**: `validate_run.py` performs independent validation

---

## Determinism

- `random_seed: 42` set via `set_random_seeds()` before every run
- All scikit-learn models use `random_state=42`
- Run ID includes timestamp + random suffix for uniqueness
- Config snapshot frozen at run start

---

## Data Flow

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
  RegimeAgent (regime_series.parquet) <-- MA/vol regimes, shifted by 1 day
       |
       v
  EventModelAgent (event_model.pkl)   <-- logistic + isotonic calibration
       |
       v
  BacktestAgent (predictions_oos.parquet) <-- walk-forward, no leakage
       |
       v
  DecisionRiskAgent (decision_action.json) <-- ENTER/ABSTAIN + because
       |
       v
  PortfolioAgent (portfolio_plan.json)  <-- PASSIVE sizing
       |
       v
  DashboardAgent (final_report.html/json) <-- everything aggregated
       |
       v
  MemoryLearningAgent (suggestions.json) <-- learning, never auto-applied
```
