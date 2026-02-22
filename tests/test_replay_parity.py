"""
Tests for tools/compare_runs.py — replay parity comparison.
Tests that compare_runs detects diffs and matches correctly.
"""

import json
import os

import numpy as np
import pandas as pd
import pytest

from data.snapshot_store import save_snapshot
from determinism import content_hash_sha256


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Create a realistic OHLCV DataFrame for testing."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n, freq="B")
    close = 100.0 + np.cumsum(rng.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "Open": close + rng.randn(n) * 0.1,
            "High": close + abs(rng.randn(n) * 0.5),
            "Low": close - abs(rng.randn(n) * 0.5),
            "Close": close,
            "Volume": rng.randint(1_000_000, 10_000_000, size=n),
        },
        index=dates,
    )
    df.index.name = None
    return df


def _create_json_artifact(path: str, data: dict):
    """Create a JSON artifact with embedded content hash."""
    data["content_hash_sha256"] = content_hash_sha256(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _setup_minimal_run(run_dir: str, metrics_data: dict = None,
                       seed: int = 42):
    """Create a minimal run directory with key artifacts for parity testing."""
    # DataAgent snapshot
    os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)
    df = _make_ohlcv(seed=seed)
    save_snapshot(df, run_dir)

    # BacktestAgent/metrics.json
    if metrics_data is None:
        metrics_data = {
            "EV_per_trade": 0.05,
            "max_drawdown": -0.12,
            "win_rate": 0.55,
            "num_trades": 42,
        }
    _create_json_artifact(
        os.path.join(run_dir, "BacktestAgent", "metrics.json"),
        metrics_data,
    )

    # DecisionRiskAgent/decision_action.json
    decision_data = {
        "action": "ABSTAIN",
        "position": 0,
        "reason": "test",
    }
    _create_json_artifact(
        os.path.join(run_dir, "DecisionRiskAgent", "decision_action.json"),
        decision_data,
    )

    # final_report.json
    report_data = {
        "ticker": "PLTR",
        "run_timestamp": "2026-02-22T00:00:00",
        "data": {},
        "backtest": {},
        "decision": {"decision_action": {"action": "ABSTAIN"}},
        "portfolio": {},
    }
    _create_json_artifact(
        os.path.join(run_dir, "final_report.json"),
        report_data,
    )


class TestCompareRunsMatch:
    """Tests that identical runs produce parity PASS."""

    def test_identical_runs_pass(self, tmp_path):
        from tools.compare_runs import compare_runs

        run_a = str(tmp_path / "run_a")
        run_b = str(tmp_path / "run_b")
        _setup_minimal_run(run_a)
        _setup_minimal_run(run_b)

        result = compare_runs(run_a, run_b, verbose=False)
        assert result["passed"] is True
        assert len(result["mismatches"]) == 0

    def test_snapshot_hash_match(self, tmp_path):
        from tools.compare_runs import compare_runs

        run_a = str(tmp_path / "run_a")
        run_b = str(tmp_path / "run_b")
        _setup_minimal_run(run_a, seed=42)
        _setup_minimal_run(run_b, seed=42)

        result = compare_runs(run_a, run_b, verbose=False)
        # DataAgent/data_snapshot.parquet should be in matches
        snap_matches = [
            m for m in result["matches"]
            if m["file"] == "DataAgent/data_snapshot.parquet"
        ]
        assert len(snap_matches) == 1


