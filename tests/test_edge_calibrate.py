"""Tests for tools/edge_calibrate.py — threshold calibration.

Covers:
- Deterministic YAML output (same inputs → identical bytes)
- Refusal on no eligible runs (exit code 2)
- Calibrated thresholds within expected ranges
- YAML key set matches exactly the 11 expected keys
- Fixture-based calibration with known distributions
"""

import json
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.edge_calibrate import (
    MIN_ELIGIBLE_RUNS,
    MIN_PASS_LIKE_RUNS,
    MINIMUM_MEANINGFUL_FLOORS,
    _YAML_KEY_ORDER,
    calibrate_thresholds,
    collect_metrics,
    main,
    scan_eligible_runs,
    write_edge_yaml,
)
from tools.edge_validate import _DEFAULT_THRESHOLDS


# ============================================================
# Fixture helpers — create synthetic run directories
# ============================================================

def _make_trades(n=40, seed=42, r_values=None):
    """Build a synthetic trades DataFrame with r_multiple column."""
    rng = np.random.RandomState(seed)

    if r_values is not None:
        n = len(r_values)
        r_vals = np.array(r_values, dtype=float)
    else:
        r_vals = rng.randn(n) * 0.5 + 0.1

    if n == 0:
        return pd.DataFrame(columns=[
            "entry_date", "entry_price", "exit_date", "exit_price",
            "pnl", "return", "holding_days", "shares", "notional",
            "exposure_pct", "stop_distance", "stop_pct", "risk_budget",
            "r_multiple",
        ])

    dates = pd.bdate_range("2024-01-02", periods=n * 5, freq="B")
    rows = []
    for i in range(n):
        entry_i = i * 5
        exit_i = entry_i + rng.randint(1, 4)
        entry_price = 50.0 + rng.randn() * 5
        stop_dist = max(entry_price * 0.05, 0.5)
        risk_budget = 500.0
        shares = max(1, int(risk_budget / stop_dist))
        exit_price = entry_price + r_vals[i] * stop_dist
        pnl = (exit_price - entry_price) * shares
        rows.append({
            "entry_date": str(dates[entry_i].date()),
            "entry_price": round(entry_price, 4),
            "exit_date": str(dates[min(exit_i, len(dates) - 1)].date()),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 4),
            "return": round((exit_price / entry_price - 1) * 100, 4),
            "holding_days": exit_i - entry_i,
            "shares": shares,
            "notional": round(shares * entry_price, 4),
            "exposure_pct": 0.10,
            "stop_distance": round(stop_dist, 4),
            "stop_pct": round(stop_dist / entry_price, 4),
            "risk_budget": risk_budget,
            "r_multiple": round(r_vals[i], 6),
        })

    return pd.DataFrame(rows)


def _make_walk_forward(expectancies=None):
    if expectancies is None:
        expectancies = [0.01, 0.02, -0.005, 0.015, 0.008, 0.003]
    windows = [
        {"total_return": round(e * 100, 4), "max_dd": 0.05,
         "trades_count": 20, "win_rate": 0.55, "expectancy": e,
         "test_days": 60}
        for e in expectancies
    ]
    return {"windows": windows, "n_windows": len(windows)}


def _make_monte_carlo(dd_p95=0.15):
    return {
        "n_simulations": 1000, "n_trades": 40, "seed": 20260221,
        "final_return": {"mean": 0.10, "std": 0.05, "p5": 0.02, "p50": 0.10, "p95": 0.20},
        "max_drawdown": {"mean": 0.08, "std": 0.03, "p5": 0.03, "p50": 0.07, "p95": dd_p95},
    }


def _make_regime_contribution(buckets=None):
    if buckets is None:
        buckets = [
            {"regime": "normal", "count": 25, "mean_return": 0.02, "total_return": 0.5},
            {"regime": "quiet", "count": 10, "mean_return": 0.01, "total_return": 0.1},
        ]
    return {"buckets": buckets, "source": "volatility_regime"}


