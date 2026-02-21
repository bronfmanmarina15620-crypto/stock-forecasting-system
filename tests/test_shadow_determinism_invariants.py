"""
Shadow-mode determinism invariants.

Fast (<0.2 s) guardrail tests that fail if:
  - timestamp_utc is non-deterministic (wall-clock)
  - content_hash_sha256 is missing from shadow artifacts
  - content_hash_sha256 doesn't verify on reload
"""

import json
import os

from agents.shadow_monitor_agent import ShadowMonitorAgent
from determinism import content_hash_sha256


# ── helpers ──────────────────────────────────────────────────


def _make_config(ticker="TEST"):
    from config import SystemConfig, BacktestConfig, StrategyConfig
    return SystemConfig(
        ticker=ticker,
        strategy=StrategyConfig(
            atr_length=14, atr_mult=3.0, slope_lookback=20,
            entry_lookback=20, atr_pct_high=0.04, slope_min=0.0,
            risk_per_trade=0.005,
        ),
        backtest=BacktestConfig(
            capital_base=100000.0, max_leverage=1.0,
            max_position_pct=0.25, min_stop_pct=0.01,
            max_stop_pct=0.20, commission_pct=0.001,
            spread_bps=2.0, slippage_bps=3.0,
        ),
    )


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _setup_run(run_dir):
    _write_json(
        os.path.join(run_dir, "DecisionRiskAgent", "decision_action.json"),
        {"action": "ABSTAIN", "date": "2026-02-21",
         "content_hash_sha256": "x"},
    )
    _write_json(
        os.path.join(run_dir, "StrategyAgent", "output.json"),
        {"status": "SUCCESS", "ma150_distance_pct": 0.03, "atr_latest": 2.5},
    )
    _write_json(
        os.path.join(run_dir, "RegimeAgent", "output.json"),
        {"status": "SUCCESS", "recent_regime": "TREND_LOW_VOL"},
    )
    _write_json(
        os.path.join(run_dir, "BacktestAgent", "metrics.json"),
        {"total_return": 0.15, "content_hash_sha256": "x"},
    )


# ── invariant tests ──────────────────────────────────────────


class TestTimestampUtcDeterministic:
    """timestamp_utc must equal asof_date + T00:00:00+00:00."""

    def test_timestamp_utc_derived_from_asof_date(self, tmp_path):
        run_dir = str(tmp_path / "runs" / "TEST" / "20260221_120000_abc123")
        os.makedirs(run_dir)
        _setup_run(run_dir)

        agent = ShadowMonitorAgent(_make_config(), run_dir)
        agent.run()

        with open(os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_metrics.json"
        )) as f:
            metrics = json.load(f)

        expected = metrics["asof_date"] + "T00:00:00+00:00"
        assert metrics["timestamp_utc"] == expected, (
            f"timestamp_utc must be deterministic: "
            f"got {metrics['timestamp_utc']!r}, expected {expected!r}"
        )

    def test_timestamp_utc_stable_across_runs(self, tmp_path):
        """Two runs with identical inputs produce identical timestamp_utc."""
        values = []
        for i in range(2):
            run_dir = str(tmp_path / "runs" / "TEST" / f"20260221_12000{i}_x{i}")
            os.makedirs(run_dir)
            _setup_run(run_dir)
            ShadowMonitorAgent(_make_config(), run_dir).run()
            with open(os.path.join(
                run_dir, "ShadowMonitorAgent", "shadow_metrics.json"
            )) as f:
                values.append(json.load(f)["timestamp_utc"])
        assert values[0] == values[1]


class TestContentHashPresent:
    """Both shadow artifacts must contain a valid content_hash_sha256."""

    def test_shadow_metrics_hash_present_and_valid(self, tmp_path):
        run_dir = str(tmp_path / "runs" / "TEST" / "20260221_120000_hsh001")
        os.makedirs(run_dir)
        _setup_run(run_dir)
        ShadowMonitorAgent(_make_config(), run_dir).run()

        with open(os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_metrics.json"
        )) as f:
            data = json.load(f)

        assert "content_hash_sha256" in data
        assert data["content_hash_sha256"] == content_hash_sha256(data)

    def test_shadow_summary_hash_present_and_valid(self, tmp_path):
        run_dir = str(tmp_path / "runs" / "TEST" / "20260221_120000_hsh002")
        os.makedirs(run_dir)
        _setup_run(run_dir)
        ShadowMonitorAgent(_make_config(), run_dir).run()

        with open(os.path.join(
            run_dir, "ShadowMonitorAgent", "shadow_summary.json"
        )) as f:
            data = json.load(f)

        assert "content_hash_sha256" in data
        assert data["content_hash_sha256"] == content_hash_sha256(data)
