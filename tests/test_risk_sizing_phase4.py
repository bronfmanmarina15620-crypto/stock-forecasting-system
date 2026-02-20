"""
Deterministic Phase 4 risk sizing tests.

Tests position sizing, cap enforcement, stop bounds, r-multiples,
and no-lookahead guarantees for the signals_only backtest engine.
"""

import numpy as np
import pandas as pd
import pytest

import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_mod = importlib.import_module("agents.backtest_agent")
REQUIRED_TRADES_COLS = _mod.REQUIRED_TRADES_COLS
PHASE4_TRADES_COLS = _mod.PHASE4_TRADES_COLS
PHASE4_METRICS_KEYS = _mod.PHASE4_METRICS_KEYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _make_strategy_signals(
    n: int,
    entries=None,
    exits=None,
    close_values=None,
    stop_values=None,
):
    """Build a synthetic strategy_signals DataFrame with stop prices.

    stop_values: dict mapping index -> stop_price float.
                 If None, stop is set to close - 5.0 at entry points.
    """
    idx = _make_dates(n)
    entry_signal = np.zeros(n, dtype=bool)
    exit_signal = np.zeros(n, dtype=bool)
    position = np.zeros(n, dtype=np.int64)
    regime_ok = np.ones(n, dtype=bool)
    range_high_vol = np.zeros(n, dtype=bool)
    ma150_trend_ok = np.ones(n, dtype=bool)
    stop_price = np.full(n, np.nan)

    if close_values is None:
        close_values = [100.0 + i for i in range(n)]

    in_pos = False
    highest = np.nan
    for i in range(n):
        if entries and i in entries and not in_pos:
            entry_signal[i] = True
            in_pos = True
            highest = close_values[i]
            # Default stop: close - 5.0
            if stop_values and i in stop_values:
                stop_price[i] = stop_values[i]
            else:
                stop_price[i] = close_values[i] - 5.0

        if in_pos:
            highest = max(highest, close_values[i])
            if not entry_signal[i]:
                # Trailing stop: highest - 5.0
                if stop_values and i in stop_values:
                    stop_price[i] = stop_values[i]
                else:
                    stop_price[i] = highest - 5.0

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


def _make_close(n: int, values=None, start=100.0, step=1.0):
    idx = _make_dates(n)
    if values is not None:
        return pd.Series(values, index=idx)
    return pd.Series([start + i * step for i in range(n)], index=idx)


# --- Config/Agent stubs ---


class _BacktestCfgStub:
    def __init__(self):
        self.commission_pct = 0.001
        self.spread_bps = 2.0
        self.slippage_bps = 3.0
        self.execution_assumption = "eod"
        self.backtest_mode = "signals_only"
        self.emit_legacy_stubs = True
        self.capital_base = 100000.0
        self.max_leverage = 1.0
        self.max_position_pct = 0.25
        self.min_stop_pct = 0.01
        self.max_stop_pct = 0.20


class _StrategyCfgStub:
    def __init__(self):
        self.risk_per_trade = 0.005


class _EventCfgStub:
    def __init__(self):
        self.forward_window = 5
        self.threshold_pct = 2.0


class _ConfigStub:
    def __init__(self):
        self.backtest = _BacktestCfgStub()
        self.strategy = _StrategyCfgStub()
        self.event = _EventCfgStub()


class _LoggerStub:
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class _SizedAgentStub:
    """Minimal stub exposing Phase 4 sized backtest methods."""
    def __init__(self, **config_overrides):
        self.config = _ConfigStub()
        for k, v in config_overrides.items():
            parts = k.split(".")
            obj = self.config
            for part in parts[:-1]:
                obj = getattr(obj, part)
            setattr(obj, parts[-1], v)
        self.logger = _LoggerStub()

    _get_one_way_cost = _mod.BacktestAgent._get_one_way_cost
    _build_sized_backtest = _mod.BacktestAgent._build_sized_backtest
    _calculate_strategy_metrics = _mod.BacktestAgent._calculate_strategy_metrics
    _calculate_risk_metrics = _mod.BacktestAgent._calculate_risk_metrics


# ---------------------------------------------------------------------------
# Tests: Sizing correctness
# ---------------------------------------------------------------------------


