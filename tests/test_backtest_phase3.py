"""
Deterministic Phase 3 backtest + metrics tests.

Tests that BacktestAgent's strategy-based backtest produces correct,
deterministic artifacts from synthetic strategy signals.
"""

import numpy as np
import pandas as pd
import pytest

import importlib
import inspect
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_mod = importlib.import_module("agents.backtest_agent")
REQUIRED_PNL_COLS = _mod.REQUIRED_PNL_COLS
REQUIRED_TRADES_COLS = _mod.REQUIRED_TRADES_COLS
REQUIRED_METRICS_KEYS = _mod.REQUIRED_METRICS_KEYS
_STUB_ML_METRICS = _mod._STUB_ML_METRICS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _make_strategy_signals(n: int, entries=None, exits=None):
    """Build a synthetic strategy_signals DataFrame.

    entries / exits: lists of integer indices where entry/exit occur.
    """
    idx = _make_dates(n)
    entry_signal = np.zeros(n, dtype=bool)
    exit_signal = np.zeros(n, dtype=bool)
    position = np.zeros(n, dtype=np.int64)
    regime_ok = np.ones(n, dtype=bool)
    range_high_vol = np.zeros(n, dtype=bool)
    ma150_trend_ok = np.ones(n, dtype=bool)
    stop_price = np.full(n, np.nan)

    in_pos = False
    for i in range(n):
        if entries and i in entries and not in_pos:
            entry_signal[i] = True
            in_pos = True
        if exits and i in exits and in_pos:
            exit_signal[i] = True
            in_pos = False
        position[i] = 1 if in_pos else 0

    return pd.DataFrame({
        "regime_ok": regime_ok,
        "range_high_vol": range_high_vol,
        "ma150_trend_ok": ma150_trend_ok,
        "entry_signal": entry_signal,
        "exit_signal": exit_signal,
        "stop_price": stop_price,
        "position": position,
    }, index=idx)


def _make_close(n: int, start=100.0, step=1.0):
    """Linearly increasing close prices."""
    idx = _make_dates(n)
    return pd.Series(
        [start + i * step for i in range(n)],
        index=idx,
    )


# Minimal stub to call strategy methods without full agent infra
class _CostStub:
    commission_pct = 0.001
    spread_bps = 2.0
    slippage_bps = 3.0
    execution_assumption = "eod"


class _ConfigStub:
    backtest = _CostStub()


class _AgentStub:
    """Minimal stub exposing BacktestAgent strategy methods."""
    def __init__(self):
        self.config = _ConfigStub()

    # Bind methods from BacktestAgent
    _get_one_way_cost = _mod.BacktestAgent._get_one_way_cost
    _build_strategy_trades = _mod.BacktestAgent._build_strategy_trades
    _build_strategy_pnl = _mod.BacktestAgent._build_strategy_pnl
    _calculate_strategy_metrics = _mod.BacktestAgent._calculate_strategy_metrics


# ---------------------------------------------------------------------------
# Tests: Trade building
# ---------------------------------------------------------------------------


