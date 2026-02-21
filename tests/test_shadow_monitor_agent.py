"""
Tests for Phase 7 ShadowMonitorAgent.

Covers:
  - Artifacts written with content_hash_sha256
  - Missing optional inputs produce DEGRADED (not crash)
  - Rolling ENTER frequency computed when history exists
  - Deterministic output for same inputs
"""

import json
import os
import tempfile

import pytest

from agents.shadow_monitor_agent import ShadowMonitorAgent
from determinism import content_hash_sha256


# ============================================================
# Fixtures / helpers
# ============================================================


def _make_config(ticker="TEST"):
    """Minimal config stub with required attributes."""
    from config import (
        SystemConfig, BacktestConfig, StrategyConfig,
        DataConfig, FeatureConfig, EventConfig, RegimeConfig,
        DecisionConfig, PortfolioConfig, MemoryConfig,
    )
    return SystemConfig(
        ticker=ticker,
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


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _setup_full_run(run_dir, ticker="TEST"):
    """Populate a minimal set of upstream agent outputs for shadow mode."""
    # DecisionRiskAgent/decision_action.json
    decision = {
        "action": "ABSTAIN",
        "position": 0,
        "ma150_trend_ok": True,
        "range_high_vol": False,
        "entry_signal": False,
        "exit_signal": False,
        "stop_price": 45.0,
        "because": ["not in breakout"],
        "date": "2026-02-21",
        "content_hash_sha256": "placeholder",
    }
    _write_json(
        os.path.join(run_dir, "DecisionRiskAgent", "decision_action.json"),
        decision,
    )

    # StrategyAgent/output.json
    strategy_output = {
        "status": "SUCCESS",
        "entries": 5,
        "exits": 4,
        "days_in_position": 100,
        "regime_ok_days": 200,
        "range_high_vol_days": 50,
        "ma150_distance_pct": 0.03,
        "atr_latest": 2.5,
    }
    _write_json(
        os.path.join(run_dir, "StrategyAgent", "output.json"),
        strategy_output,
    )

    # RegimeAgent/output.json
    regime_output = {
        "status": "SUCCESS",
        "recent_regime": "TREND_LOW_VOL",
    }
    _write_json(
        os.path.join(run_dir, "RegimeAgent", "output.json"),
        regime_output,
    )

    # BacktestAgent/metrics.json
    metrics = {
        "total_return": 0.15,
        "sharpe": 1.2,
        "num_trades": 10,
        "content_hash_sha256": "placeholder",
    }
    _write_json(
        os.path.join(run_dir, "BacktestAgent", "metrics.json"),
        metrics,
    )


# ============================================================
# Tests
# ============================================================


class TestShadowMonitorArtifacts:
    """shadow_metrics.json and shadow_summary.json are valid."""

    def test_artifacts_written_with_content_hash(self, tmp_path):
        ticker = "TEST"
        run_dir = str(tmp_path / "runs" / ticker / "20260221_120000_abc123")
        os.makedirs(run_dir, exist_ok=True)
        _setup_full_run(run_dir, ticker)

        config = _make_config(ticker)
        agent = ShadowMonitorAgent(config, run_dir)
        result = agent.run()

        assert result["status"] == "SUCCESS"

        # Check shadow_metrics.json
        metrics_path = os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_metrics.json"
        )
        assert os.path.exists(metrics_path)
        with open(metrics_path) as f:
            metrics = json.load(f)

        assert "content_hash_sha256" in metrics
        # Recompute and verify hash integrity
        stored_hash = metrics["content_hash_sha256"]
        recomputed = content_hash_sha256(metrics)
        assert stored_hash == recomputed, "content_hash mismatch in shadow_metrics"

        # Check required keys
        for key in [
            "run_id", "ticker", "mode", "asof_date", "timestamp_utc",
            "decision", "regime_label", "drift_flags", "status",
        ]:
            assert key in metrics, f"Missing key: {key}"

        assert metrics["mode"] == "shadow"
        assert metrics["decision"] == "ABSTAIN"
        assert metrics["regime_label"] == "TREND_LOW_VOL"
        assert metrics["status"] == "OK"

        # Check shadow_summary.json
        summary_path = os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_summary.json"
        )
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)

        assert "content_hash_sha256" in summary
        stored_hash = summary["content_hash_sha256"]
        recomputed = content_hash_sha256(summary)
        assert stored_hash == recomputed, "content_hash mismatch in shadow_summary"

        for key in ["run_id", "ticker", "decision", "regime_label", "status", "top_flag"]:
            assert key in summary


