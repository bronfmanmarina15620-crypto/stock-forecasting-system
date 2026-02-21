"""
Deterministic unit tests for Phase 5 volatility regime classification.

All tests use small synthetic data — no randomness, no network, no I/O.
"""

import json
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from agents.volatility_regime_agent import (
    classify_volatility_regime,
    compute_atr,
    compute_slope,
    QUIET,
    NORMAL,
    EXPANDING,
    EXTREME,
)
from config import (
    SystemConfig,
    StrategyConfig,
    VolatilityRegimeConfig,
    get_default_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _constant_series(n: int, value: float, start: str = "2024-01-01") -> pd.Series:
    return pd.Series(value, index=_make_dates(n, start))


# Default thresholds matching VolatilityRegimeConfig defaults
QUIET_TH = 0.8
EXPANSION_TH = 1.2
EXTREME_TH = 1.5


# ---------------------------------------------------------------------------
# 1. Threshold boundary tests
# ---------------------------------------------------------------------------

class TestClassifyVolatilityRegime:
    """Test classify_volatility_regime with exact boundary values."""

    def test_quiet_when_ratio_below_quiet_threshold(self):
        result = classify_volatility_regime(0.7, 0.0, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == QUIET

    def test_normal_when_ratio_equals_quiet_threshold(self):
        result = classify_volatility_regime(0.8, 0.0, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL

    def test_normal_when_ratio_between_thresholds(self):
        result = classify_volatility_regime(1.0, 0.0, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL

    def test_normal_when_ratio_above_expansion_but_slope_zero(self):
        """ratio > expansion but slope == 0 -> NORMAL (not EXPANDING)."""
        result = classify_volatility_regime(1.3, 0.0, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL

    def test_normal_when_ratio_above_expansion_but_slope_negative(self):
        """ratio > expansion but slope < 0 -> NORMAL (not EXPANDING)."""
        result = classify_volatility_regime(1.3, -0.1, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL

    def test_expanding_when_ratio_above_expansion_and_slope_positive(self):
        result = classify_volatility_regime(1.3, 0.1, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == EXPANDING

    def test_extreme_when_ratio_above_extreme_threshold(self):
        result = classify_volatility_regime(1.6, 0.0, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == EXTREME


# ---------------------------------------------------------------------------
# 2. Precedence tests
# ---------------------------------------------------------------------------

class TestRegimePrecedence:
    """EXTREME overrides EXPANDING; NaN → NORMAL."""

    def test_extreme_overrides_expanding(self):
        """ratio > extreme AND slope > 0 -> EXTREME (not EXPANDING)."""
        result = classify_volatility_regime(1.6, 0.5, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == EXTREME

    def test_nan_ratio_returns_normal(self):
        result = classify_volatility_regime(np.nan, 0.0, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL

    def test_nan_slope_normal_ratio_returns_normal(self):
        """ratio in NORMAL range + NaN slope -> NORMAL."""
        result = classify_volatility_regime(1.0, np.nan, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL

    def test_nan_slope_extreme_ratio_returns_extreme(self):
        """ratio > extreme_threshold + NaN slope -> EXTREME (slope irrelevant)."""
        result = classify_volatility_regime(1.6, np.nan, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == EXTREME

    def test_nan_slope_quiet_ratio_returns_quiet(self):
        """ratio < quiet_threshold + NaN slope -> QUIET (slope irrelevant)."""
        result = classify_volatility_regime(0.5, np.nan, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == QUIET

    def test_nan_slope_expanding_ratio_returns_normal(self):
        """ratio > expansion but NaN slope -> NORMAL (NaN slope blocks EXPANDING)."""
        result = classify_volatility_regime(1.3, np.nan, QUIET_TH, EXPANSION_TH, EXTREME_TH)
        assert result == NORMAL


# ---------------------------------------------------------------------------
# 3. Multiplier mapping
# ---------------------------------------------------------------------------

class TestMultiplierMapping:
    """Size multipliers must match config defaults."""

    def test_default_multipliers(self):
        cfg = VolatilityRegimeConfig()
        assert cfg.size_multipliers["quiet"] == 0.5
        assert cfg.size_multipliers["normal"] == 1.0
        assert cfg.size_multipliers["expanding"] == 0.5
        assert cfg.size_multipliers["extreme"] == 0.0


# ---------------------------------------------------------------------------
# 4. compute_slope determinism
# ---------------------------------------------------------------------------

class TestComputeSlope:
    """Slope via linear regression must be deterministic."""

    def test_slope_of_linear_series(self):
        """Slope of y = 2*x should be ~2.0."""
        n = 20
        dates = _make_dates(n)
        series = pd.Series([2.0 * i for i in range(n)], index=dates)
        slope = compute_slope(series, lookback=10)
        # From index 9 onward the slope should be exactly 2.0
        for i in range(9, n):
            assert abs(slope.iloc[i] - 2.0) < 1e-10, (
                f"Slope at {i} should be 2.0, got {slope.iloc[i]}"
            )

    def test_slope_nan_during_warmup(self):
        """First (lookback-1) values should be NaN."""
        n = 20
        dates = _make_dates(n)
        series = pd.Series(range(n), index=dates, dtype=float)
        slope = compute_slope(series, lookback=10)
        for i in range(9):
            assert np.isnan(slope.iloc[i]), f"Day {i} should be NaN"

    def test_slope_deterministic(self):
        """Same input -> same output."""
        n = 50
        dates = _make_dates(n)
        series = pd.Series(np.sin(np.arange(n, dtype=float)), index=dates)
        s1 = compute_slope(series, lookback=10)
        s2 = compute_slope(series, lookback=10)
        pd.testing.assert_series_equal(s1, s2)


# ---------------------------------------------------------------------------
# 5. compute_atr determinism
# ---------------------------------------------------------------------------

class TestComputeATR:
    def test_atr_constant_range(self):
        """When high-low is constant, ATR should equal that constant."""
        n = 50
        dates = _make_dates(n)
        high = pd.Series(110.0, index=dates)
        low = pd.Series(100.0, index=dates)
        close = pd.Series(105.0, index=dates)
        atr = compute_atr(high, low, close, window=14)
        # After warmup, ATR should be exactly 10.0
        valid = atr.iloc[14:]
        assert np.allclose(valid.values, 10.0, atol=1e-10)


# ---------------------------------------------------------------------------
# 6. Config loading
# ---------------------------------------------------------------------------

class TestConfigLoading:
    """VolatilityRegimeConfig integrates with StrategyConfig."""

    def test_default_config_has_volatility_regime(self):
        cfg = get_default_config("PLTR")
        vr = cfg.strategy.volatility_regime
        assert isinstance(vr, VolatilityRegimeConfig)
        assert vr.atr_short == 14
        assert vr.atr_long == 100
        assert vr.extreme_threshold == 1.5

    def test_volatility_regime_enabled_default_true(self):
        cfg = get_default_config("PLTR")
        assert cfg.strategy.volatility_regime_enabled is True

    def test_missing_yaml_section_uses_defaults(self):
        """If volatility_regime key is absent from YAML, defaults apply."""
        sc = StrategyConfig()
        assert sc.volatility_regime_enabled is True
        assert sc.volatility_regime.quiet_threshold == 0.8


# ---------------------------------------------------------------------------
# 7. Integration: EXTREME blocks ENTER
# ---------------------------------------------------------------------------

class TestExtremeBlocksEnter:
    """DecisionRiskAgent must force ABSTAIN when volatility regime is EXTREME."""

    def test_extreme_forces_abstain(self):
        """Simulate: strategy says ENTER, but regime is EXTREME -> ABSTAIN."""
        from agents.decision_risk_agent import DecisionRiskAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create VolatilityRegimeAgent/regime_latest.json with EXTREME
            vr_dir = os.path.join(tmpdir, "VolatilityRegimeAgent")
            os.makedirs(vr_dir)
            latest = {
                "date": "2024-06-01",
                "regime": "EXTREME",
                "atr_ratio": 1.8,
                "atr_slope": 0.5,
                "thresholds": {"quiet": 0.8, "expansion": 1.2, "extreme": 1.5},
                "multiplier": 0.0,
            }
            with open(os.path.join(vr_dir, "regime_latest.json"), "w") as f:
                json.dump(latest, f)

            # Build a fake decision_action that says ENTER
            decision_action = {
                "action": "ENTER",
                "position": 1,
                "regime_ok": True,
                "range_high_vol": False,
                "ma150_trend_ok": True,
                "entry_signal": True,
                "exit_signal": False,
                "stop_price": 100.0,
                "because": ["Entry: breakout above 20-day high"],
                "date": "2024-06-01",
            }

            # Instantiate agent with minimal config
            config = get_default_config("PLTR")
            agent = DecisionRiskAgent.__new__(DecisionRiskAgent)
            agent.config = config
            agent.run_dir = tmpdir
            from utils import AgentLogger
            agent.logger = AgentLogger("DecisionRiskAgent", tmpdir)
            agent.agent_name = "DecisionRiskAgent"
            agent.agent_dir = os.path.join(tmpdir, "DecisionRiskAgent")
            os.makedirs(agent.agent_dir, exist_ok=True)

            result = agent._apply_volatility_regime(decision_action)

            assert result["action"] == "ABSTAIN"
            assert result["position"] == 0
            assert result["volatility_regime"] == "EXTREME"
            assert result["volatility_size_multiplier"] == 0.0
            assert "blocked_by_volatility_regime_extreme" in result["because"]

    def test_normal_does_not_block_enter(self):
        """When regime is NORMAL, ENTER should remain ENTER."""
        from agents.decision_risk_agent import DecisionRiskAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            vr_dir = os.path.join(tmpdir, "VolatilityRegimeAgent")
            os.makedirs(vr_dir)
            latest = {
                "date": "2024-06-01",
                "regime": "NORMAL",
                "atr_ratio": 1.0,
                "atr_slope": 0.01,
                "thresholds": {"quiet": 0.8, "expansion": 1.2, "extreme": 1.5},
                "multiplier": 1.0,
            }
            with open(os.path.join(vr_dir, "regime_latest.json"), "w") as f:
                json.dump(latest, f)

            decision_action = {
                "action": "ENTER",
                "position": 1,
                "regime_ok": True,
                "range_high_vol": False,
                "ma150_trend_ok": True,
                "entry_signal": True,
                "exit_signal": False,
                "stop_price": 100.0,
                "because": ["Entry: breakout"],
                "date": "2024-06-01",
            }

            config = get_default_config("PLTR")
            agent = DecisionRiskAgent.__new__(DecisionRiskAgent)
            agent.config = config
            agent.run_dir = tmpdir
            from utils import AgentLogger
            agent.logger = AgentLogger("DecisionRiskAgent", tmpdir)
            agent.agent_name = "DecisionRiskAgent"
            agent.agent_dir = os.path.join(tmpdir, "DecisionRiskAgent")
            os.makedirs(agent.agent_dir, exist_ok=True)

            result = agent._apply_volatility_regime(decision_action)

            assert result["action"] == "ENTER"
            assert result["position"] == 1
            assert result["volatility_regime"] == "NORMAL"
            assert result["volatility_size_multiplier"] == 1.0

    def test_no_vr_agent_files_no_override(self):
        """When VolatilityRegimeAgent artifacts are absent, no override."""
        from agents.decision_risk_agent import DecisionRiskAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            decision_action = {
                "action": "ENTER",
                "position": 1,
                "because": ["Entry: breakout"],
                "date": "2024-06-01",
            }

            config = get_default_config("PLTR")
            agent = DecisionRiskAgent.__new__(DecisionRiskAgent)
            agent.config = config
            agent.run_dir = tmpdir
            from utils import AgentLogger
            agent.logger = AgentLogger("DecisionRiskAgent", tmpdir)
            agent.agent_name = "DecisionRiskAgent"
            agent.agent_dir = os.path.join(tmpdir, "DecisionRiskAgent")
            os.makedirs(agent.agent_dir, exist_ok=True)

            result = agent._apply_volatility_regime(decision_action)

            assert result["action"] == "ENTER"
            assert result["volatility_regime"] is None
            assert result["volatility_size_multiplier"] == 1.0