class TestBuildStrategyTrades:
    """_build_strategy_trades must produce correct, deterministic trades."""

    def setup_method(self):
        self.agent = _AgentStub()

    def test_single_trade_correct(self):
        """One entry + one exit = one trade with correct values."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5], exits=[10])
        close = _make_close(n, start=100.0, step=1.0)

        trades = self.agent._build_strategy_trades(signals, close)

        assert len(trades) == 1
        t = trades.iloc[0]
        assert t['entry_price'] == 105.0  # close at index 5
        assert t['exit_price'] == 110.0   # close at index 10
        assert t['pnl'] == 5.0

        # Gross return = 110/105 - 1 = ~0.04762
        # Round-trip cost = 2 * 0.0015 = 0.003
        expected_ret = (110.0 / 105.0) - 1 - 0.003
        assert abs(t['return'] - expected_ret) < 1e-10

    def test_no_trades_when_no_signals(self):
        """No entry signals → empty trades DataFrame."""
        n = 20
        signals = _make_strategy_signals(n)
        close = _make_close(n)

        trades = self.agent._build_strategy_trades(signals, close)
        assert len(trades) == 0
        assert list(trades.columns) == REQUIRED_TRADES_COLS

    def test_open_trade_not_included(self):
        """Entry without exit → not in trades (open position)."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5])
        close = _make_close(n)

        trades = self.agent._build_strategy_trades(signals, close)
        assert len(trades) == 0

    def test_multiple_trades(self):
        """Two complete trades."""
        n = 30
        signals = _make_strategy_signals(
            n, entries=[3, 15], exits=[8, 20]
        )
        close = _make_close(n, start=100.0, step=0.5)

        trades = self.agent._build_strategy_trades(signals, close)
        assert len(trades) == 2
        assert trades.iloc[0]['entry_price'] == 101.5
        assert trades.iloc[0]['exit_price'] == 104.0
        assert trades.iloc[1]['entry_price'] == 107.5
        assert trades.iloc[1]['exit_price'] == 110.0

    def test_trades_schema(self):
        """Trades must have the locked column schema."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5], exits=[10])
        close = _make_close(n)

        trades = self.agent._build_strategy_trades(signals, close)
        assert list(trades.columns) == REQUIRED_TRADES_COLS

    def test_holding_days(self):
        """holding_days must be calendar days between entry and exit."""
        n = 20
        signals = _make_strategy_signals(n, entries=[0], exits=[5])
        close = _make_close(n)

        trades = self.agent._build_strategy_trades(signals, close)
        # Business days 0-5 spans a weekend, so calendar days > 5
        assert trades.iloc[0]['holding_days'] >= 5


# ---------------------------------------------------------------------------
# Tests: PnL series
# ---------------------------------------------------------------------------


class TestBuildStrategyPnl:
    """_build_strategy_pnl must produce correct daily returns."""

    def setup_method(self):
        self.agent = _AgentStub()

    def test_pnl_schema(self):
        """PnL series must have the locked column schema."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5], exits=[10])
        close = _make_close(n)

        pnl = self.agent._build_strategy_pnl(signals, close)
        assert list(pnl.columns) == REQUIRED_PNL_COLS

    def test_no_position_no_return(self):
        """When never in position, daily returns should be <= 0 (costs only at 0 signal days)."""
        n = 20
        signals = _make_strategy_signals(n)
        close = _make_close(n)

        pnl = self.agent._build_strategy_pnl(signals, close)
        # No entry/exit costs, no position returns
        assert (pnl['daily_return'] == 0).all()
        assert (pnl['equity_curve'] == 1.0).all()

    def test_equity_starts_at_one(self):
        """Equity curve must start at 1.0."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5], exits=[10])
        close = _make_close(n)

        pnl = self.agent._build_strategy_pnl(signals, close)
        assert pnl['equity_curve'].iloc[0] == 1.0

    def test_cost_deducted_at_entry_and_exit(self):
        """Entry and exit days should have cost deductions."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5], exits=[10])
        close = _make_close(n, start=100.0, step=0.0)  # flat prices

        pnl = self.agent._build_strategy_pnl(signals, close)
        one_way = 0.0015  # commission + spread + slippage

        # Entry day: position[4]=0, so no market return, minus entry cost
        assert abs(pnl['daily_return'].iloc[5] - (-one_way)) < 1e-10

        # Exit day: position[9]=1, market return = 0 (flat), minus exit cost
        assert abs(pnl['daily_return'].iloc[10] - (-one_way)) < 1e-10

    def test_position_column_matches_signals(self):
        """PnL position column must match strategy signals position."""
        n = 20
        signals = _make_strategy_signals(n, entries=[5], exits=[10])
        close = _make_close(n)

        pnl = self.agent._build_strategy_pnl(signals, close)
        np.testing.assert_array_equal(
            pnl['position'].values,
            signals['position'].values,
        )


# ---------------------------------------------------------------------------
# Tests: Metrics
# ---------------------------------------------------------------------------