class TestShadowDegradedMode:
    """Missing optional inputs produce DEGRADED, not crash."""

    def test_missing_all_inputs(self, tmp_path):
        """No upstream outputs at all — should still succeed with DEGRADED."""
        ticker = "TEST"
        run_dir = str(tmp_path / "runs" / ticker / "20260221_120000_xyz789")
        os.makedirs(run_dir, exist_ok=True)

        config = _make_config(ticker)
        agent = ShadowMonitorAgent(config, run_dir)
        result = agent.run()

        assert result["status"] == "SUCCESS"  # agent itself succeeds
        assert result["shadow_status"] == "DEGRADED"
        assert "MISSING_DECISION" in result["drift_flags"]

        # Verify artifact written
        metrics_path = os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_metrics.json"
        )
        with open(metrics_path) as f:
            metrics = json.load(f)
        assert metrics["status"] == "DEGRADED"
        assert "MISSING_DECISION" in metrics["drift_flags"]

    def test_missing_decision_only(self, tmp_path):
        """Regime + strategy present, but decision missing."""
        ticker = "TEST"
        run_dir = str(tmp_path / "runs" / ticker / "20260221_120000_nodc01")
        os.makedirs(run_dir, exist_ok=True)

        # Write regime and strategy but NOT decision
        _write_json(
            os.path.join(run_dir, "RegimeAgent", "output.json"),
            {"status": "SUCCESS", "recent_regime": "RANGE_HIGH_VOL"},
        )
        _write_json(
            os.path.join(run_dir, "StrategyAgent", "output.json"),
            {"status": "SUCCESS"},
        )

        config = _make_config(ticker)
        agent = ShadowMonitorAgent(config, run_dir)
        result = agent.run()

        assert result["shadow_status"] == "DEGRADED"
        assert "MISSING_DECISION" in result["drift_flags"]
        assert "MISSING_STRATEGY" not in result["drift_flags"]
        assert result["shadow_decision"] == "UNKNOWN"


class TestShadowRollingHistory:
    """Rolling ENTER frequency computed when history exists."""

    def test_history_created_on_first_run(self, tmp_path):
        ticker = "TEST"
        run_dir = str(tmp_path / "runs" / ticker / "20260221_120000_hist01")
        os.makedirs(run_dir, exist_ok=True)
        _setup_full_run(run_dir, ticker)

        config = _make_config(ticker)
        agent = ShadowMonitorAgent(config, run_dir)
        agent.run()

        history_path = os.path.join(
            tmp_path, "runs", ticker, "_shadow_history", "shadow_history.jsonl"
        )
        assert os.path.exists(history_path)

        with open(history_path) as f:
            lines = f.readlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["decision"] == "ABSTAIN"

    def test_rolling_enter_count(self, tmp_path):
        """Pre-populate history with ENTER lines, verify rolling count."""
        ticker = "TEST"
        run_dir = str(tmp_path / "runs" / ticker / "20260221_120000_hist02")
        os.makedirs(run_dir, exist_ok=True)
        _setup_full_run(run_dir, ticker)

        # Pre-populate 5 ENTER lines
        history_dir = os.path.join(tmp_path, "runs", ticker, "_shadow_history")
        os.makedirs(history_dir, exist_ok=True)
        history_path = os.path.join(history_dir, "shadow_history.jsonl")
        with open(history_path, "w") as f:
            for i in range(5):
                line = json.dumps({
                    "run_id": f"fake_{i}",
                    "asof_date": f"2026-02-{10+i:02d}",
                    "decision": "ENTER",
                    "regime_label": "TREND_LOW_VOL",
                    "status": "OK",
                }, sort_keys=True)
                f.write(line + "\n")

        config = _make_config(ticker)
        agent = ShadowMonitorAgent(config, run_dir)
        agent.run()

        # Read metrics
        metrics_path = os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_metrics.json"
        )
        with open(metrics_path) as f:
            metrics = json.load(f)

        # 5 ENTERs pre-populated + 1 ABSTAIN from this run = 5 out of 6
        assert metrics["enter_rolling_20"] == 5


class TestShadowDeterminism:
    """Same inputs produce identical content_hash_sha256."""

    def test_hash_stability(self, tmp_path):
        ticker = "TEST"
        hashes = []
        for i in range(2):
            run_id = f"20260221_120000_det{i:02d}"
            run_dir = str(tmp_path / "runs" / ticker / run_id)
            os.makedirs(run_dir, exist_ok=True)
            _setup_full_run(run_dir, ticker)

            config = _make_config(ticker)
            agent = ShadowMonitorAgent(config, run_dir)
            agent.run()

            summary_path = os.path.join(
                run_dir, "ShadowMonitorAgent", "shadow_summary.json"
            )
            with open(summary_path) as f:
                summary = json.load(f)
            hashes.append(summary["content_hash_sha256"])

        assert hashes[0] == hashes[1], "Shadow summary hash not deterministic"
