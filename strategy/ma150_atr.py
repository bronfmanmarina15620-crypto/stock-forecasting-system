"""
Pure, deterministic MA150 + ATR(14) trailing-stop strategy module.

Strategy: Trend Following with Regime Filter and RANGE_HIGH_VOL block.
Long-only. No ML. No randomness.

Position timing convention: same-bar (EOD).
    Signal on day t -> position becomes 1 on day t.
    This matches the existing backtest engine (eod execution_assumption).

Rules
-----
A) Regime Filter
   trend_ok = (close > ma150) & (slope(ma150) > 0)
   slope[t] = ma150[t] - ma150[t - slope_lookback]

B) RANGE_HIGH_VOL block
   trend_weak = abs(slope) <= slope_min
   high_vol   = (atr / close) >= atr_pct_high
   range_high_vol = trend_weak & high_vol
   regime_ok  = trend_ok & (~range_high_vol)

C) Entry: 20-day breakout
   entry_signal = regime_ok & (close > rolling_max(close, entry_lookback).shift(1))
   Only fires when NOT already in a position.

D) Exit: ATR trailing stop
   stop = highest_close_since_entry - atr_mult * atr
   Exit when close <= stop.  Only fires when IN a position.

E) Position: 0/1 (long-only, no shorting)
"""

import json

import numpy as np
import pandas as pd


def compute_ma150_atr_strategy(
    close: pd.Series,
    ma150: pd.Series,
    atr: pd.Series,
    *,
    atr_length: int = 14,
    atr_mult: float = 3.0,
    slope_lookback: int = 20,
    entry_lookback: int = 20,
    atr_pct_high: float = 0.04,
    slope_min: float = 0.0,
) -> pd.DataFrame:
    """Compute MA150 + ATR trailing stop strategy signals.

    Parameters
    ----------
    close : pd.Series
        Daily close prices, datetime-indexed.
    ma150 : pd.Series
        150-day simple moving average of close, same index.
    atr : pd.Series
        Average True Range (typically 14-period), same index.
    atr_length : int
        ATR period (documentation only; ATR is pre-computed).
    atr_mult : float
        ATR multiplier for trailing stop (default 3.0).
    slope_lookback : int
        Lookback for MA150 slope calculation (default 20).
    entry_lookback : int
        Lookback for breakout entry (default 20).
    atr_pct_high : float
        ATR/close threshold for high-volatility flag (default 0.04).
    slope_min : float
        Minimum absolute slope for trend detection (default 0.0).

    Returns
    -------
    pd.DataFrame
        Columns: regime_ok, range_high_vol, entry_signal, exit_signal,
                 stop_price, position, reasons
    """
    n = len(close)
    idx = close.index

    # ------------------------------------------------------------------
    # A) Regime Filter
    # ------------------------------------------------------------------
    # slope[t] = ma150[t] - ma150[t - slope_lookback]  (no lookahead)
    slope = ma150 - ma150.shift(slope_lookback)
    trend_ok = (close > ma150) & (slope > 0)

    # ------------------------------------------------------------------
    # B) RANGE_HIGH_VOL
    # ------------------------------------------------------------------
    trend_weak = slope.abs() <= slope_min
    atr_pct = atr / close
    high_vol = atr_pct >= atr_pct_high
    range_high_vol = trend_weak & high_vol

    # regime_ok = trend_ok AND NOT range_high_vol
    regime_ok = trend_ok & (~range_high_vol)

    # ------------------------------------------------------------------
    # C) Breakout entry condition (vectorised part)
    # ------------------------------------------------------------------
    # Rolling max of previous entry_lookback days, shifted by 1 to
    # exclude today from the lookback window.
    rolling_max_prev = close.rolling(entry_lookback).max().shift(1)
    breakout = close > rolling_max_prev
    entry_condition = regime_ok & breakout

    # ------------------------------------------------------------------
    # D + E) Stateful position tracking with ATR trailing stop
    # ------------------------------------------------------------------
    position = np.zeros(n, dtype=np.int64)
    stop_price = np.full(n, np.nan, dtype=np.float64)
    exit_signal = np.zeros(n, dtype=bool)
    entry_signal = np.zeros(n, dtype=bool)
    reasons_list: list[list[str]] = []

    in_position = False
    highest_close = np.nan

    for i in range(n):
        c = close.iloc[i]
        a = atr.iloc[i]
        m = ma150.iloc[i]
        s = slope.iloc[i]
        _safe_bool = lambda v: bool(v) if not pd.isna(v) else False
        rhv = _safe_bool(range_high_vol.iloc[i])
        to = _safe_bool(trend_ok.iloc[i])
        bc = _safe_bool(breakout.iloc[i])
        ec = _safe_bool(entry_condition.iloc[i])

        day_reasons: list[str] = []

        if in_position:
            # Update trailing stop
            highest_close = max(highest_close, c)
            if not np.isnan(a):
                current_stop = highest_close - (atr_mult * a)
            else:
                current_stop = np.nan
            stop_price[i] = current_stop

            if not np.isnan(current_stop) and c <= current_stop:
                # EXIT
                exit_signal[i] = True
                position[i] = 0
                in_position = False
                day_reasons.append(
                    f"Exit: close<=ATR_stop (close={c:.4f}, stop={current_stop:.4f})"
                )
                highest_close = np.nan
            else:
                position[i] = 1
                day_reasons.append(
                    f"Hold: trailing stop intact "
                    f"(close={c:.4f}, stop={current_stop:.4f}, "
                    f"highest={highest_close:.4f})"
                )
        else:
            # Not in position - build reason for why we don't enter
            if pd.isna(m) or pd.isna(s) or pd.isna(a):
                day_reasons.append("No entry: insufficient data (warmup period)")
            elif rhv:
                ap = float(atr_pct.iloc[i]) if not pd.isna(atr_pct.iloc[i]) else 0.0
                day_reasons.append(
                    f"Blocked: RANGE_HIGH_VOL "
                    f"(trend_weak & high_vol; atr_pct={ap:.4f}>={atr_pct_high})"
                )
            elif not to:
                if c <= m:
                    day_reasons.append(
                        f"Regime fail: close<=MA150 "
                        f"(close={c:.4f}, ma150={m:.4f})"
                    )
                if not pd.isna(s) and s <= 0:
                    day_reasons.append(
                        f"Regime fail: MA150 slope<=0 (slope={s:.4f})"
                    )
            elif not bc:
                rm = float(rolling_max_prev.iloc[i]) if not pd.isna(rolling_max_prev.iloc[i]) else 0.0
                day_reasons.append(
                    f"No entry: breakout not triggered "
                    f"(close={c:.4f}<=rolling_high_prev{entry_lookback}={rm:.4f})"
                )

            if ec:
                # ENTRY
                entry_signal[i] = True
                position[i] = 1
                in_position = True
                highest_close = c
                stop_val = c - (atr_mult * a)
                stop_price[i] = stop_val
                day_reasons.append(
                    f"Entry: breakout triggered and regime_ok "
                    f"(close={c:.4f}, stop={stop_val:.4f})"
                )
            else:
                position[i] = 0

        reasons_list.append(day_reasons)

    result = pd.DataFrame(
        {
            "regime_ok": regime_ok,
            "range_high_vol": range_high_vol,
            "entry_signal": pd.array(entry_signal, dtype=bool),
            "exit_signal": pd.array(exit_signal, dtype=bool),
            "stop_price": stop_price,
            "position": position,
            "reasons": [json.dumps(r) for r in reasons_list],
        },
        index=idx,
    )

    return result