class TestStrategyMetrics:
    """_calculate_strategy_metrics must produce correct, complete metrics."""

    def setup_method(self):
        self.agent = _AgentStub()

    def _compute(self, n=50, entries=None, exits=None):
        if entries is None:
            entries = [10]
        if exits is None:
            exits = [20]
        signals = _make_strategy_signals(n, entries=entries, exits=exits)
        close = _make_close(n, start=100.0, step=1.0)
        trades = self.agent._build_strategy_trades(signals, close)
        pnl = self.agent._build_strategy_pnl(signals, close)
        ml_metrics = {'legacy_ml': {'auc': 0.5, 'brier_score': 0.5,
                                     'base_rate': 0.1, 'total_samples': 10}}
        return self.agent._calculate_strategy_metrics(
            signals, close, trades, pnl, ml_metrics
        )

    def test_all_required_keys_present(self):
        """metrics dict must contain all REQUIRED_METRICS_KEYS."""
        metrics = self._compute()
        for key in REQUIRED_METRICS_KEYS:
            assert key in metrics, f"Missing key: {key}"

    def test_legacy_ml_nested(self):
        """metrics['legacy_ml'] must contain ML metrics when provided."""
        metrics = self._compute()
        assert 'auc' in metrics['legacy_ml']
        assert 'brier_score' in metrics['legacy_ml']

    def test_single_winning_trade(self):
        """One winning trade with known prices → verify metrics."""
        metrics = self._compute(n=50, entries=[10], exits=[20])

        assert metrics['num_trades'] == 1
        assert metrics['win_rate'] == 1.0  # Positive return

        # entry=110, exit=120, gross_return = 10/110 ≈ 0.0909
        expected_gross = (120.0 / 110.0) - 1
        expected_net = expected_gross - 0.003
        assert abs(metrics['avg_trade_return'] - expected_net) < 1e-6
        assert abs(metrics['EV_per_trade'] - expected_net) < 1e-6

    def test_exposure_time(self):
        """exposure_time_pct must match days in position."""
        n = 50
        entries = [10]
        exits = [20]
        signals = _make_strategy_signals(n, entries=entries, exits=exits)
        # Position is 1 for indices 10-19 (10 days), 0 elsewhere
        expected_pct = signals['position'].sum() / n * 100

        metrics = self._compute(n=n, entries=entries, exits=exits)
        assert abs(metrics['exposure_time_pct'] - expected_pct) < 0.01

    def test_no_trades_metrics(self):
        """No trades → safe defaults, no division errors."""
        metrics = self._compute(n=50, entries=[], exits=[])
        assert metrics['num_trades'] == 0
        assert metrics['win_rate'] == 0.0
        assert metrics['total_return'] == 0.0
        assert metrics['max_drawdown'] == 0.0
        assert metrics['profit_factor'] == 0.0

    def test_regime_diagnostics(self):
        """Regime diagnostics must reflect signal data."""
        metrics = self._compute(n=50, entries=[10], exits=[20])
        # Our synthetic signals have all regime_ok=True, range_high_vol=False
        assert metrics['days_regime_ok_pct'] == 100.0
        assert metrics['days_range_high_vol_pct'] == 0.0
        assert metrics['breakout_entry_count'] == 1

    def test_costs(self):
        """total_costs must equal num_trades * round_trip."""
        metrics = self._compute(n=50, entries=[10], exits=[20])
        assert abs(metrics['total_costs'] - 0.003) < 1e-10
        assert abs(metrics['costs_per_trade_avg'] - 0.003) < 1e-10

    def test_deterministic(self):
        """Same inputs must produce identical metrics."""
        m1 = self._compute(n=50, entries=[10], exits=[20])
        m2 = self._compute(n=50, entries=[10], exits=[20])
        for key in REQUIRED_METRICS_KEYS:
            assert m1[key] == m2[key], f"Non-deterministic: {key}"


# ---------------------------------------------------------------------------
# Tests: Schema locks
# ---------------------------------------------------------------------------


class TestSchemaLocks:
    """Schema lock constants must match Phase 3 spec."""

    def test_pnl_cols(self):
        assert REQUIRED_PNL_COLS == [
            "date", "equity_curve", "daily_return", "position"
        ]

    def test_trades_cols(self):
        assert REQUIRED_TRADES_COLS == [
            "entry_date", "entry_price", "exit_date", "exit_price",
            "pnl", "return", "holding_days",
        ]

    def test_metrics_keys_include_phase3(self):
        assert "total_return" in REQUIRED_METRICS_KEYS
        assert "cagr" in REQUIRED_METRICS_KEYS
        assert "sharpe" in REQUIRED_METRICS_KEYS
        assert "days_regime_ok_pct" in REQUIRED_METRICS_KEYS
        assert "total_costs" in REQUIRED_METRICS_KEYS


# ---------------------------------------------------------------------------
# Tests: Phase 3 hardening — ML regression prevention
# ---------------------------------------------------------------------------