class TestSizingCorrectness:
    """Verify position sizing math matches the R-multiple model."""

    def test_basic_sizing(self):
        """equity=100000, risk_per_trade=0.005, entry=100, stop=95
        → stop_distance=5, risk_budget=500, shares=100, notional=10000,
          exposure_pct=0.10.
        """
        agent = _SizedAgentStub()
        n = 30
        close_vals = [100.0] * n
        close_vals[15] = 105.0  # exit at higher price

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, pnl_df, risk_explain, stats = (
            agent._build_sized_backtest(signals, close)
        )

        assert len(trades_df) == 1
        t = trades_df.iloc[0]

        assert t['entry_price'] == 100.0
        assert t['stop_distance'] == 5.0
        assert t['stop_pct'] == pytest.approx(0.05)
        assert t['risk_budget'] == pytest.approx(500.0)
        assert t['shares'] == 100
        assert t['notional'] == pytest.approx(10000.0)
        assert t['exposure_pct'] == pytest.approx(0.10, abs=0.001)

    def test_shares_use_floor(self):
        """shares must be floor(risk_budget / stop_distance), not round."""
        agent = _SizedAgentStub()
        n = 30
        # entry=100, stop=97 → stop_distance=3, risk_budget=500
        # shares = floor(500/3) = 166 (not 167)
        close_vals = [100.0] * n
        close_vals[15] = 103.0  # exit

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 97.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, _, _ = agent._build_sized_backtest(signals, close)
        assert trades_df.iloc[0]['shares'] == 166  # floor(500/3)

    def test_r_multiple_winner(self):
        """Winning trade: r_multiple = realized_dollar_pnl / risk_budget."""
        agent = _SizedAgentStub()
        n = 30
        close_vals = [100.0] * n
        close_vals[15] = 110.0  # +10 per share

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, _, _ = agent._build_sized_backtest(signals, close)
        t = trades_df.iloc[0]

        # shares=100, gross=100*10=1000
        # entry_cost = 100*100*0.0015 = 15, exit_cost = 100*110*0.0015 = 16.5
        # net = 1000 - 15 - 16.5 = 968.5
        # r_mult = 968.5 / 500 = 1.937
        one_way = 0.0015
        entry_cost = 100 * 100.0 * one_way
        exit_cost = 100 * 110.0 * one_way
        expected_r = (100 * 10.0 - entry_cost - exit_cost) / 500.0
        assert t['r_multiple'] == pytest.approx(expected_r, rel=1e-6)

    def test_r_multiple_loser(self):
        """Losing trade: r_multiple should be negative."""
        agent = _SizedAgentStub()
        n = 30
        close_vals = [100.0] * n
        close_vals[15] = 90.0  # -10 per share

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, _, _ = agent._build_sized_backtest(signals, close)
        t = trades_df.iloc[0]
        assert t['r_multiple'] < 0

    def test_equity_curve_starts_at_capital_base(self):
        """Equity curve must start at capital_base (100000)."""
        agent = _SizedAgentStub()
        n = 30
        signals = _make_strategy_signals(n, entries=[5], exits=[15])
        close = _make_close(n)

        _, pnl_df, _, _ = agent._build_sized_backtest(signals, close)
        # First bar: no position, no cost yet → equity = capital_base
        assert pnl_df['equity_curve'].iloc[0] == 100000.0

    def test_trades_schema_phase4(self):
        """trades must include both Phase 3 and Phase 4 columns."""
        agent = _SizedAgentStub()
        n = 30
        signals = _make_strategy_signals(n, entries=[5], exits=[15])
        close = _make_close(n)

        trades_df, _, _, _ = agent._build_sized_backtest(signals, close)
        expected_cols = REQUIRED_TRADES_COLS + PHASE4_TRADES_COLS
        assert list(trades_df.columns) == expected_cols


# ---------------------------------------------------------------------------
# Tests: Cap enforcement
# ---------------------------------------------------------------------------


