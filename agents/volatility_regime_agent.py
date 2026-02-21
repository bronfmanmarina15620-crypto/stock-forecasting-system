"""
VolatilityRegimeAgent - Phase 5 volatility regime classification.

Runs AFTER RegimeAgent and BEFORE StrategyAgent.
Produces:
    - regime_series.parquet   (date, atr_short, atr_long, atr_ratio,
                                atr_slope, regime, size_multiplier)
    - regime_latest.json      (latest-date snapshot)
    - metrics.json            (day counts / percentages per regime)
"""

import json
import os

import numpy as np
import pandas as pd
from typing import Dict, Any

from .base_agent import BaseAgent


# Regime label constants
QUIET = "QUIET"
NORMAL = "NORMAL"
EXPANDING = "EXPANDING"
EXTREME = "EXTREME"

_VALID_REGIMES = {QUIET, NORMAL, EXPANDING, EXTREME}

_REGIME_SERIES_COLUMNS = [
    "date", "atr_short", "atr_long", "atr_ratio",
    "atr_slope", "regime", "size_multiplier",
]


def classify_volatility_regime(
    atr_ratio: float,
    atr_slope: float,
    quiet_threshold: float,
    expansion_threshold: float,
    extreme_threshold: float,
) -> str:
    """Classify a single day's volatility regime.

    Precedence (highest first):
        1. EXTREME  if ratio > extreme_threshold
        2. EXPANDING if ratio > expansion_threshold AND slope > 0
        3. QUIET    if ratio < quiet_threshold
        4. NORMAL   otherwise
    """
    if np.isnan(atr_ratio):
        return NORMAL  # safe default during warmup

    if atr_ratio > extreme_threshold:
        return EXTREME

    # NaN slope treated as slope <= 0 (blocks EXPANDING only)
    slope_positive = (not np.isnan(atr_slope)) and atr_slope > 0
    if atr_ratio > expansion_threshold and slope_positive:
        return EXPANDING
    if atr_ratio < quiet_threshold:
        return QUIET
    return NORMAL


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                window: int) -> pd.Series:
    """Compute ATR using simple rolling mean of True Range."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def compute_slope(series: pd.Series, lookback: int) -> pd.Series:
    """Compute rolling linear-regression slope over *lookback* periods.

    Uses numpy polyfit (degree 1) for deterministic results.
    Returns NaN where fewer than *lookback* valid points are available.
    """
    result = pd.Series(np.nan, index=series.index)
    values = series.values
    x = np.arange(lookback, dtype=np.float64)
    for i in range(lookback - 1, len(values)):
        window = values[i - lookback + 1: i + 1]
        if np.any(np.isnan(window)):
            continue
        coeffs = np.polyfit(x, window, 1)
        result.iloc[i] = coeffs[0]
    return result


def _validate_regime_latest(latest: Dict[str, Any], vr_cfg: Any) -> None:
    """Validate invariants on the latest regime snapshot before writing.

    Raises ValueError with offending values if any invariant fails.
    """
    regime = latest["regime"]
    if regime not in _VALID_REGIMES:
        raise ValueError(
            f"Invalid regime label '{regime}'. "
            f"Must be one of {sorted(_VALID_REGIMES)}"
        )

    expected_mult = vr_cfg.size_multipliers.get(regime.lower(), 1.0)
    if latest["multiplier"] != expected_mult:
        raise ValueError(
            f"Multiplier mismatch: regime={regime} expects "
            f"multiplier={expected_mult}, got {latest['multiplier']}"
        )

    ratio = latest.get("atr_ratio")
    slope = latest.get("atr_slope")
    th = latest["thresholds"]

    # EXTREME iff ratio > extreme_threshold (ratio may be None during warmup)
    if ratio is not None:
        if regime == EXTREME and not (ratio > th["extreme"]):
            raise ValueError(
                f"EXTREME requires ratio > {th['extreme']}, "
                f"got ratio={ratio}, slope={slope}"
            )
        if regime != EXTREME and ratio > th["extreme"]:
            raise ValueError(
                f"ratio={ratio} > extreme={th['extreme']} "
                f"but regime={regime} (should be EXTREME)"
            )

    # EXPANDING implies ratio > expansion AND slope > 0 AND NOT EXTREME
    if regime == EXPANDING:
        if ratio is None or not (ratio > th["expansion"]):
            raise ValueError(
                f"EXPANDING requires ratio > {th['expansion']}, "
                f"got ratio={ratio}"
            )
        if slope is None or slope <= 0:
            raise ValueError(
                f"EXPANDING requires slope > 0, got slope={slope}"
            )


class VolatilityRegimeAgent(BaseAgent):
    """Classify daily volatility regime from ATR ratio + ATR slope."""

    def run(self) -> Dict[str, Any]:
        """Compute regime series and write artifacts."""
        self.logger.info("Starting volatility regime classification")

        try:
            vr_cfg = self.config.strategy.volatility_regime
            enabled = getattr(
                self.config.strategy, 'volatility_regime_enabled', True
            )

            # Load raw OHLCV
            data_output = self.load_agent_output("DataAgent")
            if data_output["status"] != "SUCCESS":
                return {"status": "FAILED", "error": "DataAgent failed"}

            df = pd.read_parquet(data_output["data_path"])
            high = df["High"]
            low = df["Low"]
            close = df["Close"]

            if not enabled:
                # Emit stub artifacts — all NORMAL, multiplier 1.0
                regime_df = pd.DataFrame({
                    "date": df.index,
                    "atr_short": np.nan,
                    "atr_long": np.nan,
                    "atr_ratio": np.nan,
                    "atr_slope": np.nan,
                    "regime": NORMAL,
                    "size_multiplier": 1.0,
                })
                return self._write_artifacts(regime_df, vr_cfg)

            # --- Compute ATR short / long ---
            atr_short = compute_atr(high, low, close, vr_cfg.atr_short)
            atr_long = compute_atr(high, low, close, vr_cfg.atr_long)

            # --- ATR ratio ---
            atr_ratio = pd.Series(np.nan, index=df.index)
            nonzero = atr_long != 0
            atr_ratio[nonzero] = atr_short[nonzero] / atr_long[nonzero]

            # --- ATR slope (of the short ATR) ---
            atr_slope = compute_slope(atr_short, vr_cfg.slope_lookback)

            # --- Classify each day ---
            regimes = []
            for i in range(len(df)):
                label = classify_volatility_regime(
                    float(atr_ratio.iloc[i]),
                    float(atr_slope.iloc[i]),
                    vr_cfg.quiet_threshold,
                    vr_cfg.expansion_threshold,
                    vr_cfg.extreme_threshold,
                )
                regimes.append(label)

            # --- Multiplier ---
            multipliers = [
                vr_cfg.size_multipliers.get(r.lower(), 1.0)
                for r in regimes
            ]

            regime_df = pd.DataFrame({
                "date": df.index,
                "atr_short": atr_short.values,
                "atr_long": atr_long.values,
                "atr_ratio": atr_ratio.values,
                "atr_slope": atr_slope.values,
                "regime": regimes,
                "size_multiplier": multipliers,
            })

            return self._write_artifacts(regime_df, vr_cfg)

        except Exception as e:
            self.logger.error(
                f"Volatility regime classification failed: {str(e)}"
            )
            import traceback
            traceback.print_exc()
            return {"status": "FAILED", "error": str(e)}

    # ------------------------------------------------------------------
    # Artifact writing
    # ------------------------------------------------------------------

    def _write_artifacts(
        self,
        regime_df: pd.DataFrame,
        vr_cfg: Any,
    ) -> Dict[str, Any]:
        """Write parquet, latest JSON, and metrics JSON."""

        # Sort by date ascending for determinism
        regime_df = regime_df.sort_values("date").reset_index(drop=True)

        # --- Schema guard: regime_series must have all required columns ---
        missing = set(_REGIME_SERIES_COLUMNS) - set(regime_df.columns)
        if missing:
            raise ValueError(
                f"regime_series missing columns: {sorted(missing)}"
            )
        # Coerce types for determinism
        regime_df["regime"] = regime_df["regime"].astype(str)
        regime_df["size_multiplier"] = regime_df["size_multiplier"].astype(
            float
        )

        # --- regime_series.parquet ---
        self.save_artifact("regime_series.parquet", regime_df)

        # --- regime_latest.json ---
        last = regime_df.iloc[-1]
        latest = {
            "date": str(last["date"].date())
            if hasattr(last["date"], "date")
            else str(last["date"]),
            "regime": last["regime"],
            "atr_ratio": (
                float(last["atr_ratio"])
                if not np.isnan(last["atr_ratio"])
                else None
            ),
            "atr_slope": (
                float(last["atr_slope"])
                if not np.isnan(last["atr_slope"])
                else None
            ),
            "thresholds": {
                "quiet": vr_cfg.quiet_threshold,
                "expansion": vr_cfg.expansion_threshold,
                "extreme": vr_cfg.extreme_threshold,
            },
            "multiplier": float(last["size_multiplier"]),
        }

        # --- Invariant check before persisting regime_latest ---
        _validate_regime_latest(latest, vr_cfg)

        self.save_artifact("regime_latest.json", latest)

        # --- metrics.json ---
        counts = regime_df["regime"].value_counts().to_dict()
        total = len(regime_df)
        pcts = {k: float(v / total * 100) for k, v in counts.items()}
        metrics = {
            "regime_day_counts": counts,
            "regime_day_pcts": pcts,
            "total_days": total,
        }
        self.save_artifact("metrics.json", metrics)

        output = {
            "status": "SUCCESS",
            "latest_regime": latest["regime"],
            "latest_multiplier": latest["multiplier"],
            "regime_series_path": self.get_artifact_path(
                "regime_series.parquet"
            ),
            "regime_latest_path": self.get_artifact_path(
                "regime_latest.json"
            ),
        }
        self.save_output(output)
        self.logger.info(
            f"Volatility regime complete: latest={latest['regime']}, "
            f"multiplier={latest['multiplier']}"
        )
        return output
