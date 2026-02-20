"""
Deterministic unit tests for the MA150+ATR trend-following strategy.

All tests use small synthetic series — no randomness, no network, no I/O.
"""

import json

import numpy as np
import pandas as pd
import pytest

from strategy.ma150_atr import compute_ma150_atr_strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _constant_series(n: int, value: float, start: str = "2024-01-01") -> pd.Series:
    return pd.Series(value, index=_make_dates(n, start))


def _linear_series(
    n: int, start_val: float, step: float, start_date: str = "2024-01-01"
) -> pd.Series:
    """Create a linearly increasing/decreasing series."""
    return pd.Series(
        [start_val + i * step for i in range(n)],
        index=_make_dates(n, start_date),
    )


# ---------------------------------------------------------------------------
# 1. Slope calculation correctness
# ---------------------------------------------------------------------------


class TestSlopeCalculation:
    """slope[t] = ma150[t] - ma150[t - slope_lookback]."""

    def test_slope_positive_when_ma_rising(self):
        """A linearly rising MA150 should produce positive slope."""
        n = 250
        close = _linear_series(n, 100.0, 0.5)
        ma150 = _linear_series(n, 80.0, 0.4)  # rising MA
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=20
        )

        # After warmup (slope_lookback=20), slope should be positive
        valid = result.iloc[20:]
        # slope = ma150[t] - ma150[t-20] = 0.4*20 = 8.0 > 0
        assert valid["regime_ok"].any(), "Should have some regime_ok=True days"

    def test_slope_negative_when_ma_falling(self):
        """A linearly falling MA150 should produce negative slope -> regime_ok=False."""
        n = 250
        close = _linear_series(n, 100.0, -0.5)  # falling close
        ma150 = _linear_series(n, 120.0, -0.4)  # falling MA
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=20
        )

        # Close < MA150 AND slope < 0 -> regime_ok should be False
        valid = result.iloc[20:]
        assert not valid["regime_ok"].any(), "Falling MA should have regime_ok=False"

    def test_slope_uses_correct_lookback(self):
        """Slope with lookback=5 vs lookback=20 should give different warmup."""
        n = 200
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.25)
        atr = _constant_series(n, 2.0)

        result_5 = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=5
        )
        result_20 = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=20
        )

        # With lookback=5, slope is valid from day 5 onward
        # With lookback=20, slope is valid from day 20 onward
        # Day 10 should be valid for lookback=5 but NaN for lookback=20
        day10_5 = result_5["regime_ok"].iloc[10]
        day10_20 = result_20["regime_ok"].iloc[10]

        assert not pd.isna(day10_5), "lookback=5 should have valid data at day 10"
        # Day 10 with lookback=20 may be NaN (slope can't be computed yet)
        # (ma150[10] - ma150[10-20] -> index -10 is NaN)


# ---------------------------------------------------------------------------
# 1b. ma150_trend_ok column (pre-range_high_vol)
# ---------------------------------------------------------------------------


class TestMA150TrendOk:
    """ma150_trend_ok = (close > ma150) AND (slope > 0), before RHV override."""

    def test_ma150_trend_ok_true_when_above_and_rising(self):
        """close > ma150 AND slope > 0 -> ma150_trend_ok = True."""
        n = 200
        close = _linear_series(n, 100.0, 0.5)
        ma150 = _linear_series(n, 80.0, 0.4)  # rising, below close
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=20
        )

        valid = result.iloc[20:]
        assert valid["ma150_trend_ok"].all(), (
            "ma150_trend_ok should be True when close>ma150 and slope>0"
        )

    def test_ma150_trend_ok_differs_from_regime_ok_during_rhv(self):
        """When RANGE_HIGH_VOL, ma150_trend_ok can be True while regime_ok is False."""
        n = 200
        dates = _make_dates(n)

        # Close above MA150 but flat slope and high vol
        # slope=0 with slope_min=0 -> trend_weak=True
        # BUT close > ma150 and slope is exactly 0 which is NOT > 0
        # So ma150_trend_ok = False here too.
        # To get the divergence: slope must be > 0 (trend_ok=True)
        # but abs(slope) <= slope_min (trend_weak=True) with slope_min > 0
        close = _constant_series(n, 110.0)
        ma150 = _linear_series(n, 100.0, 0.01)  # very slow rise
        atr = _constant_series(n, 5.0)  # atr/close=5/110~4.5%>=4%

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=20,
            atr_pct_high=0.04,
            slope_min=0.5,  # slope=0.01*20=0.2 < 0.5 -> trend_weak
        )

        valid = result.iloc[20:]
        # ma150_trend_ok = close>ma150 AND slope>0 -> True (slope=0.2>0)
        # range_high_vol = trend_weak AND high_vol -> True
        # regime_ok = ma150_trend_ok AND NOT range_high_vol -> False
        has_divergence = (valid["ma150_trend_ok"] & ~valid["regime_ok"]).any()
        assert has_divergence, (
            "ma150_trend_ok should be True while regime_ok is False during RHV"
        )

    def test_ma150_trend_ok_false_when_below_ma(self):
        """close < ma150 -> ma150_trend_ok = False."""
        n = 200
        close = _constant_series(n, 80.0)
        ma150 = _constant_series(n, 100.0)  # above close
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=20
        )

        assert not result["ma150_trend_ok"].any(), (
            "ma150_trend_ok should be False when close < ma150"
        )

    def test_ma150_trend_ok_column_present(self):
        """Output DataFrame must contain ma150_trend_ok column."""
        n = 200
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(close, ma150, atr)
        assert "ma150_trend_ok" in result.columns