class TestBacktestModeGuardrails:
    """Verify signals_only is default and ML code is unreachable in that mode."""

    def test_default_mode_is_signals_only(self):
        """BacktestConfig.backtest_mode must default to 'signals_only'."""
        _cfg = importlib.import_module("config")
        cfg = _cfg.BacktestConfig()
        assert cfg.backtest_mode == "signals_only"

    def test_signals_only_no_module_level_sklearn_import(self):
        """backtest_agent.py must NOT import sklearn/pickle at module level.

        Module-level imports would force sklearn into sys.modules for ALL
        modes, defeating the purpose of the signals_only gate.
        """
        source = inspect.getsource(_mod)
        # Check top-level imports (before class def) don't contain sklearn/pickle
        lines_before_class = source.split("class BacktestAgent")[0]
        for line in lines_before_class.splitlines():
            stripped = line.strip()
            # Skip comments and docstrings
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            assert "import pickle" not in stripped, \
                "Module-level 'import pickle' found — must be lazy inside legacy_ml"
            assert "from sklearn" not in stripped, \
                "Module-level 'from sklearn' found — must be lazy inside legacy_ml"
            assert "import sklearn" not in stripped, \
                "Module-level 'import sklearn' found — must be lazy inside legacy_ml"

    def test_signals_only_method_exists(self):
        """BacktestAgent must have _run_signals_only method."""
        assert hasattr(_mod.BacktestAgent, '_run_signals_only')

    def test_legacy_ml_method_exists(self):
        """BacktestAgent must have _run_legacy_ml method."""
        assert hasattr(_mod.BacktestAgent, '_run_legacy_ml')

    def test_run_dispatches_on_mode(self):
        """run() must read backtest_mode and dispatch."""
        source = inspect.getsource(_mod.BacktestAgent.run)
        assert "backtest_mode" in source
        assert "_run_signals_only" in source
        assert "_run_legacy_ml" in source

    def test_stub_ml_metrics_has_required_keys(self):
        """_STUB_ML_METRICS must provide numeric defaults for dashboard."""
        legacy = _STUB_ML_METRICS['legacy_ml']
        assert 'auc' in legacy
        assert 'brier_score' in legacy
        assert 'base_rate' in legacy
        assert 'total_samples' in legacy
        # Must be numeric (not string "N/A") so formatters don't crash
        assert isinstance(legacy['auc'], (int, float))
        assert isinstance(legacy['brier_score'], (int, float))

    def test_metrics_schema_phase3_top_level_keys_present(self):
        """Phase 3 top-level metrics must be present with stub ML metrics."""
        agent = _AgentStub()
        n = 50
        signals = _make_strategy_signals(n, entries=[10], exits=[20])
        close = _make_close(n, start=100.0, step=1.0)
        trades = agent._build_strategy_trades(signals, close)
        pnl = agent._build_strategy_pnl(signals, close)

        # Use stub (signals_only) ML metrics
        metrics = agent._calculate_strategy_metrics(
            signals, close, trades, pnl, _STUB_ML_METRICS
        )

        for key in REQUIRED_METRICS_KEYS:
            assert key in metrics, f"Missing Phase 3 key with stub ML: {key}"

        # legacy_ml must be the stub
        assert metrics['legacy_ml'] == _STUB_ML_METRICS['legacy_ml']


# ---------------------------------------------------------------------------
# Tests: Legacy ML stub isolation (STEP 3)
# ---------------------------------------------------------------------------


