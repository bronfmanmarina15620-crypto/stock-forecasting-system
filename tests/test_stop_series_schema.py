"""
Schema lock tests for stop_series.parquet.

Prevents silent column renames/removals/dtype changes in stop_series.
"""

import numpy as np
import pandas as pd
import pytest

from strategy.ma150_atr import compute_ma150_atr_strategy

import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_mod = importlib.import_module("agents.strategy_agent")
REQUIRED_STOP_COLS = _mod.REQUIRED_STOP_COLS
_EXPECTED_STOP_DTYPES = _mod._EXPECTED_STOP_DTYPES
_validate_stop_schema = _mod._validate_stop_schema


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


def _make_stop_df_from_strategy(n=200):
    """Build a stop_df the same way StrategyAgent does."""
    close = _linear_series(n, 100.0, 0.3)
    ma150 = _linear_series(n, 90.0, 0.2)
    atr = _constant_series(n, 2.0)
    result = compute_ma150_atr_strategy(close, ma150, atr, slope_lookback=5)
    return pd.DataFrame({
        "date": result.index,
        "stop_price": result["stop_price"].values,
        "position": result["position"].values,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStopSchemaLock:
    """REQUIRED_STOP_COLS constant must match the Phase 2 spec exactly."""

    def test_required_cols_match_spec(self):
        assert REQUIRED_STOP_COLS == ["date", "stop_price", "position"]

    def test_expected_dtypes_match_spec(self):
        assert _EXPECTED_STOP_DTYPES == {
            "stop_price": "float64",
            "position": "int64",
        }

    def test_strategy_output_passes_stop_validation(self):
        """stop_df built from compute_ma150_atr_strategy must pass validation."""
        stop_df = _make_stop_df_from_strategy()
        # Should not raise
        _validate_stop_schema(stop_df)

    def test_validation_rejects_missing_column(self):
        """Removing a column must trigger a ValueError."""
        stop_df = _make_stop_df_from_strategy()
        bad_df = stop_df.drop(columns=["position"])
        with pytest.raises(ValueError, match="schema mismatch"):
            _validate_stop_schema(bad_df)

    def test_validation_rejects_wrong_dtype(self):
        """Wrong dtype must trigger a ValueError."""
        stop_df = _make_stop_df_from_strategy()
        stop_df["position"] = stop_df["position"].astype(float)
        with pytest.raises(ValueError, match="dtype mismatch"):
            _validate_stop_schema(stop_df)

    def test_validation_rejects_non_datetime_date(self):
        """date column must be datetime-like."""
        stop_df = _make_stop_df_from_strategy()
        stop_df["date"] = stop_df["date"].astype(str)
        with pytest.raises(ValueError, match="datetime-like"):
            _validate_stop_schema(stop_df)

    def test_validation_rejects_invalid_position_values(self):
        """position must only contain {0, 1}."""
        stop_df = _make_stop_df_from_strategy()
        stop_df.loc[0, "position"] = 2
        with pytest.raises(ValueError, match="invalid values"):
            _validate_stop_schema(stop_df)

    def test_position_only_zero_one(self):
        """All position values from strategy must be 0 or 1."""
        stop_df = _make_stop_df_from_strategy()
        unique_vals = set(stop_df["position"].unique())
        assert unique_vals.issubset({0, 1})