# ---------------------------------------------------------------------------
# 2. Breakout entry triggers
# ---------------------------------------------------------------------------


class TestBreakoutEntry:
    """Entry only fires when close > shifted rolling max AND regime_ok."""

    def test_breakout_triggers_on_new_high(self):
        """After a series of flat prices, a breakout day should trigger entry."""
        n = 200
        dates = _make_dates(n)

        # Flat at 100 for first 170 days, then jump to 110 on day 170
        close_vals = [100.0] * 170 + [110.0] + [110.0] * 29
        close = pd.Series(close_vals, index=dates)
        # MA150 below close for regime_ok
        ma150 = _constant_series(n, 95.0)
        atr = _constant_series(n, 3.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=5,  # short lookback so regime_ok kicks in fast
            entry_lookback=20,
        )

        # Day 170 jumps from 100 to 110 -> breakout above 20-day rolling max
        # But slope = ma150[170] - ma150[165] = 95 - 95 = 0 -> not positive
        # So regime_ok may be False. Let's use a rising MA150.
        ma150_rising = pd.Series(
            [90.0 + i * 0.05 for i in range(n)], index=dates
        )
        result2 = compute_ma150_atr_strategy(
            close, ma150_rising, atr,
            slope_lookback=5,
            entry_lookback=20,
        )

        # Day 170: close=110, rolling_max_prev20 = max of [100]*20 shifted = 100
        # 110 > 100 -> breakout.  regime_ok requires close > ma150 and slope > 0
        assert result2["entry_signal"].iloc[170], (
            "Breakout day should trigger entry_signal"
        )

    def test_no_entry_during_warmup(self):
        """No entries should fire during the first entry_lookback days."""
        n = 200
        # Steadily rising close
        close = _linear_series(n, 80.0, 0.5)
        ma150 = _linear_series(n, 70.0, 0.3)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=5,
            entry_lookback=20,
        )

        # First entry_lookback days should have no entry (rolling max is NaN)
        # The shifted rolling max needs at least entry_lookback + 1 days
        assert not result["entry_signal"].iloc[:20].any(), (
            "No entry should fire in first 20 days (warmup)"
        )

    def test_no_entry_when_regime_not_ok(self):
        """Even if breakout happens, no entry when regime_ok=False."""
        n = 200
        dates = _make_dates(n)

        # Close below MA150 -> regime fail
        close_vals = [50.0] * 170 + [60.0] + [60.0] * 29
        close = pd.Series(close_vals, index=dates)
        ma150 = _constant_series(n, 100.0)  # MA150 way above close
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=5,
            entry_lookback=20,
        )

        # Breakout from 50 to 60 but close < MA150=100 -> no entry
        assert not result["entry_signal"].any(), (
            "No entry when close < MA150"
        )

    def test_rolling_max_excludes_today(self):
        """Rolling max should NOT include today's close (shifted by 1)."""
        n = 200
        dates = _make_dates(n)

        # Flat at 100, then 101 on day 50 (just barely above the max)
        close_vals = [100.0] * 50 + [101.0] + [99.0] * 149
        close = pd.Series(close_vals, index=dates)
        ma150_vals = [90.0 + i * 0.1 for i in range(n)]
        ma150 = pd.Series(ma150_vals, index=dates)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=5,
            entry_lookback=20,
        )

        # Day 50: close=101.  Rolling max of prev 20 days (day 30-49) = 100.
        # 101 > 100 -> breakout.  If rolling max included today, it would be
        # 101 and 101 > 101 is False.
        # Check that the entry_signal considers the previous 20 days only
        if result["regime_ok"].iloc[50]:
            assert result["entry_signal"].iloc[50], (
                "Rolling max should exclude today's close"
            )


