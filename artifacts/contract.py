"""
Artifact contract — single source of truth for required/optional artifacts,
JSON schemas, and decision enum validation.

Imported by:
  - validate_run.py (validation)
  - tests/test_validate_contract.py (unit tests)

This module defines WHAT must exist; validate_run.py defines HOW to check it.
"""

# ============================================================
# CRITICAL ARTIFACTS (must exist for a valid run)
# ============================================================

CRITICAL_ARTIFACTS: list[str] = [
    # Root-level
    "status.txt",
    "status.json",
    "config.json",
    "config_snapshot.yaml",
    "final_report.html",
    "final_report.json",
    "_meta.json",
    "run_summary.json",
    # BacktestAgent
    "BacktestAgent/trades.parquet",
    "BacktestAgent/pnl_series.parquet",
    "BacktestAgent/metrics.json",
    "BacktestAgent/costs_assumptions.json",
    "BacktestAgent/risk_explain.json",
    # DecisionRiskAgent
    "DecisionRiskAgent/signals.csv",
    "DecisionRiskAgent/abstain_stats.json",
    "DecisionRiskAgent/decision_action.json",
    "DecisionRiskAgent/decision_explain.json",
    # RobustnessAgent
    "RobustnessAgent/summary.json",
    "RobustnessAgent/monte_carlo.json",
    # DataAgent
    "DataAgent/data_snapshot.parquet",
    "DataAgent/snapshot_hash.txt",
]

# ============================================================
# OPTIONAL ARTIFACTS (allowed but not required)
# ============================================================

OPTIONAL_ARTIFACTS: list[str] = [
    # Edge validation
    "edge_summary.json",
    "edge_report.txt",
    # Shadow mode
    "ShadowMonitorAgent/shadow_metrics.json",
    "ShadowMonitorAgent/shadow_summary.json",
    # Drift
    "DriftAgent/drift_summary.json",
    # Legacy ML
    "BacktestAgent/legacy_ml/sanity_tests.json",
    "BacktestAgent/legacy_ml/predictions_oos.parquet",
    # Robustness extras
    "RobustnessAgent/walk_forward.json",
    "RobustnessAgent/sensitivity_map.json",
    "RobustnessAgent/exposure_decomposition.json",
    "RobustnessAgent/regime_contribution.json",
    "RobustnessAgent/capacity_test.json",
    # Agent outputs and logs
    "DataAgent/output.json",
    "DataAgent/bars_raw.parquet",
    "DataAgent/bars_adj.parquet",
    "DataAgent/quality_report.json",
    "FeatureAgent/output.json",
    "RegimeAgent/output.json",
    "BacktestAgent/output.json",
    "DecisionRiskAgent/output.json",
    "RobustnessAgent/output.json",
    "PortfolioAgent/output.json",
    "DashboardAgent/output.json",
    "MemoryLearningAgent/output.json",
]

# ============================================================
# CONTENT HASH TARGETS (JSON files that must embed content_hash_sha256)
# ============================================================

CONTENT_HASH_TARGETS: list[str] = [
    "BacktestAgent/metrics.json",
    "final_report.json",
    "DecisionRiskAgent/decision_action.json",
    "RobustnessAgent/summary.json",
    "RobustnessAgent/monte_carlo.json",
    "RobustnessAgent/walk_forward.json",
    "RobustnessAgent/sensitivity_map.json",
    "RobustnessAgent/exposure_decomposition.json",
    "RobustnessAgent/regime_contribution.json",
    "RobustnessAgent/capacity_test.json",
]

SHADOW_HASH_TARGETS: list[str] = [
    "ShadowMonitorAgent/shadow_metrics.json",
    "ShadowMonitorAgent/shadow_summary.json",
]

# ============================================================
# DECISION ENUM
# ============================================================

VALID_DECISIONS: frozenset[str] = frozenset({
    "ENTER",
    "ABSTAIN",
    "EXIT",
    "UNKNOWN",
})

# ============================================================
# JSON SCHEMAS (lightweight required-keys validation)
# ============================================================

# Each schema is a dict of {key_name: expected_type_or_None}.
# None means "any type, just check presence".

METRICS_REQUIRED_KEYS: list[str] = [
    "EV_per_trade",
    "max_drawdown",
    "win_rate",
    "avg_trades_per_month",
    "total_return",
    "cagr",
    "sharpe",
    "exposure_time_pct",
    "num_trades",
    "days_regime_ok_pct",
    "days_range_high_vol_pct",
    "avg_exposure_pct",
    "max_exposure_pct",
    "avg_r_multiple",
    "median_r_multiple",
    "worst_r_multiple",
    "best_r_multiple",
    "pct_trades_skipped_due_to_stop_bounds",
    "pct_trades_capped_by_max_position",
    "realized_risk_per_trade_avg",
]

ABSTAIN_STATS_REQUIRED_KEYS: list[str] = [
    "abstain_ratio",
    "enter_count",
    "abstain_count",
    "signals_per_month",
]

FINAL_REPORT_REQUIRED_KEYS: list[str] = [
    "ticker",
    "run_timestamp",
    "data",
    "backtest",
    "decision",
    "portfolio",
]

STATUS_JSON_REQUIRED_KEYS: list[str] = [
    "overall_status",
    "ticker",
    "timestamp",
    "stages",
    "integrity",
]

SUMMARY_REQUIRED_KEYS: list[str] = [
    "ticker",
    "run_id",
    "status",
    "created_utc",
    "git_sha",
    "decision",
]

# ============================================================
# PARITY COMPARISON TARGETS
# (files compared between runs for determinism verification)
# ============================================================

# JSON files compared via canonical normalization
PARITY_JSON_TARGETS: list[str] = [
    "BacktestAgent/metrics.json",
    "final_report.json",
    "DecisionRiskAgent/decision_action.json",
    "RobustnessAgent/summary.json",
    "RobustnessAgent/monte_carlo.json",
    "RobustnessAgent/walk_forward.json",
    "RobustnessAgent/sensitivity_map.json",
    "RobustnessAgent/exposure_decomposition.json",
    "RobustnessAgent/regime_contribution.json",
    "RobustnessAgent/capacity_test.json",
]

# Non-JSON files compared via raw SHA-256
PARITY_RAW_TARGETS: list[str] = [
    "DataAgent/data_snapshot.parquet",
]

# Files to ignore during parity comparison (known non-deterministic).
# final_report.html contains generation timestamps in the rendered HTML;
# the deterministic content is verified via final_report.json instead.
PARITY_IGNORE: list[str] = [
    "status.txt",
    "status.json",
    "run_summary.json",
    "_meta.json",
    "config.json",
    "config_snapshot.yaml",
    "final_report.html",
    "edge_summary.json",
    "edge_report.txt",
]
