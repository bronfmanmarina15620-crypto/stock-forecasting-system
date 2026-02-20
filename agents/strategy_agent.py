"""
StrategyAgent - Computes MA150+ATR strategy signals and artifacts.

Runs AFTER DataAgent (needs raw OHLCV) and BEFORE DecisionRiskAgent.
Produces:
    - strategy_signals.parquet  (regime_ok, range_high_vol, ma150_trend_ok,
                                 entry_signal, exit_signal, stop_price, position)
    - strategy_explain.json     (daily reasons keyed by date)
    - stop_series.parquet       (date, stop_price, position)
"""

import json

import numpy as np
import pandas as pd
from typing import Dict, Any

from .base_agent import BaseAgent
from strategy.ma150_atr import compute_ma150_atr_strategy

# Phase 2 schema lock — any change here requires a migration plan.
REQUIRED_SIGNAL_COLS = [
    "regime_ok",
    "range_high_vol",
    "ma150_trend_ok",
    "entry_signal",
    "exit_signal",
    "stop_price",
    "position",
]

_EXPECTED_DTYPES = {
    "regime_ok": "bool",
    "range_high_vol": "bool",
    "ma150_trend_ok": "bool",
    "entry_signal": "bool",
    "exit_signal": "bool",
    "stop_price": "float64",
    "position": "int64",
}


def _validate_signal_schema(df: pd.DataFrame) -> None:
    """Validate strategy_signals DataFrame against the locked schema.

    Raises ValueError on any mismatch so broken schemas fail loudly
    instead of silently corrupting downstream artifacts.
    """
    actual_cols = list(df.columns)
    if actual_cols != REQUIRED_SIGNAL_COLS:
        raise ValueError(
            f"strategy_signals schema mismatch.\n"
            f"  Expected: {REQUIRED_SIGNAL_COLS}\n"
            f"  Got:      {actual_cols}"
        )
    for col, expected_dtype in _EXPECTED_DTYPES.items():
        actual = str(df[col].dtype)
        if actual != expected_dtype:
            raise ValueError(
                f"strategy_signals dtype mismatch for '{col}': "
                f"expected {expected_dtype}, got {actual}"
            )


class StrategyAgent(BaseAgent):
    """Compute MA150+ATR trend-following strategy signals."""

    def run(self) -> Dict[str, Any]:
        """Generate strategy signals from raw OHLCV data."""
        self.logger.info("Starting MA150+ATR strategy computation")

        try:
            # Load raw price data from DataAgent
            data_output = self.load_agent_output("DataAgent")
            if data_output["status"] != "SUCCESS":
                return {"status": "FAILED", "error": "DataAgent failed"}

            df = pd.read_parquet(data_output["data_path"])
            close = df["Close"]
            high = df["High"]
            low = df["Low"]

            # ---- Compute MA150 (raw, not shifted) ----
            ma150 = close.rolling(150).mean()

            # ---- Compute ATR(14) (raw, not shifted) ----
            atr_window = self.config.strategy.atr_length
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(atr_window).mean()

            # ---- Run strategy ----
            params = {
                "atr_length": self.config.strategy.atr_length,
                "atr_mult": self.config.strategy.atr_mult,
                "slope_lookback": self.config.strategy.slope_lookback,
                "entry_lookback": self.config.strategy.entry_lookback,
                "atr_pct_high": self.config.strategy.atr_pct_high,
                "slope_min": self.config.strategy.slope_min,
            }
            result = compute_ma150_atr_strategy(close, ma150, atr, **params)

            # ---- Build artifacts ----
            signals_df = result[REQUIRED_SIGNAL_COLS].copy()
            _validate_signal_schema(signals_df)

            # Strategy explain: daily reasons keyed by date string
            explain = {}
            for dt, reasons_json in result["reasons"].items():
                date_str = str(dt.date()) if hasattr(dt, "date") else str(dt)
                explain[date_str] = json.loads(reasons_json)

            # Stop series
            stop_df = pd.DataFrame({
                "date": result.index,
                "stop_price": result["stop_price"].values,
                "position": result["position"].values,
            })

            # ---- Save artifacts ----
            self.save_artifact("strategy_signals.parquet", signals_df)
            self.save_artifact("strategy_explain.json", explain)
            self.save_artifact("stop_series.parquet", stop_df)

            # Summary stats for output.json
            n_entries = int(result["entry_signal"].sum())
            n_exits = int(result["exit_signal"].sum())
            n_days_in_position = int(result["position"].sum())
            n_regime_ok = int(result["regime_ok"].sum())
            n_range_high_vol = int(result["range_high_vol"].sum())

            output = {
                "status": "SUCCESS",
                "strategy": "MA150_ATR_trend_following",
                "params": params,
                "total_bars": len(result),
                "entries": n_entries,
                "exits": n_exits,
                "days_in_position": n_days_in_position,
                "regime_ok_days": n_regime_ok,
                "range_high_vol_days": n_range_high_vol,
                "signals_path": self.get_artifact_path("strategy_signals.parquet"),
                "explain_path": self.get_artifact_path("strategy_explain.json"),
                "stop_path": self.get_artifact_path("stop_series.parquet"),
            }

            self.save_output(output)
            self.logger.info(
                f"Strategy complete: {n_entries} entries, {n_exits} exits, "
                f"{n_days_in_position} days in position"
            )
            return output

        except Exception as e:
            self.logger.error(f"Strategy computation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"status": "FAILED", "error": str(e)}