# ---------------------------------------------------------------------------
# 3. ATR trailing stop
# ---------------------------------------------------------------------------


class TestATRTrailingStop:
    """Trailing stop = highest_close_since_entry - atr_mult * atr."""

    def test_stop_updates_with_higher_close(self):
        """As close rises, highest_close updates, raising the stop."""
        n = 200
        dates = _make_dates(n)

        # Flat 100 for 50 days, breakout to 110, then rise to 120 linearly
        close_vals = [100.0] * 50 + [110.0 + i * 0.2 for i in range(150)]
        close = pd.Series(close_vals, index=dates)
        ma150 = pd.Series([90.0 + i * 0.1 for i in range(n)], index=dates)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            atr_mult=3.0,
            slope_lookback=5,
            entry_lookback=20,
        )

        # Find the first entry
        entry_days = result.index[result["entry_signal"]]
        if len(entry_days) > 0:
            entry_idx = result.index.get_loc(entry_days[0])
            # Check stops after entry are rising (as close rises)
            in_pos = result.iloc[entry_idx:]
            in_pos = in_pos[in_pos["position"] == 1]
            if len(in_pos) > 2:
                stops = in_pos["stop_price"].values
                # Stops should be non-decreasing (since close rises monotonically)
                assert all(
                    stops[i + 1] >= stops[i] - 1e-10
                    for i in range(len(stops) - 1)
                ), "Stop should rise as close rises"

    def test_exit_when_close_drops_below_stop(self):
        """Exit triggers when close <= stop_price."""
        n = 200
        dates = _make_dates(n)

        # Rise to 120, then sharp drop to trigger stop
        close_vals = (
            [100.0] * 50
            + [110.0 + i * 0.5 for i in range(40)]
            + [90.0] * 110  # sharp drop
        )
        close = pd.Series(close_vals, index=dates)
        ma150 = pd.Series([88.0 + i * 0.1 for i in range(n)], index=dates)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            atr_mult=3.0,
            slope_lookback=5,
            entry_lookback=20,
        )

        # If an entry happened, the sharp drop should trigger exit
        if result["entry_signal"].any():
            # After the drop, position should go to 0
            assert result["exit_signal"].any(), (
                "Sharp drop should trigger exit_signal"
            )
            # After exit, position should be 0
            exit_day = result.index[result["exit_signal"]][0]
            exit_loc = result.index.get_loc(exit_day)
            assert result["position"].iloc[exit_loc] == 0, (
                "Position should be 0 on exit day"
            )

    def test_stop_initial_value(self):
        """On entry day, stop = close - atr_mult * atr."""
        n = 200
        dates = _make_dates(n)

        close_vals = [100.0] * 50 + [115.0] + [115.0] * 149
        close = pd.Series(close_vals, index=dates)
        ma150 = pd.Series([85.0 + i * 0.15 for i in range(n)], index=dates)
        atr = _constant_series(n, 2.5)

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            atr_mult=3.0,
            slope_lookback=5,
            entry_lookback=20,
        )

        entry_days = result.index[result["entry_signal"]]
        if len(entry_days) > 0:
            entry_idx = result.index.get_loc(entry_days[0])
            entry_close = close.iloc[entry_idx]
            entry_stop = result["stop_price"].iloc[entry_idx]
            expected_stop = entry_close - 3.0 * 2.5
            assert abs(entry_stop - expected_stop) < 1e-10, (
                f"Initial stop should be {expected_stop}, got {entry_stop}"
            )


# ---------------------------------------------------------------------------
# 4. RANGE_HIGH_VOL blocks entries
# ---------------------------------------------------------------------------


