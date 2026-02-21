"""
Tests for Phase 6 RobustnessAgent.

Covers:
  - Deterministic seed: same input trade series => same monte_carlo percentiles
  - Sensitivity grid shape
  - Walk-forward window boundaries ordering
  - JSON schema sanity: keys exist
"""

import json
import math
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Import the agent directly
from agents.robustness_agent import (
    RobustnessAgent,
    _MONTE_CARLO_SEED,
    _ATR_MULT_FACTORS,
    _RISK_PCT_FACTORS,
)


# ============================================================
# Fixtures
# ============================================================


def _make_config():
    """Build a minimal config object matching expected interface."""
    from config import (
        SystemConfig, BacktestConfig, StrategyConfig,
        DataConfig, FeatureConfig, EventConfig, RegimeConfig,
        DecisionConfig, PortfolioConfig, MemoryConfig,
    )
    return SystemConfig(
        ticker="TEST",
        strategy=StrategyConfig(
            atr_length=14,
            atr_mult=3.0,
            slope_lookback=20,
            entry_lookback=20,
            atr_pct_high=0.04,
            slope_min=0.0,
            risk_per_trade=0.005,
        ),
        backtest=BacktestConfig(
            capital_base=100000.0,
            max_leverage=1.0,
            max_position_pct=0.25,
            min_stop_pct=0.01,
            max_stop_pct=0.20,
            commission_pct=0.001,
            spread_bps=2.0,
            slippage_bps=3.0,
        ),
    )


def _make_trades(n=20, seed=42):
    """Create a deterministic trades DataFrame."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n * 10, freq="B")
    trades = []
    for i in range(n):
        entry_i = i * 10
        exit_i = entry_i + rng.randint(3, 8)
        entry_price = 50.0 + rng.randn() * 5
        exit_price = entry_price * (1 + rng.randn() * 0.05)
        ret = (exit_price / entry_price - 1) - 0.002
        trades.append({
            "entry_date": str(dates[entry_i].date()),
            "entry_price": entry_price,
            "exit_date": str(dates[exit_i].date()),
            "exit_price": exit_price,
            "pnl": exit_price - entry_price,
            "return": ret,
            "holding_days": (dates[exit_i] - dates[entry_i]).days,
            "shares": 100,
            "notional": 100 * entry_price,
            "exposure_pct": 0.05,
            "stop_distance": entry_price * 0.05,
            "stop_pct": 0.05,
            "risk_budget": 500.0,
            "r_multiple": ret / 0.005 if 0.005 > 0 else 0.0,
        })
    return pd.DataFrame(trades)


def _make_pnl_series(n=500, seed=42):
    """Create a deterministic pnl_series DataFrame."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n, freq="B")
    daily_ret = rng.randn(n) * 0.01
    equity = 100000.0 * np.cumprod(1 + daily_ret)
    position = np.zeros(n, dtype=int)
    # Simulate some days in position
    position[50:100] = 1
    position[200:250] = 1
    position[350:400] = 1
    exposure = np.where(position > 0, 0.10, 0.0)
    return pd.DataFrame({
        "date": dates,
        "equity_curve": equity,
        "daily_return": daily_ret,
        "position": position,
        "exposure_pct": exposure,
    })


def _make_strategy_signals(n=500, seed=42):
    """Create a deterministic strategy_signals DataFrame."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n, freq="B")
    close = 50.0 + np.cumsum(rng.randn(n) * 0.5)
    close = np.maximum(close, 1.0)  # keep positive

    regime_ok = np.ones(n, dtype=bool)
    range_high_vol = np.zeros(n, dtype=bool)
    ma150_trend_ok = np.ones(n, dtype=bool)
    entry_signal = np.zeros(n, dtype=bool)
    exit_signal = np.zeros(n, dtype=bool)
    position = np.zeros(n, dtype=int)
    stop_price = np.full(n, np.nan)

    # Create some entry/exit pairs
    entry_signal[50] = True
    exit_signal[99] = True
    position[50:100] = 1

    entry_signal[200] = True
    exit_signal[249] = True
    position[200:250] = 1

    entry_signal[350] = True
    exit_signal[399] = True
    position[350:400] = 1

    return pd.DataFrame({
        "regime_ok": regime_ok,
        "range_high_vol": range_high_vol,
        "ma150_trend_ok": ma150_trend_ok,
        "entry_signal": entry_signal,
        "exit_signal": exit_signal,
        "stop_price": stop_price,
        "position": position,
    }, index=dates)


def _make_close_series(n=500, seed=42):
    """Create a deterministic close price series."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n, freq="B")
    close = 50.0 + np.cumsum(rng.randn(n) * 0.5)
    close = np.maximum(close, 1.0)
    return pd.Series(close, index=dates, name="Close")


