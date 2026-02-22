# Strategy Contract: MA150 + ATR

## Indicators

* MA150: 150-period moving average on Close (as implemented).
* ATR: Average True Range (window as implemented).

## Core Rules (Contract-Level)

* Trend is defined relative to MA150 (exact rule is "as implemented" in strategy module).
* Entry eligibility, stop calculation, and "extended" classification must be deterministic.
* Strategy outputs must include:

  * eligibility / signal state
  * stop price (derived from ATR)
  * any distance-to-MA150 / extension metrics used

## No Strategy Proliferation

* This contract documents the single allowed strategy.
* Any new strategy requires an explicit design + invariants update.
