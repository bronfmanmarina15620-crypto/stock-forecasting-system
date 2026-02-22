# Strategy Contract: MA150 + ATR

## Indicators

* MA150: 150-period simple moving average on Close.
* ATR: Average True Range, default 14-period. Configured via `config/strategy.yaml` (`atr_length`).

## Parameters (source of truth: `config/strategy.yaml`)

* `atr_length`: 14
* `atr_mult`: 3.0 (ATR multiplier for trailing stop)
* `slope_lookback`: 20 (lookback for MA150 slope)
* `entry_lookback`: 20 (breakout lookback)
* `atr_pct_high`: 0.04 (ATR/close threshold for RANGE_HIGH_VOL block)
* `slope_min`: 0.0 (minimum absolute slope for trend detection)

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
