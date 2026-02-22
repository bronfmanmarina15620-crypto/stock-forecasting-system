# Strategy Contract: MA150 + ATR

## Indicators

* MA150: 150-period simple moving average on Close.
* ATR: Average True Range, default 14-period. Configured via `config/strategy.yaml` (`atr_length`).

## Parameters (source of truth: `config/strategy.yaml`)

Defaults are defined in **`config/strategy.yaml`**. Key parameters include `atr_length`, `atr_mult`, `slope_lookback`, `entry_lookback`, `atr_pct_high`, and `slope_min`. Refer to that file for current values.

## Core Rules (Contract-Level)

* Trend filter: close > MA150 AND MA150 slope > 0.
* RANGE_HIGH_VOL block: weak trend + high ATR/close ratio blocks entry.
* Entry: breakout (per `entry_lookback`) when regime_ok (as implemented in `strategy/ma150_atr.py`).
* Exit: ATR trailing stop (highest close since entry minus atr_mult * ATR).
* Position: 0/1 (long-only, no shorting).
* All logic must be deterministic; no randomness.

## Output Artifacts (StrategyAgent)

* `strategy_signals.parquet` — columns: regime_ok, range_high_vol, ma150_trend_ok, entry_signal, exit_signal, stop_price, position
* `strategy_explain.json` — daily reasons keyed by date
* `stop_series.parquet` — columns: date, stop_price, position

## No Strategy Proliferation

* This contract documents the single allowed strategy.
* Any new strategy requires an explicit design + invariants update.