def _setup_fixture_run(
    base_dir,
    run_name,
    n_trades=40,
    seed=42,
    r_values=None,
    wf_expectancies=None,
    skip_artifact=None,
):
    """Create a single fixture run directory with required artifacts."""
    run_dir = os.path.join(base_dir, run_name)
    os.makedirs(os.path.join(run_dir, "BacktestAgent"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "RobustnessAgent"), exist_ok=True)

    trades = _make_trades(n=n_trades, seed=seed, r_values=r_values)
    wf = _make_walk_forward(expectancies=wf_expectancies)
    mc = _make_monte_carlo()
    rc = _make_regime_contribution()

    if skip_artifact != "trades":
        trades.to_parquet(
            os.path.join(run_dir, "BacktestAgent", "trades.parquet"),
            index=False,
        )
    if skip_artifact != "walk_forward":
        with open(os.path.join(run_dir, "RobustnessAgent", "walk_forward.json"), "w") as f:
            json.dump(wf, f)
    if skip_artifact != "monte_carlo":
        with open(os.path.join(run_dir, "RobustnessAgent", "monte_carlo.json"), "w") as f:
            json.dump(mc, f)
    if skip_artifact != "regime_contribution":
        with open(os.path.join(run_dir, "RobustnessAgent", "regime_contribution.json"), "w") as f:
            json.dump(rc, f)

    return run_dir


def _setup_diverse_runs(base_dir):
    """Create a set of fixture runs with diverse metric profiles.

    Returns the runs_root path.  Creates 12 runs (>= MIN_ELIGIBLE_RUNS)
    with varying trade counts and walk-forward expectancies.
    """
    runs_root = os.path.join(base_dir, "runs", "TEST")
    os.makedirs(runs_root, exist_ok=True)

    profiles = [
        {"name": "run_01", "n": 30, "seed": 1,
         "wf": [0.005, 0.01, -0.002, 0.008, 0.003, 0.001]},
        {"name": "run_02", "n": 35, "seed": 2,
         "wf": [0.01, 0.02, 0.005, 0.015, 0.008, 0.003]},
        {"name": "run_03", "n": 40, "seed": 3,
         "wf": [-0.005, 0.01, -0.01, 0.005, -0.002, 0.001]},
        {"name": "run_04", "n": 45, "seed": 4,
         "wf": [0.02, 0.03, 0.01, 0.025, 0.015, 0.01]},
        {"name": "run_05", "n": 50, "seed": 5,
         "wf": [0.005, 0.01, 0.002, 0.008, 0.003, 0.001]},
        {"name": "run_06", "n": 55, "seed": 6,
         "wf": [0.01, 0.015, 0.005, 0.012, 0.008, 0.003]},
        {"name": "run_07", "n": 60, "seed": 7,
         "wf": [0.008, 0.012, 0.003, 0.010, 0.006, 0.002]},
        {"name": "run_08", "n": 35, "seed": 8,
         "wf": [0.01, 0.02, -0.003, 0.015, 0.007, 0.004]},
        {"name": "run_09", "n": 40, "seed": 9,
         "wf": [0.005, 0.01, 0.001, 0.008, 0.004, 0.002]},
        {"name": "run_10", "n": 45, "seed": 10,
         "wf": [0.02, 0.015, 0.01, 0.018, 0.012, 0.008]},
        {"name": "run_11", "n": 50, "seed": 11,
         "wf": [0.01, 0.008, 0.005, 0.012, 0.006, 0.003]},
        {"name": "run_12", "n": 55, "seed": 12,
         "wf": [0.015, 0.02, 0.008, 0.018, 0.010, 0.005]},
    ]

    for p in profiles:
        _setup_fixture_run(
            runs_root, p["name"],
            n_trades=p["n"], seed=p["seed"],
            wf_expectancies=p["wf"],
        )

    return runs_root


def _setup_small_runs(base_dir, n_runs=3):
    """Create a small set of runs (below MIN_ELIGIBLE_RUNS).

    Returns the runs_root path.
    """
    runs_root = os.path.join(base_dir, "runs", "SMALL")
    os.makedirs(runs_root, exist_ok=True)

    for i in range(n_runs):
        _setup_fixture_run(
            runs_root, f"run_{i:02d}",
            n_trades=40, seed=100 + i,
            wf_expectancies=[0.01, 0.02, 0.005, 0.015, 0.008, 0.003],
        )

    return runs_root


