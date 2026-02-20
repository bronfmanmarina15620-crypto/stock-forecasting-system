"""
Schema lock tests for StrategyAgent artifacts.

Prevents silent column renames/removals in strategy_signals.parquet.
"""

import json

import numpy as np
import pandas as pd
import pytest

from strategy.ma150_atr import compute_ma150_atr_strategy

# Import the locked schema constants from the agent module.
# Use importlib to avoid triggering the agents package __init__
# which may pull in heavy dependencies.
import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_mod = importlib.import_module("agents.strategy_agent")
REQUIRED_SIGNAL_COLS = _mod.REQUIRED_SIGNAL_COLS
_EXPECTED_DTYPES = _mod._EXPECTED_DTYPES
_validate_signal_schema = _mod._validate_signal_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _linear_series(n, start_val, step, start_date="2024-01-01"):
    return pd.Series(
        [start_val + i * step for i in range(n)],
        index=_make_dates(n, start_date),
    )


def _constant_series(n, value, start_date="2024-01-01"):
    return pd.Series(value, index=_make_dates(n, start_date))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSchemaLock:
    """The REQUIRED_SIGNAL_COLS constant must match the Phase 2 spec exactly."""

    def test_required_cols_match_spec(self):
        expected = [
            "regime_ok",
            "range_high_vol",
            "ma150_trend_ok",
            "entry_signal",
            "exit_signal",
            "stop_price",
            "position",
        ]
        assert REQUIRED_SIGNAL_COLS == expected

    def test_expected_dtypes_match_spec(self):
        expected = {
            "regime_ok": "bool",
            "range_high_vol": "bool",
            "ma150_trend_ok": "bool",
            "entry_signal": "bool",
            "exit_signal": "bool",
            "stop_price": "float64",
            "position": "int64",
        }
        assert _EXPECTED_DTYPES == expected

    def test_strategy_output_passes_validation(self):
        """compute_ma150_atr_strategy output must pass _validate_signal_schema."""
        n = 200
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(close, ma150, atr, slope_lookback=5)
        signals_df = result[REQUIRED_SIGNAL_COLS].copy()

        # Should not raise
        _validate_signal_schema(signals_df)

    def test_validation_rejects_missing_column(self):
        """Removing a column must trigger a ValueError."""
        n = 50
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(close, ma150, atr, slope_lookback=5)
        # Drop one column
        bad_df = result[REQUIRED_SIGNAL_COLS].drop(columns=["ma150_trend_ok"])

        with pytest.raises(ValueError, match="schema mismatch"):
            _validate_signal_schema(bad_df)

    def test_validation_rejects_wrong_dtype(self):
        """Wrong dtype must trigger a ValueError."""
        n = 50
        close = _linear_series(n, 100.0, 0.3)
        ma150 = _linear_series(n, 90.0, 0.2)
        atr = _constant_series(n, 2.0)

        result = compute_ma150_atr_strategy(close, ma150, atr, slope_lookback=5)
        signals_df = result[REQUIRED_SIGNAL_COLS].copy()
        # Corrupt dtype: cast position to float
        signals_df["position"] = signals_df["position"].astype(float)

        with pytest.raises(ValueError, match="dtype mismatch"):
            _validate_signal_schema(signals_df)