# ============================================================
# Tests
# ============================================================


class TestMonteCarloDeterminism:
    """Same input trade series => same monte_carlo percentiles."""

    def test_deterministic_same_seed(self):
        """Two runs with identical trades must produce identical MC results."""
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        trades = _make_trades(n=20, seed=42)

        result1 = agent._monte_carlo_reshuffle(trades)
        result2 = agent._monte_carlo_reshuffle(trades)

        assert result1["final_return"]["percentiles"] == result2["final_return"]["percentiles"]
        assert result1["max_drawdown"]["percentiles"] == result2["max_drawdown"]["percentiles"]
        assert result1["final_return"]["mean"] == result2["final_return"]["mean"]

    def test_different_trades_different_result(self):
        """Different trade series should produce different MC results."""
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        trades_a = _make_trades(n=20, seed=42)
        trades_b = _make_trades(n=20, seed=99)

        result_a = agent._monte_carlo_reshuffle(trades_a)
        result_b = agent._monte_carlo_reshuffle(trades_b)

        # Very unlikely to be exactly equal with different trade returns
        assert result_a["final_return"]["mean"] != result_b["final_return"]["mean"]

    def test_empty_trades(self):
        """MC reshuffle with no trades returns safe defaults."""
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        trades = pd.DataFrame(columns=[
            "entry_date", "entry_price", "exit_date", "exit_price",
            "pnl", "return", "holding_days",
        ])

        result = agent._monte_carlo_reshuffle(trades)
        assert result["n_trades"] == 0
        assert result["percentiles"] == {}