# ============================================================
# TestScanEligibleRuns
# ============================================================


class TestScanEligibleRuns:

    def test_empty_dir(self, tmp_path):
        assert scan_eligible_runs(str(tmp_path / "nonexistent")) == []

    def test_skips_underscore_dirs(self, tmp_path):
        runs_root = str(tmp_path / "runs")
        _setup_fixture_run(runs_root, "_shadow_history", n_trades=10, seed=1)
        assert scan_eligible_runs(runs_root) == []

    def test_finds_eligible(self, tmp_path):
        runs_root = str(tmp_path / "runs")
        _setup_fixture_run(runs_root, "run_a", n_trades=10, seed=1)
        _setup_fixture_run(runs_root, "run_b", n_trades=20, seed=2)
        result = scan_eligible_runs(runs_root)
        assert len(result) == 2
        assert result == sorted(result)  # sorted

    def test_skips_incomplete_runs(self, tmp_path):
        runs_root = str(tmp_path / "runs")
        _setup_fixture_run(runs_root, "complete", n_trades=10, seed=1)
        _setup_fixture_run(runs_root, "missing_trades", n_trades=10, seed=2,
                           skip_artifact="trades")
        result = scan_eligible_runs(runs_root)
        assert len(result) == 1


# ============================================================
# TestCollectMetrics
# ============================================================


class TestCollectMetrics:

    def test_collects_from_valid_runs(self, tmp_path):
        runs_root = str(tmp_path / "runs")
        dir1 = _setup_fixture_run(runs_root, "run_1", n_trades=10, seed=1)
        dir2 = _setup_fixture_run(runs_root, "run_2", n_trades=20, seed=2)
        metrics = collect_metrics([dir1, dir2], roll_k=5)
        assert len(metrics) == 2
        assert metrics[0]["n"] == 10
        assert metrics[1]["n"] == 20

    def test_skips_invalid_runs(self, tmp_path):
        runs_root = str(tmp_path / "runs")
        dir1 = _setup_fixture_run(runs_root, "good", n_trades=10, seed=1)
        dir2 = _setup_fixture_run(runs_root, "bad", n_trades=10, seed=2,
                                  skip_artifact="trades")
        metrics = collect_metrics([dir1, dir2], roll_k=5)
        assert len(metrics) == 1


# ============================================================
# TestCalibrateThresholds
# ============================================================


