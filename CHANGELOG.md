# Changelog

## v0.4.1-phase4-hardening (2026-02-20)

- Docs: document Phase 4 risk sizing outputs in README (config table, artifact paths, 7 trades columns, 9 metric keys, run/validate commands)
- Docs: update BacktestAgent description and artifact tree for `signals_only` mode; bump version to 0.4.0
- Tests: add `tests/test_phase4_artifact_schema.py` — 5 static schema checks ensuring Phase 4 columns/metrics stay consistent across `backtest_agent.py` and `validate_run.py`
- CI: PR pytest workflow verified correct (no changes needed)

## v0.4.0-phase4-risk (2026-02-20)

- Position sizing: R-multiple model via `_build_sized_backtest()` in `signals_only` mode
- Config: `capital_base`, `max_leverage`, `max_position_pct`, `min_stop_pct`, `max_stop_pct` in `BacktestConfig`; `risk_per_trade` in `StrategyConfig`
- Guardrails: skip trade if stop_pct outside bounds or stop_distance <= 0; cap by `max_position_pct` and `max_leverage`
- Artifacts: `risk_explain.json` audit trail; 7 new `trades.parquet` columns; 9 new `metrics.json` keys
- Reports: dashboard HTML + JSON include Phase 4 risk metrics
- Validation: `validate_run.py` checks `risk_explain.json` and all 9 Phase 4 metric fields
- Legacy ML: stub `risk_explain.json` + zeroed Phase 4 metrics emitted for backward compat