class TestSensitivityGridShape:
    """Sensitivity grid must be [len(atr_mult_factors) x len(risk_pct_factors)]."""

    def test_grid_shape(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        signals = _make_strategy_signals()
        close = _make_close_series()
        config = _make_config()

        result = agent._parameter_sensitivity(
            signals, close, config.strategy, config.backtest,
        )

        expected_points = len(_ATR_MULT_FACTORS) * len(_RISK_PCT_FACTORS)
        assert len(result["grid"]) == expected_points
        assert result["grid_shape"] == [len(_ATR_MULT_FACTORS), len(_RISK_PCT_FACTORS)]

    def test_grid_has_required_keys(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        signals = _make_strategy_signals()
        close = _make_close_series()
        config = _make_config()

        result = agent._parameter_sensitivity(
            signals, close, config.strategy, config.backtest,
        )

        required_keys = {"atr_mult", "risk_pct", "total_return", "max_dd", "mar", "trades_count"}
        for point in result["grid"]:
            assert required_keys.issubset(point.keys()), f"Missing keys in grid point: {point.keys()}"


class TestWalkForwardWindows:
    """Walk-forward window boundaries must be ordered."""

    def test_window_ordering(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        signals = _make_strategy_signals(n=500)
        close = _make_close_series(n=500)
        trades = _make_trades(n=20)
        pnl = _make_pnl_series(n=500)

        result = agent._walk_forward_validation(signals, close, trades, pnl)
        windows = result["windows"]

        assert len(windows) > 0, "Should produce at least one window"

        # Each window's test_start >= train_end
        for w in windows:
            assert w["test_start"] >= w["train_end"], (
                f"Window {w['window']}: test_start {w['test_start']} "
                f"< train_end {w['train_end']}"
            )

        # Windows are chronologically ordered
        for i in range(1, len(windows)):
            assert windows[i]["test_start"] >= windows[i - 1]["test_start"], (
                f"Window {i} test_start not after window {i-1}"
            )

    def test_insufficient_data_returns_empty(self):
        """Very short series should return 0 windows gracefully."""
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        dates = pd.bdate_range("2024-01-02", periods=5, freq="B")
        signals = pd.DataFrame({
            "regime_ok": [True] * 5,
            "range_high_vol": [False] * 5,
            "ma150_trend_ok": [True] * 5,
            "entry_signal": [False] * 5,
            "exit_signal": [False] * 5,
            "stop_price": [np.nan] * 5,
            "position": [0] * 5,
        }, index=dates)
        close = pd.Series([50.0] * 5, index=dates)
        trades = pd.DataFrame(columns=["entry_date", "return"])
        pnl = pd.DataFrame({
            "date": dates,
            "equity_curve": [100000.0] * 5,
            "daily_return": [0.0] * 5,
            "position": [0] * 5,
        })

        result = agent._walk_forward_validation(signals, close, trades, pnl)
        assert result["n_windows"] == 0


class TestJSONSchemaSanity:
    """All output JSONs must have expected top-level keys."""

    def test_monte_carlo_keys(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        trades = _make_trades(n=15)
        result = agent._monte_carlo_reshuffle(trades)

        assert "n_simulations" in result
        assert "n_trades" in result
        assert "seed" in result
        assert "final_return" in result
        assert "max_drawdown" in result
        assert "percentiles" in result["final_return"]
        assert "percentiles" in result["max_drawdown"]

    def test_exposure_decomposition_keys(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()
        agent.run_dir = "/nonexistent"

        pnl = _make_pnl_series()
        signals = _make_strategy_signals()
        close = _make_close_series()

        result = agent._exposure_decomposition(pnl, signals, close)

        assert "time_in_market_pct" in result
        assert "avg_exposure_pct" in result
        assert "benchmark_correlation" in result
        assert "benchmark_unavailable" in result

    def test_capacity_test_keys(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        close = _make_close_series()
        volume = pd.Series(np.ones(len(close)) * 1e6, index=close.index)
        config = _make_config()

        result = agent._capacity_test(close, volume, config.backtest)

        assert "adv_20d_usd" in result
        assert "max_position_usd" in result
        assert "position_adv_ratio" in result
        assert "category" in result
        assert result["category"] in ("tiny", "small", "moderate", "large")

    def test_capacity_no_volume(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        close = _make_close_series()
        config = _make_config()

        result = agent._capacity_test(close, None, config.backtest)

        assert result["volume_unavailable"] is True
        assert result["category"] == "unknown"

    def test_summary_keys(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()

        summary = agent._build_summary(
            walk_forward={"windows": [], "n_windows": 0},
            sensitivity={"grid": [], "grid_shape": [0, 0]},
            monte_carlo={"n_simulations": 1000, "n_trades": 0, "percentiles": {}},
            exposure={"time_in_market_pct": 10.0, "benchmark_correlation": None, "benchmark_unavailable": True},
            regime_contrib={"buckets": []},
            capacity={"category": "unknown", "position_adv_ratio": None},
            bt_metrics={"total_return": 0.1, "max_drawdown": -0.05},
        )

        assert "phase" in summary
        assert "walk_forward_stability" in summary
        assert "monte_carlo_tail_risk" in summary
        assert "sensitivity_range" in summary
        assert "capacity_category" in summary
        assert "artifact_paths" in summary


class TestRegimeContribution:
    """Regime contribution analysis tests."""

    def test_no_regime_data(self):
        """Should return empty buckets when no regime series available."""
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()
        agent.run_dir = "/nonexistent"

        trades = _make_trades()
        result = agent._regime_contribution(trades)
        assert result["buckets"] == []

    def test_empty_trades(self):
        agent = RobustnessAgent.__new__(RobustnessAgent)
        agent.logger = MagicMock()
        agent.run_dir = "/nonexistent"

        trades = pd.DataFrame(columns=["entry_date", "return"])
        result = agent._regime_contribution(trades)
        assert result["buckets"] == []
