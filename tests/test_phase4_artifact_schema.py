"""Static schema guard: Phase 4 constants match across modules.

Purely deterministic – imports only; never runs the pipeline.
"""

import importlib

_bt = importlib.import_module("agents.backtest_agent")
_vr = importlib.import_module("validate_run")

PHASE4_TRADES_COLS = _bt.PHASE4_TRADES_COLS
PHASE4_METRICS_KEYS = _bt.PHASE4_METRICS_KEYS
REQUIRED_METRICS_FIELDS = _vr.REQUIRED_METRICS_FIELDS

# ── expected values (update here if spec changes) ──────────────────

EXPECTED_TRADES_COLS = [
    "shares", "notional", "exposure_pct", "stop_distance",
    "stop_pct", "risk_budget", "r_multiple",
]

EXPECTED_METRICS_KEYS = [
    "avg_exposure_pct", "max_exposure_pct",
    "avg_r_multiple", "median_r_multiple",
    "worst_r_multiple", "best_r_multiple",
    "pct_trades_skipped_due_to_stop_bounds",
    "pct_trades_capped_by_max_position",
    "realized_risk_per_trade_avg",
]


class TestPhase4TradesSchema:
    def test_trades_cols_match_spec(self):
        assert PHASE4_TRADES_COLS == EXPECTED_TRADES_COLS

    def test_trades_cols_count(self):
        assert len(PHASE4_TRADES_COLS) == 7


class TestPhase4MetricsSchema:
    def test_metrics_keys_match_spec(self):
        assert PHASE4_METRICS_KEYS == EXPECTED_METRICS_KEYS

    def test_metrics_keys_count(self):
        assert len(PHASE4_METRICS_KEYS) == 9


class TestValidateRunIncludesPhase4:
    def test_all_phase4_metrics_in_required_fields(self):
        missing = set(EXPECTED_METRICS_KEYS) - set(REQUIRED_METRICS_FIELDS)
        assert missing == set(), f"validate_run.py missing Phase 4 keys: {missing}"