class TestCompareRunsMismatch:
    """Tests that differing runs produce parity FAIL."""

    def test_different_metrics_fail(self, tmp_path):
        from tools.compare_runs import compare_runs

        run_a = str(tmp_path / "run_a")
        run_b = str(tmp_path / "run_b")
        _setup_minimal_run(run_a, metrics_data={"EV_per_trade": 0.05})
        _setup_minimal_run(run_b, metrics_data={"EV_per_trade": 0.10})

        result = compare_runs(run_a, run_b, verbose=False)
        assert result["passed"] is False
        mismatch_files = [m["file"] for m in result["mismatches"]]
        assert "BacktestAgent/metrics.json" in mismatch_files

    def test_different_snapshot_data_fail(self, tmp_path):
        from tools.compare_runs import compare_runs

        run_a = str(tmp_path / "run_a")
        run_b = str(tmp_path / "run_b")
        _setup_minimal_run(run_a, seed=42)
        _setup_minimal_run(run_b, seed=99)  # Different data

        result = compare_runs(run_a, run_b, verbose=False)
        assert result["passed"] is False
        mismatch_files = [m["file"] for m in result["mismatches"]]
        assert "DataAgent/data_snapshot.parquet" in mismatch_files


class TestCompareRunsSkipped:
    """Tests for missing files handling."""

    def test_missing_file_skipped(self, tmp_path):
        from tools.compare_runs import compare_runs

        run_a = str(tmp_path / "run_a")
        run_b = str(tmp_path / "run_b")
        _setup_minimal_run(run_a)
        _setup_minimal_run(run_b)

        # Remove a file from run_b that's in PARITY_JSON_TARGETS
        # but not one we created (e.g., RobustnessAgent/summary.json)
        result = compare_runs(run_a, run_b, verbose=False)
        # RobustnessAgent artifacts should be in skipped
        skipped_files = [s["file"] for s in result["skipped"]]
        assert "RobustnessAgent/summary.json" in skipped_files


class TestHtmlTimestampIgnored:
    """final_report.html is excluded from parity comparison."""

    def test_html_with_different_timestamps_still_passes(self, tmp_path):
        """Differing HTML files must not cause parity failure."""
        from tools.compare_runs import compare_runs

        run_a = str(tmp_path / "run_a")
        run_b = str(tmp_path / "run_b")
        _setup_minimal_run(run_a)
        _setup_minimal_run(run_b)

        # Write different HTML to each run (simulates timestamp drift)
        for run_dir, ts in [(run_a, "2026-01-01"), (run_b, "2026-01-02")]:
            with open(os.path.join(run_dir, "final_report.html"), "w") as f:
                f.write(f"<html><body>Generated at {ts}</body></html>")

        result = compare_runs(run_a, run_b, verbose=False)
        # HTML must not appear in mismatches
        mismatch_files = [m["file"] for m in result["mismatches"]]
        assert "final_report.html" not in mismatch_files


class TestValidateRunHashCheck:
    """Tests for validate_run.py snapshot hash step."""

    def test_snapshot_hash_step(self, tmp_path):
        from validate_run import validate_snapshot_hash

        run_dir = str(tmp_path / "run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)
        df = _make_ohlcv()
        save_snapshot(df, run_dir)

        from pathlib import Path
        failures, warnings = validate_snapshot_hash(Path(run_dir))
        assert len(failures) == 0

    def test_snapshot_hash_mismatch_fails(self, tmp_path):
        from validate_run import validate_snapshot_hash
        from data.snapshot_store import snapshot_hash_path

        run_dir = str(tmp_path / "run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)
        df = _make_ohlcv()
        save_snapshot(df, run_dir)

        # Tamper with hash
        hp = snapshot_hash_path(run_dir)
        with open(hp, "w") as f:
            f.write("bad_hash\n")

        from pathlib import Path
        failures, warnings = validate_snapshot_hash(Path(run_dir))
        assert len(failures) > 0
        assert "mismatch" in failures[0].lower() or "Mismatch" in failures[0]

    def test_missing_snapshot_fails(self, tmp_path):
        from validate_run import validate_snapshot_hash
        from pathlib import Path

        run_dir = str(tmp_path / "empty_run")
        os.makedirs(run_dir, exist_ok=True)

        failures, warnings = validate_snapshot_hash(Path(run_dir))
        assert len(failures) > 0