class TestCalibrateThresholds:

    def test_yaml_key_set_complete(self, tmp_path):
        """Calibrated thresholds must have exactly the 11 expected keys."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)
        thresholds = result["thresholds"]
        assert set(thresholds.keys()) == set(_YAML_KEY_ORDER)
        assert len(thresholds) == 11

    def test_thresholds_within_ranges(self, tmp_path):
        """Calibrated values must be within allowed ranges."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)
        t = result["thresholds"]

        assert 30 <= t["n_min"] <= 100
        assert 0.0 <= t["e_min"]
        assert 1.0 <= t["pf_min"]
        assert 0.0 < t["mdd_max"] <= 15.0
        assert t["roll_k"] == 20
        assert 0.5 <= t["pos_roll_ratio_min"] <= 1.0
        assert 0.0 <= t["wf_e_min"]
        assert 0.5 <= t["wf_pos_folds_min"] <= 1.0
        assert t["roll_fail_streak"] == 5
        assert t["dd_shock"] == 10.0
        assert t["reset_streak"] == 3

    def test_structural_keys_unchanged(self, tmp_path):
        """Structural keys must equal defaults regardless of data."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)
        t = result["thresholds"]

        assert t["roll_k"] == _DEFAULT_THRESHOLDS["roll_k"]
        assert t["roll_fail_streak"] == _DEFAULT_THRESHOLDS["roll_fail_streak"]
        assert t["dd_shock"] == _DEFAULT_THRESHOLDS["dd_shock"]
        assert t["reset_streak"] == _DEFAULT_THRESHOLDS["reset_streak"]

    def test_n_min_uses_percentile(self, tmp_path):
        """n_min should use p25 of trade counts, not just the floor."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)

        # With N values [30..55], p25 >= 30; n_min must be >= floor
        assert result["thresholds"]["n_min"] >= MINIMUM_MEANINGFUL_FLOORS["n_min"]

    # ------------------------------------------------------------------
    # MINIMUM FLOOR ENFORCEMENT (new tests)
    # ------------------------------------------------------------------

    def test_n_min_never_below_floor(self, tmp_path):
        """Calibration must never output n_min < 30."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)
        assert result["thresholds"]["n_min"] >= MINIMUM_MEANINGFUL_FLOORS["n_min"]

    def test_pos_roll_ratio_min_never_below_floor(self, tmp_path):
        """Calibration must never output pos_roll_ratio_min < 0.5."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)
        assert (
            result["thresholds"]["pos_roll_ratio_min"]
            >= MINIMUM_MEANINGFUL_FLOORS["pos_roll_ratio_min"]
        )

    def test_wf_pos_folds_min_never_below_floor(self, tmp_path):
        """Calibration must never output wf_pos_folds_min < 0.5."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)
        assert (
            result["thresholds"]["wf_pos_folds_min"]
            >= MINIMUM_MEANINGFUL_FLOORS["wf_pos_folds_min"]
        )

    def test_floors_hold_even_with_degenerate_data(self, tmp_path):
        """Even with low-diversity metrics, floors must hold."""
        # Create runs where all pos_roll_ratio and wf_pos_folds are 0.0
        # (e.g., very few trades, N < roll_k)
        runs_root = os.path.join(str(tmp_path), "runs", "DEGEN")
        os.makedirs(runs_root, exist_ok=True)
        for i in range(12):
            _setup_fixture_run(
                runs_root, f"run_{i:02d}",
                n_trades=3, seed=200 + i,
                wf_expectancies=[0.01, 0.005, 0.001],
            )
        dirs = scan_eligible_runs(runs_root)
        # roll_k=20 means N=3 < roll_k → pos_roll_ratio = 0.0 for all
        metrics = collect_metrics(dirs, roll_k=20)
        result = calibrate_thresholds(metrics)
        t = result["thresholds"]

        assert t["n_min"] >= MINIMUM_MEANINGFUL_FLOORS["n_min"]
        assert t["pos_roll_ratio_min"] >= MINIMUM_MEANINGFUL_FLOORS["pos_roll_ratio_min"]
        assert t["wf_pos_folds_min"] >= MINIMUM_MEANINGFUL_FLOORS["wf_pos_folds_min"]


# ============================================================
# TestDeterminism
# ============================================================


class TestDeterminism:

    def test_identical_yaml_on_repeated_runs(self, tmp_path):
        """Same inputs must produce byte-identical YAML output."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)
        metrics = collect_metrics(dirs, roll_k=5)
        result = calibrate_thresholds(metrics)

        path1 = str(tmp_path / "out1.yaml")
        path2 = str(tmp_path / "out2.yaml")

        write_edge_yaml(result["thresholds"], path1)
        write_edge_yaml(result["thresholds"], path2)

        with open(path1, "rb") as f1, open(path2, "rb") as f2:
            assert f1.read() == f2.read()

    def test_calibration_deterministic(self, tmp_path):
        """Two calibration runs on same data produce identical thresholds."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        dirs = scan_eligible_runs(runs_root)

        m1 = collect_metrics(dirs, roll_k=5)
        m2 = collect_metrics(dirs, roll_k=5)

        r1 = calibrate_thresholds(m1)
        r2 = calibrate_thresholds(m2)

        assert r1["thresholds"] == r2["thresholds"]


# ============================================================
# TestNoEligibleRuns
# ============================================================


class TestNoEligibleRuns:

    def test_exit_code_2_no_runs(self, tmp_path):
        """No eligible runs → exit code 2."""
        out = str(tmp_path / "edge.yaml")
        exit_code = main([
            "--ticker", "EMPTY",
            "--runs-root", str(tmp_path / "nonexistent"),
            "--out", out,
        ])
        assert exit_code == 2
        assert not os.path.exists(out)

    def test_exit_code_2_only_incomplete(self, tmp_path):
        """Only incomplete runs → exit code 2."""
        runs_root = str(tmp_path / "runs")
        _setup_fixture_run(runs_root, "bad1", skip_artifact="trades")
        _setup_fixture_run(runs_root, "bad2", skip_artifact="walk_forward")

        exit_code = main([
            "--ticker", "TEST",
            "--runs-root", runs_root,
            "--out", str(tmp_path / "edge.yaml"),
        ])
        assert exit_code == 2


# ============================================================
# TestSufficiencyGate
# ============================================================


class TestSufficiencyGate:
    """Eligibility sufficiency gate: too few runs → exit 2, no overwrite."""

    def test_insufficient_eligible_runs_exit_2(self, tmp_path):
        """Fewer than MIN_ELIGIBLE_RUNS eligible runs → exit 2."""
        runs_root = _setup_small_runs(str(tmp_path), n_runs=3)
        out_yaml = str(tmp_path / "edge.yaml")

        exit_code = main([
            "--runs-root", runs_root,
            "--out", out_yaml,
        ])

        assert exit_code == 2
        assert not os.path.exists(out_yaml)

    def test_insufficient_eligible_runs_no_overwrite(self, tmp_path):
        """config/edge.yaml must not be modified when eligibility fails."""
        runs_root = _setup_small_runs(str(tmp_path), n_runs=3)
        out_yaml = str(tmp_path / "edge.yaml")

        # Pre-create the file with known content
        os.makedirs(os.path.dirname(out_yaml) or ".", exist_ok=True)
        sentinel = "# sentinel: do not overwrite\n"
        with open(out_yaml, "w") as f:
            f.write(sentinel)

        exit_code = main([
            "--runs-root", runs_root,
            "--out", out_yaml,
        ])

        assert exit_code == 2
        with open(out_yaml) as f:
            assert f.read() == sentinel

    def test_insufficient_eligible_runs_writes_report(self, tmp_path):
        """Diagnostic report is still written even when eligibility fails."""
        runs_root = _setup_small_runs(str(tmp_path), n_runs=3)
        out_yaml = str(tmp_path / "edge.yaml")
        out_report = str(tmp_path / "report.json")

        exit_code = main([
            "--runs-root", runs_root,
            "--out", out_yaml,
            "--report", out_report,
        ])

        assert exit_code == 2
        assert not os.path.exists(out_yaml)
        assert os.path.exists(out_report)

        with open(out_report) as f:
            report = json.load(f)
        assert report.get("rejected") is True
        assert "rejection_reason" in report


# ============================================================
# TestCLI
# ============================================================


class TestCLI:

    def test_full_pipeline(self, tmp_path):
        """End-to-end: scan → calibrate → write YAML + report."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        out_yaml = str(tmp_path / "edge.yaml")
        out_report = str(tmp_path / "report.json")

        exit_code = main([
            "--ticker", "TEST",
            "--runs-root", runs_root,
            "--out", out_yaml,
            "--report", out_report,
        ])

        assert exit_code == 0
        assert os.path.exists(out_yaml)
        assert os.path.exists(out_report)

        # Verify YAML is loadable
        import yaml
        with open(out_yaml) as f:
            data = yaml.safe_load(f)
        assert "edge_gates" in data
        gates = data["edge_gates"]
        assert set(gates.keys()) == set(_YAML_KEY_ORDER)

        # Verify report is valid JSON
        with open(out_report) as f:
            report = json.load(f)
        assert report["eligible_runs"] == 12
        assert "thresholds" in report
        assert "calibration_details" in report

    def test_yaml_keys_match_default_thresholds(self, tmp_path):
        """Output YAML key set must match edge_validate._DEFAULT_THRESHOLDS."""
        runs_root = _setup_diverse_runs(str(tmp_path))
        out_yaml = str(tmp_path / "edge.yaml")

        main(["--runs-root", runs_root, "--out", out_yaml])

        import yaml
        with open(out_yaml) as f:
            data = yaml.safe_load(f)

        yaml_keys = set(data["edge_gates"].keys())
        default_keys = set(_DEFAULT_THRESHOLDS.keys())
        assert yaml_keys == default_keys, (
            f"Key mismatch: YAML has {yaml_keys - default_keys} extra, "
            f"missing {default_keys - yaml_keys}"
        )