class TestLegacyMlStubIsolation:
    """Verify legacy_ml stubs are isolated under BacktestAgent/legacy_ml/
    and are optional when emit_legacy_stubs=False.
    """

    def setup_method(self):
        self.agent = _AgentStub()

    # -- Test 1: Default emits stubs under legacy_ml/, NOT at top level --

    def test_default_stubs_path_is_legacy_ml_subfolder(self):
        """_run_signals_only must save stubs to legacy_ml/ sub-path."""
        source = inspect.getsource(_mod.BacktestAgent._run_signals_only)
        # Must create legacy_ml subfolder
        assert "legacy_ml" in source
        assert "os.makedirs" in source
        # Stubs saved to legacy_ml/ paths
        assert "legacy_ml/predictions_oos.parquet" in source
        assert "legacy_ml/sanity_tests.json" in source

    def test_stubs_not_at_top_level_in_signals_only(self):
        """_run_signals_only must NOT save predictions_oos or sanity_tests
        at agent top level (only in legacy_ml/ subfolder).
        """
        source = inspect.getsource(_mod.BacktestAgent._run_signals_only)
        # Find all save_artifact calls
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if "save_artifact" in stripped and "predictions_oos" in stripped:
                # Must reference legacy_ml/ path
                assert "legacy_ml/" in stripped, (
                    f"predictions_oos saved outside legacy_ml/: {stripped}"
                )
            if "save_artifact" in stripped and "sanity_tests" in stripped:
                assert "legacy_ml/" in stripped, (
                    f"sanity_tests saved outside legacy_ml/: {stripped}"
                )

    # -- Test 2: emit_legacy_stubs=False → no legacy_ml artifacts --

    def test_emit_stubs_false_skips_legacy_ml_creation(self):
        """When emit_legacy_stubs=False, no legacy_ml dir/artifacts are created.

        Verified by checking that stubs are gated behind emit_stubs flag.
        """
        source = inspect.getsource(_mod.BacktestAgent._run_signals_only)
        # The emit_stubs flag must gate stub creation
        assert "emit_legacy_stubs" in source
        assert "emit_stubs" in source
        # os.makedirs for legacy_ml must be inside the emit_stubs block
        assert "if emit_stubs:" in source

    def test_emit_stubs_false_metrics_no_legacy_ml_key(self):
        """With empty ml_metrics (emit_stubs=False), metrics has no legacy_ml."""
        n = 50
        signals = _make_strategy_signals(n, entries=[10], exits=[20])
        close = _make_close(n, start=100.0, step=1.0)
        trades = self.agent._build_strategy_trades(signals, close)
        pnl = self.agent._build_strategy_pnl(signals, close)

        # Simulate emit_legacy_stubs=False: pass empty ml_metrics
        metrics = self.agent._calculate_strategy_metrics(
            signals, close, trades, pnl, {}
        )

        assert 'legacy_ml' not in metrics

    # -- Test 3: Phase 3 keys always at top level; legacy_ml optional --

    def test_phase3_keys_present_with_stubs(self):
        """Phase 3 required keys must be at top level when stubs are emitted."""
        n = 50
        signals = _make_strategy_signals(n, entries=[10], exits=[20])
        close = _make_close(n, start=100.0, step=1.0)
        trades = self.agent._build_strategy_trades(signals, close)
        pnl = self.agent._build_strategy_pnl(signals, close)

        metrics = self.agent._calculate_strategy_metrics(
            signals, close, trades, pnl, _STUB_ML_METRICS
        )

        for key in REQUIRED_METRICS_KEYS:
            assert key in metrics, f"Missing Phase 3 key: {key}"
        # legacy_ml is an extra nested key, not in REQUIRED_METRICS_KEYS
        assert 'legacy_ml' in metrics

    def test_phase3_keys_present_without_stubs(self):
        """Phase 3 required keys must be at top level even without stubs."""
        n = 50
        signals = _make_strategy_signals(n, entries=[10], exits=[20])
        close = _make_close(n, start=100.0, step=1.0)
        trades = self.agent._build_strategy_trades(signals, close)
        pnl = self.agent._build_strategy_pnl(signals, close)

        metrics = self.agent._calculate_strategy_metrics(
            signals, close, trades, pnl, {}
        )

        for key in REQUIRED_METRICS_KEYS:
            assert key in metrics, f"Missing Phase 3 key without stubs: {key}"

    def test_legacy_ml_not_in_required_metrics_keys(self):
        """'legacy_ml' and 'overall' must NOT be in REQUIRED_METRICS_KEYS."""
        assert 'legacy_ml' not in REQUIRED_METRICS_KEYS
        assert 'overall' not in REQUIRED_METRICS_KEYS

    # -- Test 4: validate_run does not require legacy_ml --

    def test_validate_run_required_artifacts_no_legacy_ml(self):
        """REQUIRED_ARTIFACTS['BacktestAgent'] must NOT contain legacy ML files."""
        _vr = importlib.import_module("validate_run")
        bt_artifacts = _vr.REQUIRED_ARTIFACTS["BacktestAgent"]

        assert "predictions_oos.parquet" not in bt_artifacts
        assert "sanity_tests.json" not in bt_artifacts
        # Phase 3 artifacts must be present
        assert "metrics.json" in bt_artifacts
        assert "trades.parquet" in bt_artifacts
        assert "pnl_series.parquet" in bt_artifacts
        assert "costs_assumptions.json" in bt_artifacts

    def test_validate_run_metrics_fields_no_overall(self):
        """REQUIRED_METRICS_FIELDS must not reference 'overall' or 'legacy_ml'."""
        _vr = importlib.import_module("validate_run")
        for field in _vr.REQUIRED_METRICS_FIELDS:
            assert "overall" not in field.lower(), f"Unexpected 'overall' in: {field}"
            assert "legacy_ml" not in field.lower(), f"Unexpected 'legacy_ml' in: {field}"

    def test_emit_legacy_stubs_config_default(self):
        """BacktestConfig.emit_legacy_stubs must default to True."""
        _cfg = importlib.import_module("config")
        cfg = _cfg.BacktestConfig()
        assert cfg.emit_legacy_stubs is True
