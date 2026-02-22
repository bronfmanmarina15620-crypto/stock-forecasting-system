# Agent Contracts

Each agent has a clear input/output contract. Contracts prevent context drift and integration mistakes.

## OrchestratorAgent

* Role: runs agents in a fixed order; sets run directory structure.
* Inputs: CLI args/config.
* Outputs: run folder creation; orchestration logs/summary wiring.

## DataAgent

* Role: fetches OHLCV data (no future data).
* Inputs: ticker, date range / provider config.
* Outputs: data artifacts under run directory (OHLCV dataset).

## FeatureAgent

* Role: compute lagged technical features (no future leakage).
* Inputs: OHLCV output.
* Outputs: features artifact(s).

## RegimeAgent

* Role: label market regime (trend/range, high/low volatility classification if applicable).
* Inputs: OHLCV + features (as implemented).
* Outputs: regime labels artifact(s).

## VolatilityRegimeAgent (if present)

* Role: classify volatility regime (QUIET / NORMAL / EXPANDING / EXTREME).
* Inputs: OHLCV/returns/ATR as implemented.
* Outputs: volatility regime artifact(s).

## EventModelAgent (if present)

* Role: calibrated probability model for event risk (as implemented).
* Inputs: features/regime outputs.
* Outputs: event probability artifact(s).

## StrategyAgent

* Role: compute MA150+ATR signals, stop levels, and eligibility.
* Inputs: OHLCV + features + regime outputs (as implemented).
* Outputs: strategy signals artifact(s).

## BacktestAgent

* Role: signal-driven backtest with R-multiple sizing (as implemented).
* Inputs: signals + OHLCV.
* Outputs: backtest metrics/curves artifact(s).

## RobustnessAgent

* Role: monte carlo / walk-forward / sensitivity / exposure decomposition (as implemented).
* Inputs: backtest + signals + OHLCV.
* Outputs: robustness artifacts (multiple JSONs).

## DecisionRiskAgent

* Role: final decision normalization (ENTER/ABSTAIN/EXIT/UNKNOWN), risk sizing, order fields (as implemented).
* Inputs: strategy + regime + robustness + backtest metrics.
* Outputs: decision_action.json (and any order/risk artifacts as implemented).

## DashboardAgent

* Role: generate final_report.html and JSON summary outputs.
* Inputs: all upstream artifacts needed for report.
* Outputs: final_report.html and summary JSONs.

## MemoryLearningAgent (if present)

* Role: logs run summary and metrics for future analysis (no ML unless explicitly enabled).
* Inputs: summary + metrics.
* Outputs: memory logs/artifacts.