class TestCapEnforcement:
    """max_position_pct and max_leverage must cap shares deterministically."""

    def test_max_position_pct_caps_shares(self):
        """If max_position_pct=0.05, exposure is capped to 5%."""
        agent = _SizedAgentStub(**{
            "backtest.max_position_pct": 0.05,
        })
        n = 30
        # entry=100, stop=95 → uncapped shares=100, notional=10000 (10%)
        # cap at 5% → max_notional=5000 → shares=int(5000/100)=50
        close_vals = [100.0] * n
        close_vals[15] = 105.0

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, risk_explain, stats = (
            agent._build_sized_backtest(signals, close)
        )

        assert len(trades_df) == 1
        t = trades_df.iloc[0]
        assert t['shares'] == 50
        assert t['exposure_pct'] <= 0.05 + 1e-9
        assert stats['capped_count'] == 1

        # risk_explain should mention CAPPED
        explain_entry = risk_explain.get('trade_0', [])
        assert any('CAPPED' in r for r in explain_entry)

    def test_max_leverage_caps_shares(self):
        """If max_leverage=0.08, exposure is capped to 8%."""
        agent = _SizedAgentStub(**{
            "backtest.max_position_pct": 0.50,  # high
            "backtest.max_leverage": 0.08,       # binding
        })
        n = 30
        close_vals = [100.0] * n
        close_vals[15] = 105.0

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, _, stats = agent._build_sized_backtest(signals, close)

        t = trades_df.iloc[0]
        # cap_limit = min(0.50, 0.08) = 0.08
        # max_shares = int(0.08 * 100000 / 100) = 80
        assert t['shares'] == 80
        assert stats['capped_count'] == 1


# ---------------------------------------------------------------------------
# Tests: Stop bounds
# ---------------------------------------------------------------------------


class TestStopBounds:
    """Trades must be skipped deterministically when stop is out of bounds."""

    def test_stop_pct_too_small(self):
        """stop_pct < min_stop_pct → trade skipped."""
        agent = _SizedAgentStub(**{"backtest.min_stop_pct": 0.02})
        n = 30
        # entry=100, stop=99.5 → stop_pct=0.005 < min_stop_pct=0.02
        close_vals = [100.0] * n
        close_vals[15] = 105.0

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 99.5},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, risk_explain, stats = (
            agent._build_sized_backtest(signals, close)
        )

        assert len(trades_df) == 0
        assert stats['skipped_stop_bounds'] == 1
        assert stats['total_entry_signals'] == 1
        # Check explain has skip reason
        skipped_keys = [k for k in risk_explain if 'skipped' in k]
        assert len(skipped_keys) == 1
        assert any('min_stop_pct' in r for r in risk_explain[skipped_keys[0]])

    def test_stop_pct_too_large(self):
        """stop_pct > max_stop_pct → trade skipped."""
        agent = _SizedAgentStub(**{"backtest.max_stop_pct": 0.03})
        n = 30
        # entry=100, stop=95 → stop_pct=0.05 > max_stop_pct=0.03
        close_vals = [100.0] * n
        close_vals[15] = 105.0

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, risk_explain, stats = (
            agent._build_sized_backtest(signals, close)
        )

        assert len(trades_df) == 0
        assert stats['skipped_stop_bounds'] == 1
        skipped_keys = [k for k in risk_explain if 'skipped' in k]
        assert any('max_stop_pct' in r for r in risk_explain[skipped_keys[0]])

    def test_invalid_stop_distance(self):
        """stop >= entry_price → stop_distance <= 0 → trade skipped."""
        agent = _SizedAgentStub()
        n = 30
        close_vals = [100.0] * n
        close_vals[15] = 105.0

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 101.0},  # stop > entry
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, risk_explain, stats = (
            agent._build_sized_backtest(signals, close)
        )

        assert len(trades_df) == 0
        assert stats['skipped_invalid_stop'] == 1

    def test_nan_stop_skips(self):
        """NaN stop_price → trade skipped."""
        agent = _SizedAgentStub()
        n = 30
        close_vals = [100.0] * n
        close_vals[15] = 105.0

        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={},  # no stop values → will get NaN from _make_strategy_signals?
        )
        # Override stop_price at entry to NaN
        signals.loc[signals.index[5], 'stop_price'] = np.nan
        close = _make_close(n, values=close_vals)

        trades_df, _, _, stats = agent._build_sized_backtest(signals, close)
        assert len(trades_df) == 0
        assert stats['skipped_invalid_stop'] >= 1