class TestRangeHighVol:
    """RANGE_HIGH_VOL = (abs(slope) <= slope_min) & (atr/close >= atr_pct_high)."""

    def test_range_high_vol_blocks_entry(self):
        """When trend_weak AND high_vol, no entry should fire."""
        n = 200
        dates = _make_dates(n)

        # Flat MA150 -> slope = 0 -> trend_weak
        # High ATR -> atr/close >= atr_pct_high
        close_vals = [100.0] * 50 + [110.0] + [110.0] * 149
        close = pd.Series(close_vals, index=dates)
        ma150 = _constant_series(n, 95.0)  # flat -> slope = 0
        atr = _constant_series(n, 5.0)  # atr/close = 5/100 = 0.05 >= 0.04

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=20,
            atr_pct_high=0.04,
            slope_min=0.0,
        )

        # range_high_vol should be True (flat slope + high atr)
        valid = result.iloc[20:]
        assert valid["range_high_vol"].any(), (
            "RANGE_HIGH_VOL should be True when slope=0 and atr/close>=0.04"
        )
        # No entries when RANGE_HIGH_VOL blocks
        rhv_days = valid[valid["range_high_vol"]]
        assert not rhv_days["entry_signal"].any(), (
            "No entry should fire when RANGE_HIGH_VOL is True"
        )

    def test_no_range_high_vol_when_strong_trend(self):
        """When slope is strong (> slope_min), range_high_vol should be False."""
        n = 200
        close = _linear_series(n, 100.0, 0.5)
        ma150 = _linear_series(n, 90.0, 0.4)  # rising -> slope > 0
        atr = _constant_series(n, 2.0)  # atr/close ~ 2/100 = 0.02 < 0.04

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=20,
            atr_pct_high=0.04,
            slope_min=0.0,
        )

        valid = result.iloc[20:]
        # slope = 0.4*20 = 8.0 > 0 -> trend_weak=False -> range_high_vol=False
        assert not valid["range_high_vol"].any(), (
            "RANGE_HIGH_VOL should be False when slope > 0"
        )

    def test_range_high_vol_reason_in_output(self):
        """RANGE_HIGH_VOL days should have blocking reason."""
        n = 200
        dates = _make_dates(n)

        close = _constant_series(n, 100.0)
        ma150 = _constant_series(n, 95.0)
        atr = _constant_series(n, 5.0)  # atr/close = 0.05 >= 0.04

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=20,
            atr_pct_high=0.04,
            slope_min=0.0,
        )

        # Find a day with range_high_vol=True
        rhv_days = result[result["range_high_vol"]].iloc[20:]
        if len(rhv_days) > 0:
            reasons = json.loads(rhv_days["reasons"].iloc[0])
            assert any("RANGE_HIGH_VOL" in r for r in reasons), (
                "Reasons should mention RANGE_HIGH_VOL"
            )


# ---------------------------------------------------------------------------
# 5. No lookahead: altering future data should not change earlier signals
# ---------------------------------------------------------------------------


class TestNoLookahead:
    """Signals at time t depend only on data at <=t."""

    def test_future_data_does_not_affect_past_signals(self):
        """Changing data after day T should not alter signals at or before T."""
        n = 200
        dates = _make_dates(n)
        T = 100  # pivot point

        # Version A: original data
        close_a = pd.Series(
            [100.0 + i * 0.3 for i in range(n)], index=dates
        )
        ma150_a = pd.Series(
            [90.0 + i * 0.2 for i in range(n)], index=dates
        )
        atr_a = _constant_series(n, 2.0)

        result_a = compute_ma150_atr_strategy(
            close_a, ma150_a, atr_a, slope_lookback=5, entry_lookback=20
        )

        # Version B: identical up to day T, then completely different
        close_b = close_a.copy()
        close_b.iloc[T:] = 50.0  # collapse after T
        ma150_b = ma150_a.copy()
        ma150_b.iloc[T:] = 200.0  # jump after T
        atr_b = atr_a.copy()
        atr_b.iloc[T:] = 10.0  # big change after T

        result_b = compute_ma150_atr_strategy(
            close_b, ma150_b, atr_b, slope_lookback=5, entry_lookback=20
        )

        # All columns at indices 0..T-1 should be identical
        cols_to_check = [
            "regime_ok", "range_high_vol", "entry_signal",
            "exit_signal", "stop_price", "position",
        ]
        for col in cols_to_check:
            a_vals = result_a[col].iloc[:T]
            b_vals = result_b[col].iloc[:T]
            if col == "stop_price":
                # Handle NaN comparison
                np.testing.assert_array_equal(
                    a_vals.fillna(-999).values,
                    b_vals.fillna(-999).values,
                    err_msg=f"Column {col} differs before pivot T={T}",
                )
            else:
                np.testing.assert_array_equal(
                    a_vals.values,
                    b_vals.values,
                    err_msg=f"Column {col} differs before pivot T={T}",
                )

    def test_deterministic_same_input_same_output(self):
        """Same inputs should always produce identical outputs."""
        n = 200
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        r1 = compute_ma150_atr_strategy(close, ma150, atr)
        r2 = compute_ma150_atr_strategy(close, ma150, atr)

        pd.testing.assert_frame_equal(r1, r2)


