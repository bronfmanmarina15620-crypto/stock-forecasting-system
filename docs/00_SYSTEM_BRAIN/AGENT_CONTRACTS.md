# Agent Contracts

Each agent has a clear input/output contract. Contracts prevent context drift and integration mistakes.
Pipeline order is defined in `agents/orchestrator_agent.py`.

## OrchestratorAgent

* Role: runs agents in a fixed order; sets run directory structure.
* Inputs: CLI args/config.
* Outputs: `status.json`, `status.txt`, `OrchestratorAgent/output.json`.

## DataAgent

* Role: fetches OHLCV data (no future data).
* Inputs: ticker, date range / provider config.
* Outputs: `bars_raw.parquet`, `bars_adj.parquet`, `quality_report.json`.

## FeatureAgent

* Role: compute lagged technical features (no future leakage).
* Inputs: OHLCV output from DataAgent.
* Outputs: `features_v1.parquet`, `feature_manifest.json`.

## RegimeAgent

* Role: label market regime (trend/range, high/low volatility classification).
* Inputs: OHLCV + features (as implemented).
* Outputs: `regime_series.parquet`, `regime_definition.json`.

## VolatilityRegimeAgent

* Role: classify volatility regime (QUIET / NORMAL / EXPANDING / EXTREME).
* Inputs: OHLCV (close, high, low) for ATR ratio computation (as implemented).
* Outputs: `regime_series.parquet`, `regime_latest.json`, `metrics.json`.

## EventModelAgent

* Role: calibrated probability model for event risk (as implemented).
* Inputs: features/regime outputs.
* Outputs: `event_model.pkl`, `calibration.json`, `model_card.md`.

## StrategyAgent

* Role: compute MA150+ATR signals, stop levels, and eligibility.
* Inputs: OHLCV from DataAgent (close, high, low).
* Outputs: `strategy_signals.parquet`, `strategy_explain.json`, `stop_series.parquet`.

## BacktestAgent

* Role: signal-driven backtest with R-multiple sizing (as implemented).
* Inputs: strategy signals + OHLCV.
* Outputs: `trades.parquet`, `pnl_series.parquet`, `metrics.json`, `costs_assumptions.json`, `risk_explain.json`.

## RobustnessAgent

* Role: monte carlo / walk-forward / sensitivity / exposure decomposition (as implemented).
* Inputs: backtest + signals + OHLCV.
* Outputs: `summary.json`, `monte_carlo.json`, and additional analysis JSONs (as implemented).

## DecisionRiskAgent

* Role: final decision normalization (ENTER/ABSTAIN/EXIT/UNKNOWN) and risk sizing (as implemented).
* Inputs: strategy + regime + robustness + backtest metrics.
* Outputs: `decision_action.json`, `decision_explain.json`, `signals.csv`, `abstain_stats.json`.

## DriftAgent

* Role: cross-run drift analysis using z-scores from shadow run history.
* Inputs: current run artifacts + historical runs under `runs/<TICKER>/`.
* Outputs: `drift_summary.json`, `drift_timeseries.parquet`, `status.txt`.

## PortfolioAgent

* Role: generate position sizing plan (PASSIVE mode, no execution).
* Inputs: DecisionRiskAgent output.
* Outputs: `portfolio_plan.json`, `portfolio_report.html`, `risk_summary.json`.

## ShadowMonitorAgent (shadow mode only)

* Role: monitoring-only drift/quality metrics for shadow runs. Inserted before DashboardAgent when `--mode shadow`.
* Inputs: strategy + decision + backtest + regime outputs.
* Outputs: `shadow_metrics.json`, `shadow_summary.json`.

## DashboardAgent

* Role: generate final_report.html and JSON summary outputs.
* Inputs: all upstream artifacts needed for report.
* Outputs: `final_report.html`, `final_report.json` (written to run root).

## MemoryLearningAgent

* Role: logs run summary and metrics for future analysis (no ML unless explicitly enabled).
* Inputs: summary + metrics.
* Outputs: `lessons_learned.md`, `suggestions.json`.