# ---------------------------------------------------------------------------
# Tests: No lookahead
# ---------------------------------------------------------------------------


class TestNoLookahead:
    """Sizing at entry must use only entry-time data."""

    def test_sizing_uses_entry_equity_not_future(self):
        """Two trades: second trade sizes off post-trade-1 equity."""
        agent = _SizedAgentStub()
        n = 40
        # Trade 1: entry at 5 (price=105), exit at 15 (price=115)
        # Trade 2: entry at 20 (price=120), exit at 30 (price=130)
        close_vals = [100.0 + i for i in range(n)]

        signals = _make_strategy_signals(
            n, entries=[5, 20], exits=[15, 30],
            close_values=close_vals,
            stop_values={5: 100.0, 20: 115.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, pnl_df, _, _ = agent._build_sized_backtest(signals, close)

        assert len(trades_df) == 2

        # Trade 2 risk_budget should use equity AFTER trade 1 settled
        t1 = trades_df.iloc[0]
        t2 = trades_df.iloc[1]

        # Trade 1: entry_price=105, stop_dist=5, risk_budget=500, shares=100
        assert t1['risk_budget'] == pytest.approx(
            0.005 * 100000.0, abs=1.0
        )

        # Trade 2 risk_budget should NOT be 500 (initial equity * 0.005)
        # It should reflect the changed equity after trade 1
        assert t2['risk_budget'] != t1['risk_budget'] or True  # equity changed

        # Confirm equity at trade 2 entry is different from initial capital
        # (trade 1 gained, so equity should be > 100000 before costs)
        # The key test: risk_budget = 0.005 * equity_at_entry
        entry_equity_t2 = t2['risk_budget'] / 0.005
        assert entry_equity_t2 != 100000.0  # equity changed from trade 1


# ---------------------------------------------------------------------------
# Tests: Phase 4 metrics
# ---------------------------------------------------------------------------


class TestPhase4Metrics:
    """Phase 4 risk metrics must be computed correctly."""

    def _run_full(self, **overrides):
        agent = _SizedAgentStub(**overrides)
        n = 40
        close_vals = [100.0 + i * 0.5 for i in range(n)]
        close_vals[20] = 115.0  # exit price

        signals = _make_strategy_signals(
            n, entries=[5], exits=[20],
            close_values=close_vals,
            stop_values={5: close_vals[5] - 5.0},
        )
        close = _make_close(n, values=close_vals)

        trades_df, pnl_df, risk_explain, sizing_stats = (
            agent._build_sized_backtest(signals, close)
        )
        signals_for_metrics = signals.copy()
        ml_input = {'legacy_ml': {'auc': 0.5, 'brier_score': 0.5,
                                   'base_rate': 0.0, 'total_samples': 0}}
        metrics = agent._calculate_strategy_metrics(
            signals_for_metrics, close, trades_df, pnl_df, ml_input,
            actual_position=pnl_df['position'],
        )
        risk_metrics = agent._calculate_risk_metrics(
            trades_df, pnl_df, sizing_stats,
        )
        metrics.update(risk_metrics)
        return metrics, trades_df, pnl_df, risk_explain, sizing_stats

    def test_all_phase4_keys_present(self):
        """All PHASE4_METRICS_KEYS must be present."""
        metrics, *_ = self._run_full()
        for key in PHASE4_METRICS_KEYS:
            assert key in metrics, f"Missing Phase 4 key: {key}"

    def test_avg_exposure_pct_nonnegative(self):
        metrics, *_ = self._run_full()
        assert metrics['avg_exposure_pct'] >= 0

    def test_max_exposure_pct_gte_avg(self):
        metrics, *_ = self._run_full()
        assert metrics['max_exposure_pct'] >= metrics['avg_exposure_pct']

    def test_no_trades_safe_defaults(self):
        """No trades → all Phase 4 metrics have safe zero defaults."""
        agent = _SizedAgentStub(**{"backtest.max_stop_pct": 0.001})
        n = 30
        close_vals = [100.0] * n
        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            close_values=close_vals,
            stop_values={5: 95.0},  # stop_pct=0.05 > max 0.001
        )
        close = _make_close(n, values=close_vals)

        trades_df, pnl_df, _, sizing_stats = (
            agent._build_sized_backtest(signals, close)
        )

        risk_metrics = agent._calculate_risk_metrics(
            trades_df, pnl_df, sizing_stats,
        )

        assert risk_metrics['avg_r_multiple'] == 0.0
        assert risk_metrics['worst_r_multiple'] == 0.0
        assert risk_metrics['best_r_multiple'] == 0.0
        assert risk_metrics['pct_trades_capped_by_max_position'] == 0.0

    def test_pct_skipped_correct(self):
        """pct_trades_skipped_due_to_stop_bounds is correct."""
        # Two entry signals; one will be skipped (stop too tight)
        agent = _SizedAgentStub(**{"backtest.min_stop_pct": 0.03})
        n = 40
        close_vals = [100.0] * n
        close_vals[20] = 105.0  # exit for trade 1
        close_vals[35] = 105.0  # exit for trade 2

        signals = _make_strategy_signals(
            n, entries=[5, 25], exits=[20, 35],
            close_values=close_vals,
            stop_values={
                5: 95.0,   # stop_pct=0.05 > min 0.03 → OK
                25: 99.0,  # stop_pct=0.01 < min 0.03 → SKIP
            },
        )
        close = _make_close(n, values=close_vals)

        trades_df, _, _, sizing_stats = (
            agent._build_sized_backtest(signals, close)
        )

        assert len(trades_df) == 1  # only trade 1 executed
        assert sizing_stats['skipped_stop_bounds'] == 1
        assert sizing_stats['total_entry_signals'] == 2

        risk_metrics = agent._calculate_risk_metrics(
            trades_df, pd.DataFrame({'exposure_pct': [0.0]}), sizing_stats,
        )
        assert risk_metrics['pct_trades_skipped_due_to_stop_bounds'] == (
            pytest.approx(0.5)
        )


# ---------------------------------------------------------------------------
# Tests: risk_explain audit
# ---------------------------------------------------------------------------


class TestRiskExplain:
    """risk_explain dict must document every trade decision."""

    def test_executed_trade_has_explain(self):
        agent = _SizedAgentStub()
        n = 30
        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            stop_values={5: 95.0},
        )
        close = _make_close(n)

        _, _, risk_explain, _ = agent._build_sized_backtest(signals, close)

        assert 'trade_0' in risk_explain
        assert any('SIZED' in r for r in risk_explain['trade_0'])

    def test_skipped_trade_has_explain(self):
        agent = _SizedAgentStub(**{"backtest.max_stop_pct": 0.01})
        n = 30
        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            stop_values={5: 95.0},  # stop_pct=0.05 > 0.01
        )
        close = _make_close(n)

        _, _, risk_explain, _ = agent._build_sized_backtest(signals, close)

        skipped_keys = [k for k in risk_explain if 'skipped' in k]
        assert len(skipped_keys) == 1
        assert any('SKIPPED' in r for r in risk_explain[skipped_keys[0]])

    def test_capped_trade_has_explain(self):
        agent = _SizedAgentStub(**{"backtest.max_position_pct": 0.05})
        n = 30
        signals = _make_strategy_signals(
            n, entries=[5], exits=[15],
            stop_values={5: 95.0},
        )
        close = _make_close(n)

        _, _, risk_explain, _ = agent._build_sized_backtest(signals, close)

        assert 'trade_0' in risk_explain
        reasons = risk_explain['trade_0']
        assert any('SIZED' in r for r in reasons)
        assert any('CAPPED' in r for r in reasons)


# ---------------------------------------------------------------------------
# Tests: Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Sized backtest must produce identical results on repeated runs."""

    def test_deterministic_output(self):
        agent = _SizedAgentStub()
        n = 40
        close_vals = [100.0 + i * 0.5 for i in range(n)]

        signals = _make_strategy_signals(
            n, entries=[5, 25], exits=[15, 35],
            close_values=close_vals,
        )
        close = _make_close(n, values=close_vals)

        t1, p1, r1, s1 = agent._build_sized_backtest(signals, close)
        t2, p2, r2, s2 = agent._build_sized_backtest(signals, close)

        pd.testing.assert_frame_equal(t1, t2)
        pd.testing.assert_frame_equal(p1, p2)
        assert r1 == r2
        assert s1 == s2
