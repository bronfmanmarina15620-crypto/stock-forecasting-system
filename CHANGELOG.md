# Changelog

## Unreleased

- CI: add smoke-run job (`scripts/ci_smoke_run.sh`) + `validate_run` gate on PRs
- CLI: `run.py` adds `--lookback-days` and `--min-bars` optional flags
- Repo: add LICENSE, SECURITY.md, CODE_OF_CONDUCT.md, CONTRIBUTING.md
- Repo: add PR/issue templates, Dependabot, release workflow scaffold
- Repo: harden `.gitignore` (`.env`, `secrets.*`)

## v0.7.0-phase8-drift (2026-02-21)

- New agent: `DriftAgent` computes z-score drift metrics from shadow run history (`drift_summary.json`, `drift_timeseries.parquet`)
- New module: `analytics/drift_metrics.py` — pure, stateless drift functions (z-score, decision distribution, history discovery)
- Coverage telemetry: `total_runs_scanned`, `eligible_runs_found`, `runs_used_in_window`, `runs_excluded`, `excluded_reasons` with bounded debug samples
- `drift_reason_summary`: human-readable one-liner in drift_summary.json (OK / WARN with z-scores / INSUFFICIENT_HISTORY / ERROR)
- Dashboard: drift monitoring card in HTML + JSON (`drift` key in `final_report.json`)
- Validation: `validate_run.py` Step 9 — optional drift checks (schema, coverage identities, sample bounds, reason summary)
- Telegram: shadow success message includes `DRIFT=<status>/<flag> COVERAGE=<used>/<eligible> SCANNED=<scanned> REASON=<summary>`
- Fail-safe: DriftAgent never crashes the pipeline; emits degraded output on error

## v0.4.2-phase5-volatility-regime (2026-02-21)

- New agent: `VolatilityRegimeAgent` classifies daily volatility as QUIET/NORMAL/EXPANDING/EXTREME via ATR(14)/ATR(100) ratio + slope
- Integration: EXTREME regime blocks ENTER in `DecisionRiskAgent`; regime size multiplier attached to decision
- Backtest: per-regime trade breakdown (`regime_breakdown.json`) with win rate, avg return, avg R-multiple
- Dashboard: volatility regime card + regime breakdown table in HTML and JSON reports
- Hardening: `_validate_regime_latest()` invariant check, schema guards, defensive JSON parse fallback

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