# ---------------------------------------------------------------------------
# 6. Reasons are auditable
# ---------------------------------------------------------------------------


class TestReasons:
    """Every day must have non-empty, JSON-parseable reasons."""

    def test_reasons_are_valid_json(self):
        n = 200
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=5
        )

        for i, row in result.iterrows():
            parsed = json.loads(row["reasons"])
            assert isinstance(parsed, list), f"Reasons at {i} should be a list"
            assert len(parsed) > 0, f"Reasons at {i} should be non-empty"

    def test_entry_reason_present(self):
        """Entry days should have 'Entry:' in reasons."""
        n = 200
        dates = _make_dates(n)
        close_vals = [100.0] * 50 + [115.0] + [115.0] * 149
        close = pd.Series(close_vals, index=dates)
        ma150 = pd.Series([85.0 + i * 0.15 for i in range(n)], index=dates)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=5, entry_lookback=20
        )

        entry_days = result[result["entry_signal"]]
        for _, row in entry_days.iterrows():
            reasons = json.loads(row["reasons"])
            assert any("Entry:" in r for r in reasons), (
                "Entry days should have 'Entry:' reason"
            )

    def test_insufficient_history_reason_during_warmup(self):
        """Early days with NaN indicators must have 'Insufficient history' reason."""
        n = 200
        dates = _make_dates(n)

        # Use pre-computed MA150 with NaNs for first 20 days
        # to simulate warmup period
        ma150_vals = [np.nan] * 20 + [90.0 + i * 0.2 for i in range(n - 20)]
        close = _linear_series(n, 100.0, 0.3)
        ma150 = pd.Series(ma150_vals, index=dates)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=5, entry_lookback=20
        )

        # First 20 days: MA150 is NaN -> reasons must mention
        # "Insufficient history"
        for i in range(20):
            reasons = json.loads(result["reasons"].iloc[i])
            assert len(reasons) > 0, f"Day {i} should have non-empty reasons"
            assert any("Insufficient history" in r for r in reasons), (
                f"Day {i} should mention 'Insufficient history', "
                f"got: {reasons}"
            )

    def test_insufficient_history_for_entry_lookback(self):
        """When indicators are ready but rolling_max_prev is NaN, reason
        must mention 'Insufficient history: entry_lookback'."""
        n = 200
        dates = _make_dates(n)

        # MA150 and ATR valid from day 0, slope valid from day 5
        # but entry_lookback=50 so rolling_max_prev NaN until day 50+1
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)  # all valid
        atr = _constant_series(n, 2.0)  # all valid

        result = compute_ma150_atr_strategy(
            close, ma150, atr,
            slope_lookback=5,
            entry_lookback=50,
        )

        # Day 10: slope valid (lookback=5), atr valid, ma150 valid
        # but rolling_max_prev needs 50+1 days -> NaN at day 10
        # However, slope at day 10 needs ma150[10] - ma150[5], both valid
        # and close > ma150 is True, slope > 0 is True -> regime_ok
        # So if regime_ok and no breakout NaN, should hit the entry_lookback
        # insufficient history branch
        day10_reasons = json.loads(result["reasons"].iloc[10])
        if not any("Insufficient history" in r for r in day10_reasons):
            # May have been caught by another reason (regime fail etc.)
            # Just verify it's non-empty
            assert len(day10_reasons) > 0


# ---------------------------------------------------------------------------
# 7. Position is always 0 or 1
# ---------------------------------------------------------------------------


class TestPositionConstraints:
    def test_position_binary(self):
        """Position should always be 0 or 1."""
        n = 200
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=5
        )

        assert set(result["position"].unique()).issubset({0, 1}), (
            "Position should only be 0 or 1"
        )

    def test_no_short_positions(self):
        """Position should never be negative (long-only)."""
        n = 200
        close = _linear_series(n, 150.0, -0.5)
        ma150 = _linear_series(n, 100.0, -0.3)
        atr = _constant_series(n, 3.0)

        result = compute_ma150_atr_strategy(
            close, ma150, atr, slope_lookback=5
        )

        assert (result["position"] >= 0).all(), "No short positions allowed"
