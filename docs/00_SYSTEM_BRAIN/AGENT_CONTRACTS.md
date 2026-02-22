# Agent Contracts

Each agent has a clear input/output contract. Contracts prevent context drift and integration mistakes.
Pipeline order is defined in `agents/orchestrator_agent.py`.

## Artifact Classification

* **Contractual**: required for a valid run; enforced by `validate_run.py` `REQUIRED_ARTIFACTS`. Missing contractual artifacts cause validation failure.
* **Optional**: additional outputs produced by the agent but not enforced by `validate_run.py`. May change or be added without breaking run validity.

Agents whose outputs are not enforced by `validate_run.py` list their outputs as "Outputs (as implemented)".

---

## OrchestratorAgent

* Role: runs agents in a fixed order; sets run directory structure.
* Inputs: CLI args/config.
* Contractual: `status.json`, `status.txt` (written to run root).
* Outputs (as implemented): `OrchestratorAgent/output.json`.

## DataAgent

* Role: fetches OHLCV data (no future data).
* Inputs: ticker, date range / provider config.
* Outputs (as implemented): `bars_raw.parquet`, `bars_adj.parquet`, `quality_report.json`.

## FeatureAgent

* Role: compute lagged technical features (no future leakage).
* Inputs: OHLCV output from DataAgent.
* Outputs (as implemented): `features_v1.parquet`, `feature_manifest.json`.

## RegimeAgent

* Role: label market regime (trend/range, high/low volatility classification).
* Inputs: OHLCV + features (as implemented).
* Outputs (as implemented): `regime_series.parquet`, `regime_definition.json`.

## VolatilityRegimeAgent

* Role: classify volatility regime (QUIET / NORMAL / EXPANDING / EXTREME).
* Inputs: OHLCV (close, high, low) for ATR ratio computation (as implemented).
* Outputs (as implemented): `regime_series.parquet`, `regime_latest.json`, `metrics.json`.

## EventModelAgent

* Role: calibrated probability model for event risk (as implemented).
* Inputs: features/regime outputs.
* Outputs (as implemented): `event_model.pkl`, `calibration.json`, `model_card.md`.

## StrategyAgent

* Role: compute MA150+ATR signals, stop levels, and eligibility.
* Inputs: OHLCV from DataAgent (close, high, low).
* Outputs (as implemented): `strategy_signals.parquet`, `strategy_explain.json`, `stop_series.parquet`.

## BacktestAgent

* Role: signal-driven backtest with R-multiple sizing (as implemented).
* Inputs: strategy signals + OHLCV.
* Contractual: `trades.parquet`, `pnl_series.parquet`, `metrics.json`, `costs_assumptions.json`, `risk_explain.json`.

## RobustnessAgent

* Role: monte carlo / walk-forward / sensitivity / exposure decomposition (as implemented).
* Inputs: backtest + signals + OHLCV.
* Contractual: `summary.json`, `monte_carlo.json`.
* Optional: additional analysis JSONs (as implemented in `agents/robustness_agent.py`).

## DecisionRiskAgent

* Role: final decision normalization (ENTER/ABSTAIN/EXIT/UNKNOWN) and risk sizing (as implemented).
* Inputs: strategy + regime + robustness + backtest metrics.
* Contractual: `decision_action.json`, `decision_explain.json`, `signals.csv`, `abstain_stats.json`.
* Optional: `strategy_pnl.parquet`.

## DriftAgent

* Role: cross-run drift analysis using z-scores from shadow run history.
* Inputs: current run artifacts + historical runs under `runs/<TICKER>/`.
* Contractual (when DriftAgent folder exists): `drift_summary.json`.
* Optional: `drift_timeseries.parquet`, `status.txt`.

## PortfolioAgent

* Role: generate position sizing plan (PASSIVE mode, no execution).
* Inputs: DecisionRiskAgent output.
* Outputs (as implemented): `portfolio_plan.json`, `portfolio_report.html`, `risk_summary.json`.

## ShadowMonitorAgent (shadow mode only)

* Role: monitoring-only drift/quality metrics for shadow runs. Inserted before DashboardAgent when `--mode shadow`.
* Inputs: strategy + decision + backtest + regime outputs.
* Contractual (when ShadowMonitorAgent folder exists): `shadow_metrics.json`, `shadow_summary.json`.

## DashboardAgent

* Role: generate final_report.html and JSON summary outputs.
* Inputs: all upstream artifacts needed for report.
* Contractual: `final_report.html`, `final_report.json` (written to run root).

## MemoryLearningAgent

* Role: logs run summary and metrics for future analysis (no ML unless explicitly enabled).
* Inputs: summary + metrics.
* Outputs (as implemented): `lessons_learned.md`, `suggestions.json`.
