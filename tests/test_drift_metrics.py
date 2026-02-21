"""
Tests for analytics/drift_metrics.py — deterministic unit tests.
"""

import json
import os
import tempfile

import pandas as pd
import pytest

from analytics.drift_metrics import (
    build_timeseries_row,
    compute_decision_distribution,
    compute_drift_summary,
    compute_zscore,
    discover_eligible_runs,
    extract_run_row,
    load_history,
)


# ── Z-score tests ───────────────────────────────────────────────────


class TestComputeZscore:
    """Deterministic z-score unit tests."""

    def test_basic_zscore(self):
        """Z-score of value from known distribution."""
        history = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        # mean = 30, std ≈ 15.811
        z = compute_zscore(30.0, history)
        assert z is not None
        assert abs(z) < 1e-10  # z-score of mean = 0

    def test_zscore_above_mean(self):
        """Positive z-score for above-mean value."""
        history = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        z = compute_zscore(60.0, history)
        assert z is not None
        assert z > 0

    def test_zscore_below_mean(self):
        """Negative z-score for below-mean value."""
        history = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        z = compute_zscore(0.0, history)
        assert z is not None
        assert z < 0

    def test_zscore_none_value(self):
        """None input -> None output."""
        history = pd.Series([1.0, 2.0, 3.0])
        assert compute_zscore(None, history) is None

    def test_zscore_nan_value(self):
        """NaN input -> None output."""
        history = pd.Series([1.0, 2.0, 3.0])
        assert compute_zscore(float("nan"), history) is None

    def test_zscore_insufficient_history(self):
        """History with < 2 values -> None."""
        assert compute_zscore(5.0, pd.Series([1.0])) is None
        assert compute_zscore(5.0, pd.Series(dtype=float)) is None

    def test_zscore_zero_std(self):
        """All same values -> std=0 -> None."""
        history = pd.Series([5.0, 5.0, 5.0, 5.0])
        assert compute_zscore(5.0, history) is None

    def test_zscore_with_nans_in_history(self):
        """NaN values in history are dropped before computation."""
        history = pd.Series([10.0, None, 20.0, None, 30.0])
        z = compute_zscore(20.0, history)
        assert z is not None
        assert abs(z) < 1e-10  # 20 is the mean of [10, 20, 30]


# ── Decision distribution tests ─────────────────────────────────────


class TestDecisionDistribution:

    def test_basic_distribution(self):
        df = pd.DataFrame({"decision": ["ENTER", "ABSTAIN", "ABSTAIN", "ENTER"]})
        dist = compute_decision_distribution(df)
        assert abs(dist["ENTER"] - 0.5) < 1e-10
        assert abs(dist["ABSTAIN"] - 0.5) < 1e-10
        assert abs(dist["EXIT"] - 0.0) < 1e-10

    def test_empty_dataframe(self):
        df = pd.DataFrame({"decision": []})
        dist = compute_decision_distribution(df)
        assert dist["ENTER"] == 0.0
        assert dist["ABSTAIN"] == 0.0

    def test_all_enter(self):
        df = pd.DataFrame({"decision": ["ENTER"] * 10})
        dist = compute_decision_distribution(df)
        assert abs(dist["ENTER"] - 1.0) < 1e-10
        assert dist["ABSTAIN"] == 0.0


# ── Drift summary tests ─────────────────────────────────────────────


class TestComputeDriftSummary:

    def test_insufficient_history(self):
        """Fewer than min_k runs -> INSUFFICIENT_HISTORY."""
        history = pd.DataFrame({
            "run_id": ["run1", "run2"],
            "run_ts": ["2026-01-01T00:00:00", "2026-01-02T00:00:00"],
            "decision": ["ABSTAIN", "ENTER"],
            "confidence": [None, None],
            "ma150_slope": [None, None],
            "atr_percentile": [None, None],
        })
        latest = {
            "run_id": "run3",
            "run_ts": "2026-01-03T00:00:00",
            "decision": "ABSTAIN",
            "confidence": None,
            "ma150_slope": None,
            "atr_percentile": None,
        }
        summary = compute_drift_summary(history, latest, window_k=60, min_k=30)
        assert summary["drift_status"] == "INSUFFICIENT_HISTORY"
        assert summary["overall_drift_flag"] == "OK"
        assert summary["schema_version"] == "1.0"
        assert summary["history_window_used"] == 2

    def test_ok_status_with_no_drift(self):
        """Enough history, no extreme z-scores -> OK."""
        n = 35
        history = pd.DataFrame({
            "run_id": [f"run_{i}" for i in range(n)],
            "run_ts": [f"2026-01-{i+1:02d}T00:00:00" for i in range(n)],
            "decision": ["ABSTAIN"] * n,
            "confidence": [None] * n,
            "ma150_slope": [None] * n,
            "atr_percentile": [1.0 + i * 0.01 for i in range(n)],
        })
        latest = {
            "run_id": "latest",
            "decision": "ABSTAIN",
            "confidence": None,
            "ma150_slope": None,
            "atr_percentile": 1.17,  # near the mean
        }
        summary = compute_drift_summary(history, latest, window_k=60, min_k=30)
        assert summary["drift_status"] == "OK"
        assert summary["overall_drift_flag"] == "OK"

    def test_warn_flag_on_extreme_zscore(self):
        """Z-score >= 2.0 triggers WARN."""
        n = 35
        vals = [1.0] * n
        history = pd.DataFrame({
            "run_id": [f"run_{i}" for i in range(n)],
            "run_ts": [f"2026-01-{i+1:02d}T00:00:00" for i in range(n)],
            "decision": ["ABSTAIN"] * n,
            "confidence": [None] * n,
            "ma150_slope": [None] * n,
            "atr_percentile": vals,
        })
        # Give slight variation so std > 0
        history.loc[0, "atr_percentile"] = 1.01

        latest = {
            "run_id": "latest",
            "decision": "ABSTAIN",
            "confidence": None,
            "ma150_slope": None,
            "atr_percentile": 5.0,  # extreme outlier
        }
        summary = compute_drift_summary(history, latest, window_k=60, min_k=30)
        assert summary["drift_status"] == "OK"
        assert summary["overall_drift_flag"] == "WARN"
        assert summary["atr_percentile_drift_zscore"] is not None
        assert abs(summary["atr_percentile_drift_zscore"]) >= 2.0


# ── History discovery tests ──────────────────────────────────────────


class TestDiscoverEligibleRuns:

    def _create_run(self, ticker_dir, run_id, status="SUCCESS", has_decision=True,
                    has_summary=True):
        """Create a minimal fake run directory."""
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)

        # run_summary.json
        if has_summary:
            with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                json.dump({"status": status}, f)

        # decision_action.json
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)

        return run_dir

    def test_discovers_eligible_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_aaaaaa")
            self._create_run(tmpdir, "20260102_000000_bbbbbb")
            self._create_run(tmpdir, "20260103_000000_cccccc", status="FAILED")
            self._create_run(tmpdir, "20260104_000000_dddddd", has_decision=False)

            eligible, coverage = discover_eligible_runs(tmpdir, "current_run")
            assert len(eligible) == 2
            assert "20260101_000000_aaaaaa" in eligible
            assert "20260102_000000_bbbbbb" in eligible

    def test_excludes_current_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_aaaaaa")
            eligible, _ = discover_eligible_runs(tmpdir, "20260101_000000_aaaaaa")
            assert len(eligible) == 0

    def test_excludes_hidden_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "_shadow_history"))
            self._create_run(tmpdir, "20260101_000000_aaaaaa")
            eligible, _ = discover_eligible_runs(tmpdir, "other")
            assert len(eligible) == 1

    def test_empty_ticker_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            eligible, coverage = discover_eligible_runs(tmpdir, "current")
            assert eligible == []
            assert coverage["total_scanned"] == 0

    def test_nonexistent_ticker_dir(self):
        eligible, coverage = discover_eligible_runs("/nonexistent/path", "current")
        assert eligible == []
        assert coverage["total_scanned"] == 0


# ── Extract run row tests ────────────────────────────────────────────


class TestExtractRunRow:

    def test_extract_with_decision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = tmpdir
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ENTER", "confidence": 0.85}, f)

            row = extract_run_row(run_dir, "20260101_000000_aaaaaa")
            assert row["decision"] == "ENTER"
            assert row["confidence"] == 0.85
            assert row["run_id"] == "20260101_000000_aaaaaa"
            assert row["run_ts"] == "2026-01-01T00:00:00"

    def test_extract_missing_decision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            row = extract_run_row(tmpdir, "20260101_000000_aaaaaa")
            assert row["decision"] is None
            assert row["confidence"] is None

    def test_extract_with_regime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Decision
            dec_dir = os.path.join(tmpdir, "DecisionRiskAgent")
            os.makedirs(dec_dir)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)

            # Volatility regime
            vr_dir = os.path.join(tmpdir, "VolatilityRegimeAgent")
            os.makedirs(vr_dir)
            with open(os.path.join(vr_dir, "regime_latest.json"), "w") as f:
                json.dump({"atr_ratio": 0.95, "atr_slope": -0.02}, f)

            row = extract_run_row(tmpdir, "20260215_120000_xyzabc")
            assert row["atr_percentile"] == 0.95
            assert row["ma150_slope"] == -0.02


# ── Build timeseries row tests ───────────────────────────────────────


class TestBuildTimeseriesRow:

    def test_basic(self):
        latest = {
            "run_id": "r1",
            "run_ts": "2026-01-01T00:00:00",
            "decision": "ENTER",
            "confidence": None,
            "ma150_slope": None,
            "atr_percentile": 1.1,
        }
        summary = {
            "confidence_mean_zscore": None,
            "ma150_slope_drift_zscore": None,
            "atr_percentile_drift_zscore": 0.5,
            "overall_drift_flag": "OK",
        }
        row = build_timeseries_row(latest, summary)
        assert row["run_id"] == "r1"
        assert row["overall_flag"] == "OK"
        assert row["atr_percentile_zscore"] == 0.5


# ── Integration test: INSUFFICIENT_HISTORY with few fake runs ────────


class TestIntegrationInsufficientHistory:
    """Create 3 fake runs and check INSUFFICIENT_HISTORY behavior."""

    def test_three_runs_insufficient(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 3 fake runs
            for i in range(3):
                run_id = f"2026020{i+1}_000000_aaa00{i}"
                run_dir = os.path.join(tmpdir, run_id)
                os.makedirs(os.path.join(run_dir, "DecisionRiskAgent"))
                with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                    json.dump({"status": "SUCCESS"}, f)
                with open(os.path.join(run_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                    json.dump({"action": "ABSTAIN", "because": ["test"]}, f)

            # Current run
            current_id = "20260204_000000_cur001"
            current_dir = os.path.join(tmpdir, current_id)
            os.makedirs(os.path.join(current_dir, "DecisionRiskAgent"))
            with open(os.path.join(current_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                json.dump({"action": "ENTER"}, f)

            # Discover
            eligible, coverage = discover_eligible_runs(tmpdir, current_id)
            assert len(eligible) == 3

            # Load history
            history_df = load_history(tmpdir, eligible)
            assert len(history_df) == 3

            # Extract current
            latest_row = extract_run_row(current_dir, current_id)

            # Compute
            summary = compute_drift_summary(
                history_df, latest_row, window_k=60, min_k=30,
                coverage=coverage,
            )
            assert summary["drift_status"] == "INSUFFICIENT_HISTORY"
            assert summary["overall_drift_flag"] == "OK"
            assert summary["history_window_used"] == 3
            assert summary["schema_version"] == "1.0"
            # Coverage fields populated even with insufficient history
            assert summary["eligible_runs_found"] == 3
            assert summary["runs_used_in_window"] == 3
            assert summary["runs_excluded"] == 0

    def test_five_runs_with_custom_min_k(self):
        """With min_k=3, 5 runs should be OK."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(5):
                run_id = f"2026020{i+1}_000000_aaa00{i}"
                run_dir = os.path.join(tmpdir, run_id)
                os.makedirs(os.path.join(run_dir, "DecisionRiskAgent"))
                with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                    json.dump({"status": "SUCCESS"}, f)
                with open(os.path.join(run_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                    json.dump({"action": "ABSTAIN", "because": ["test"]}, f)

            current_id = "20260206_000000_cur001"
            current_dir = os.path.join(tmpdir, current_id)
            os.makedirs(os.path.join(current_dir, "DecisionRiskAgent"))
            with open(os.path.join(current_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)

            eligible, coverage = discover_eligible_runs(tmpdir, current_id)
            history_df = load_history(tmpdir, eligible)
            latest_row = extract_run_row(current_dir, current_id)
            summary = compute_drift_summary(
                history_df, latest_row, window_k=60, min_k=3,
                coverage=coverage,
            )
            assert summary["drift_status"] == "OK"
            assert summary["history_window_used"] == 5
            assert summary["eligible_runs_found"] == 5
            assert summary["runs_used_in_window"] == 5


# ── Coverage tracking tests ───────────────────────────────────────────


class TestCoverageTracking:
    """Tests for coverage counting and reason bucketing."""

    def _create_run(self, ticker_dir, run_id, status="SUCCESS",
                    has_decision=True, has_summary=True):
        """Create a minimal fake run directory."""
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        if has_summary:
            with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                json.dump({"status": status}, f)
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)
        return run_dir

    def test_coverage_counts_add_up(self):
        """eligible + excluded == total_scanned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_aaaaaa")  # eligible
            self._create_run(tmpdir, "20260102_000000_bbbbbb")  # eligible
            self._create_run(tmpdir, "20260103_000000_cccccc", status="FAILED")
            self._create_run(tmpdir, "20260104_000000_dddddd", has_decision=False)

            _, coverage = discover_eligible_runs(tmpdir, "current_run")
            assert coverage["total_scanned"] == 4
            assert coverage["eligible_runs_found"] == 2
            assert coverage["runs_excluded"] == 2
            assert coverage["eligible_runs_found"] + coverage["runs_excluded"] == coverage["total_scanned"]

    def test_not_success_bucket(self):
        """FAILED runs count under not_success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_aaaaaa", status="FAILED")
            self._create_run(tmpdir, "20260102_000000_bbbbbb", status="ERROR")

            _, coverage = discover_eligible_runs(tmpdir, "current")
            assert coverage["excluded_reasons"]["not_success"] == 2
            assert coverage["runs_excluded"] == 2

    def test_missing_decision_bucket(self):
        """Runs without decision_action.json count under missing_decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_aaaaaa", has_decision=False)

            _, coverage = discover_eligible_runs(tmpdir, "current")
            assert coverage["excluded_reasons"]["missing_decision"] == 1

    def test_missing_summary_counts_as_not_success(self):
        """Runs without run_summary.json or status.txt -> not_success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_aaaaaa",
                             has_summary=False, has_decision=True)

            _, coverage = discover_eligible_runs(tmpdir, "current")
            assert coverage["excluded_reasons"]["not_success"] == 1

    def test_all_eligible_zero_excluded(self):
        """All valid -> excluded = 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                self._create_run(tmpdir, f"2026010{i+1}_000000_aaa00{i}")

            _, coverage = discover_eligible_runs(tmpdir, "current")
            assert coverage["eligible_runs_found"] == 3
            assert coverage["runs_excluded"] == 0
            assert coverage["total_scanned"] == 3

    def test_coverage_has_all_reason_keys(self):
        """Coverage dict always includes all expected reason keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, coverage = discover_eligible_runs(tmpdir, "current")
            expected_keys = {
                "not_success", "missing_decision",
                "missing_required_artifacts", "validate_failed", "other",
            }
            assert set(coverage["excluded_reasons"].keys()) == expected_keys

    def test_coverage_embedded_in_drift_summary(self):
        """compute_drift_summary includes coverage when passed."""
        history = pd.DataFrame({
            "run_id": ["r1", "r2"],
            "run_ts": ["2026-01-01T00:00:00", "2026-01-02T00:00:00"],
            "decision": ["ABSTAIN", "ENTER"],
            "confidence": [None, None],
            "ma150_slope": [None, None],
            "atr_percentile": [None, None],
        })
        latest = {
            "run_id": "r3", "decision": "ABSTAIN",
            "confidence": None, "ma150_slope": None, "atr_percentile": None,
        }
        cov = {
            "total_scanned": 5,
            "eligible_runs_found": 2,
            "runs_excluded": 3,
            "excluded_reasons": {
                "not_success": 2, "missing_decision": 1,
                "missing_required_artifacts": 0, "validate_failed": 0, "other": 0,
            },
        }
        summary = compute_drift_summary(
            history, latest, window_k=60, min_k=30, coverage=cov,
        )
        assert summary["eligible_runs_found"] == 2
        assert summary["runs_used_in_window"] == 2
        assert summary["runs_excluded"] == 3
        assert summary["excluded_reasons"]["not_success"] == 2
        assert summary["excluded_reasons"]["missing_decision"] == 1

    def test_coverage_absent_when_not_passed(self):
        """compute_drift_summary without coverage omits coverage keys."""
        history = pd.DataFrame({
            "run_id": ["r1"], "run_ts": ["2026-01-01T00:00:00"],
            "decision": ["ABSTAIN"], "confidence": [None],
            "ma150_slope": [None], "atr_percentile": [None],
        })
        latest = {
            "run_id": "r2", "decision": "ABSTAIN",
            "confidence": None, "ma150_slope": None, "atr_percentile": None,
        }
        summary = compute_drift_summary(history, latest, window_k=60, min_k=30)
        assert "eligible_runs_found" not in summary
        assert "runs_used_in_window" not in summary


# ── Integration: mixed failures coverage ──────────────────────────────


class TestIntegrationMixedFailuresCoverage:
    """5 fake runs with mixed failures; verify coverage buckets."""

    def _create_run(self, ticker_dir, run_id, status="SUCCESS",
                    has_decision=True, has_summary=True):
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        if has_summary:
            with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                json.dump({"status": status}, f)
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)
        return run_dir

    def test_five_mixed_runs(self):
        """Create 5 runs: 2 eligible, 1 FAILED, 1 missing decision, 1 no summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 2 eligible
            self._create_run(tmpdir, "20260101_000000_ok0001")
            self._create_run(tmpdir, "20260102_000000_ok0002")
            # 1 FAILED
            self._create_run(tmpdir, "20260103_000000_fail01", status="FAILED")
            # 1 missing decision
            self._create_run(tmpdir, "20260104_000000_nodec1", has_decision=False)
            # 1 no summary at all
            self._create_run(tmpdir, "20260105_000000_nosum1",
                             has_summary=False, has_decision=True)

            current_id = "20260106_000000_cur001"

            eligible, coverage = discover_eligible_runs(tmpdir, current_id)

            # Eligible: ok0001, ok0002
            assert len(eligible) == 2
            assert coverage["eligible_runs_found"] == 2
            assert coverage["total_scanned"] == 5
            assert coverage["runs_excluded"] == 3

            # Reason buckets
            reasons = coverage["excluded_reasons"]
            assert reasons["not_success"] == 2  # FAILED + no summary
            assert reasons["missing_decision"] == 1
            assert reasons["missing_required_artifacts"] == 0
            assert reasons["validate_failed"] == 0
            assert reasons["other"] == 0

            # Invariant: eligible + excluded == scanned
            assert coverage["eligible_runs_found"] + coverage["runs_excluded"] == coverage["total_scanned"]

            # Now run the full flow and verify drift_summary has coverage
            history_df = load_history(tmpdir, eligible)
            # Build a current run dir for extract_run_row
            current_dir = os.path.join(tmpdir, current_id)
            os.makedirs(os.path.join(current_dir, "DecisionRiskAgent"), exist_ok=True)
            with open(os.path.join(current_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                json.dump({"action": "ENTER"}, f)
            latest_row = extract_run_row(current_dir, current_id)

            summary = compute_drift_summary(
                history_df, latest_row, window_k=60, min_k=30,
                coverage=coverage,
            )
            assert summary["eligible_runs_found"] == 2
            assert summary["runs_used_in_window"] == 2
            assert summary["runs_excluded"] == 3
            assert summary["excluded_reasons"]["not_success"] == 2
            assert summary["excluded_reasons"]["missing_decision"] == 1


# ── Hardening tests: identities, bounds, ordering, regression ─────


class TestCoverageIdentities:
    """Assert mathematical invariants hold by construction."""

    def _create_run(self, ticker_dir, run_id, status="SUCCESS",
                    has_decision=True, has_summary=True, corrupt_json=False):
        """Create a minimal fake run directory."""
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        if has_summary:
            path = os.path.join(run_dir, "run_summary.json")
            with open(path, "w") as f:
                if corrupt_json:
                    f.write("{invalid json!!!}")
                else:
                    json.dump({"status": status}, f)
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)
        return run_dir

    def test_identity_scanned_eq_eligible_plus_excluded(self):
        """total_scanned == eligible_runs_found + runs_excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mix: 3 eligible, 2 FAILED, 1 missing decision
            for i in range(3):
                self._create_run(tmpdir, f"2026010{i+1}_000000_ok000{i}")
            self._create_run(tmpdir, "20260104_000000_fail01", status="FAILED")
            self._create_run(tmpdir, "20260105_000000_fail02", status="FAILED")
            self._create_run(tmpdir, "20260106_000000_nodec1", has_decision=False)

            eligible, cov = discover_eligible_runs(tmpdir, "current")
            assert cov["total_scanned"] == cov["eligible_runs_found"] + cov["runs_excluded"]
            assert cov["total_scanned"] == 6
            assert cov["eligible_runs_found"] == 3
            assert cov["runs_excluded"] == 3

    def test_identity_excluded_eq_sum_reasons(self):
        """runs_excluded == sum(excluded_reasons.values())."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_fail01", status="FAILED")
            self._create_run(tmpdir, "20260102_000000_nodec1", has_decision=False)
            self._create_run(tmpdir, "20260103_000000_nosum1",
                             has_summary=False, has_decision=True)
            self._create_run(tmpdir, "20260104_000000_ok0001")

            _, cov = discover_eligible_runs(tmpdir, "current")
            assert cov["runs_excluded"] == sum(cov["excluded_reasons"].values())

    def test_identity_used_lte_eligible(self):
        """runs_used_in_window <= eligible_runs_found (via compute_drift_summary)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(5):
                self._create_run(tmpdir, f"2026010{i+1}_000000_ok000{i}")

            eligible, cov = discover_eligible_runs(tmpdir, "current")
            history_df = load_history(tmpdir, eligible)
            latest = {
                "run_id": "current", "decision": "ABSTAIN",
                "confidence": None, "ma150_slope": None, "atr_percentile": None,
            }
            # window_k=3 means only last 3 of 5 eligible are used
            summary = compute_drift_summary(
                history_df, latest, window_k=3, min_k=2, coverage=cov,
            )
            assert summary["runs_used_in_window"] <= summary["eligible_runs_found"]
            assert summary["runs_used_in_window"] == 3
            assert summary["eligible_runs_found"] == 5

    def test_identities_hold_empty_dir(self):
        """Identities hold even with zero runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, cov = discover_eligible_runs(tmpdir, "current")
            assert cov["total_scanned"] == 0
            assert cov["eligible_runs_found"] == 0
            assert cov["runs_excluded"] == 0
            assert cov["total_scanned"] == cov["eligible_runs_found"] + cov["runs_excluded"]
            assert cov["runs_excluded"] == sum(cov["excluded_reasons"].values())


class TestSampleBounds:
    """Assert debug sample lists are bounded."""

    def _create_run(self, ticker_dir, run_id, status="SUCCESS",
                    has_decision=True, has_summary=True):
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        if has_summary:
            with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                json.dump({"status": status}, f)
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)
        return run_dir

    def test_excluded_ids_sample_capped_at_10(self):
        """excluded_run_ids_sample never exceeds 10."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 15 FAILED runs -> 15 excluded
            for i in range(15):
                self._create_run(tmpdir, f"202601{i+1:02d}_000000_fail{i:02d}",
                                 status="FAILED")

            _, cov = discover_eligible_runs(tmpdir, "current")
            assert cov["runs_excluded"] == 15
            assert len(cov["excluded_run_ids_sample"]) <= 10
            assert len(cov["excluded_run_ids_sample"]) == 10

    def test_per_reason_sample_capped_at_5(self):
        """Per-reason sample lists never exceed 5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 8 runs missing decision
            for i in range(8):
                self._create_run(tmpdir, f"202601{i+1:02d}_000000_nod0{i:02d}",
                                 has_decision=False)

            _, cov = discover_eligible_runs(tmpdir, "current")
            assert cov["excluded_reasons"]["missing_decision"] == 8
            assert len(
                cov["excluded_run_ids_by_reason_sample"]["missing_decision"]
            ) <= 5

    def test_sample_bounds_with_mixed_reasons(self):
        """Multiple reason types each independently capped at 5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 7 FAILED + 6 missing decision = 13 excluded total
            for i in range(7):
                self._create_run(tmpdir, f"202601{i+1:02d}_000000_fai0{i:02d}",
                                 status="FAILED")
            for i in range(6):
                self._create_run(tmpdir, f"202602{i+1:02d}_000000_nod0{i:02d}",
                                 has_decision=False)

            _, cov = discover_eligible_runs(tmpdir, "current")
            assert cov["runs_excluded"] == 13
            assert len(cov["excluded_run_ids_sample"]) == 10  # capped
            by_reason = cov["excluded_run_ids_by_reason_sample"]
            assert len(by_reason["not_success"]) == 5  # capped from 7
            assert len(by_reason["missing_decision"]) == 5  # capped from 6


class TestDeterministicOrdering:
    """Assert sample lists are deterministically sorted ascending."""

    def _create_run(self, ticker_dir, run_id, status="SUCCESS",
                    has_decision=True, has_summary=True):
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        if has_summary:
            with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                json.dump({"status": status}, f)
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)
        return run_dir

    def test_excluded_ids_sorted_ascending(self):
        """excluded_run_ids_sample is sorted ascending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create runs with IDs that would sort differently if not sorted
            ids = [
                "20260105_000000_zzz001",
                "20260101_000000_aaa001",
                "20260103_000000_mmm001",
                "20260102_000000_bbb001",
                "20260104_000000_nnn001",
            ]
            for rid in ids:
                self._create_run(tmpdir, rid, status="FAILED")

            _, cov = discover_eligible_runs(tmpdir, "current")
            sample = cov["excluded_run_ids_sample"]
            assert sample == sorted(sample)

    def test_per_reason_sample_sorted_ascending(self):
        """Per-reason sample lists are sorted ascending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ids = [
                "20260103_000000_zzz001",
                "20260101_000000_aaa001",
                "20260102_000000_bbb001",
            ]
            for rid in ids:
                self._create_run(tmpdir, rid, has_decision=False)

            _, cov = discover_eligible_runs(tmpdir, "current")
            sample = cov["excluded_run_ids_by_reason_sample"]["missing_decision"]
            assert sample == sorted(sample)

    def test_deterministic_across_calls(self):
        """Two calls with same input produce identical samples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(5):
                self._create_run(tmpdir, f"202601{i+1:02d}_000000_fail{i:02d}",
                                 status="FAILED")

            _, cov1 = discover_eligible_runs(tmpdir, "current")
            _, cov2 = discover_eligible_runs(tmpdir, "current")
            assert cov1["excluded_run_ids_sample"] == cov2["excluded_run_ids_sample"]
            assert (cov1["excluded_run_ids_by_reason_sample"]
                    == cov2["excluded_run_ids_by_reason_sample"])


class TestCorruptJsonRegression:
    """Corrupt/missing JSON in historical runs must never crash,
    and must increment the correct exclusion bucket."""

    def _create_run(self, ticker_dir, run_id, status="SUCCESS",
                    has_decision=True, has_summary=True, corrupt_json=False):
        run_dir = os.path.join(ticker_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        if has_summary:
            path = os.path.join(run_dir, "run_summary.json")
            with open(path, "w") as f:
                if corrupt_json:
                    f.write("{invalid json!!!}")
                else:
                    json.dump({"status": status}, f)
        if has_decision:
            dec_dir = os.path.join(run_dir, "DecisionRiskAgent")
            os.makedirs(dec_dir, exist_ok=True)
            with open(os.path.join(dec_dir, "decision_action.json"), "w") as f:
                json.dump({"action": "ABSTAIN", "because": ["test"]}, f)
        return run_dir

    def test_corrupt_run_summary_json(self):
        """Corrupt run_summary.json -> not_success bucket, no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_ok0001")
            self._create_run(tmpdir, "20260102_000000_corrupt",
                             corrupt_json=True, has_decision=True)

            eligible, cov = discover_eligible_runs(tmpdir, "current")
            assert len(eligible) == 1
            assert "20260101_000000_ok0001" in eligible
            assert cov["runs_excluded"] == 1
            assert cov["excluded_reasons"]["not_success"] == 1
            assert "20260102_000000_corrupt" in cov["excluded_run_ids_sample"]

    def test_corrupt_json_identity_holds(self):
        """Identities hold even with corrupt JSON runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_run(tmpdir, "20260101_000000_ok0001")
            self._create_run(tmpdir, "20260102_000000_corrupt1",
                             corrupt_json=True)
            self._create_run(tmpdir, "20260103_000000_corrupt2",
                             corrupt_json=True)
            self._create_run(tmpdir, "20260104_000000_nodec01",
                             has_decision=False)

            _, cov = discover_eligible_runs(tmpdir, "current")
            # Identity: scanned = eligible + excluded
            assert cov["total_scanned"] == cov["eligible_runs_found"] + cov["runs_excluded"]
            # Identity: excluded = sum(reasons)
            assert cov["runs_excluded"] == sum(cov["excluded_reasons"].values())
            # Specific counts
            assert cov["eligible_runs_found"] == 1
            assert cov["excluded_reasons"]["not_success"] == 2
            assert cov["excluded_reasons"]["missing_decision"] == 1

    def test_empty_run_dir_no_summary_no_decision(self):
        """Run dir with no files at all -> not_success bucket."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "20260101_000000_empty1"))
            self._create_run(tmpdir, "20260102_000000_ok0001")

            eligible, cov = discover_eligible_runs(tmpdir, "current")
            assert len(eligible) == 1
            assert cov["runs_excluded"] == 1
            assert cov["excluded_reasons"]["not_success"] == 1


# ── drift_reason_summary tests ────────────────────────────────────────


class TestDriftReasonSummary:
    """Tests for the drift_reason_summary one-liner."""

    def _make_summary(self, drift_status="OK", flag="OK", min_k=30,
                      conf_z=None, slope_z=None, atr_z=None):
        """Build a minimal summary dict for testing _build_reason_summary."""
        from analytics.drift_metrics import _build_reason_summary
        summary = {
            "drift_status": drift_status,
            "overall_drift_flag": flag,
            "history_window_min_required": min_k,
            "confidence_mean_zscore": conf_z,
            "ma150_slope_drift_zscore": slope_z,
            "atr_percentile_drift_zscore": atr_z,
        }
        return _build_reason_summary(summary)

    def test_ok_case(self):
        result = self._make_summary()
        assert result == "OK: no 2-sigma drift detected"

    def test_insufficient_history(self):
        result = self._make_summary(drift_status="INSUFFICIENT_HISTORY", min_k=30)
        assert result == "STATUS=INSUFFICIENT_HISTORY (need >=30 runs)"

    def test_insufficient_history_custom_min_k(self):
        result = self._make_summary(drift_status="INSUFFICIENT_HISTORY", min_k=10)
        assert result == "STATUS=INSUFFICIENT_HISTORY (need >=10 runs)"

    def test_error_status(self):
        result = self._make_summary(drift_status="ERROR")
        assert result == "STATUS=ERROR"

    def test_warn_single_trigger(self):
        result = self._make_summary(flag="WARN", atr_z=2.5)
        assert "WARN:" in result
        assert "atr_percentile z=+2.5" in result
        assert "confidence" not in result
        assert "ma150_slope" not in result

    def test_warn_multiple_triggers_stable_order(self):
        """Ordering is always: confidence, ma150_slope, atr_percentile."""
        result = self._make_summary(flag="WARN", conf_z=2.3, slope_z=-2.1, atr_z=3.0)
        assert result.startswith("WARN: ")
        parts = result[len("WARN: "):]
        items = [p.strip() for p in parts.split(";")]
        assert len(items) == 3
        assert items[0].startswith("confidence")
        assert items[1].startswith("ma150_slope")
        assert items[2].startswith("atr_percentile")

    def test_warn_skips_non_triggering_zscores(self):
        """Only z-scores with |z| >= 2 appear."""
        result = self._make_summary(flag="WARN", conf_z=2.5, slope_z=1.0)
        assert "confidence z=+2.5" in result
        assert "ma150_slope" not in result

    def test_truncation_at_120_chars(self):
        from analytics.drift_metrics import _build_reason_summary, _MAX_REASON_SUMMARY_LEN
        # Force a very long WARN message by building directly
        summary = {
            "drift_status": "OK",
            "overall_drift_flag": "WARN",
            "confidence_mean_zscore": 2.123456789012345,
            "ma150_slope_drift_zscore": -2.987654321098765,
            "atr_percentile_drift_zscore": 3.111111111111111,
        }
        result = _build_reason_summary(summary)
        assert len(result) <= _MAX_REASON_SUMMARY_LEN

    def test_present_in_compute_drift_summary(self):
        """compute_drift_summary always includes drift_reason_summary."""
        history = pd.DataFrame({
            "run_id": [f"run_{i}" for i in range(35)],
            "run_ts": [f"2026-01-{i+1:02d}T00:00:00" for i in range(35)],
            "decision": ["ABSTAIN"] * 35,
            "confidence": [None] * 35,
            "ma150_slope": [None] * 35,
            "atr_percentile": [None] * 35,
        })
        latest = {
            "run_id": "latest", "decision": "ABSTAIN",
            "confidence": None, "ma150_slope": None, "atr_percentile": None,
        }
        summary = compute_drift_summary(history, latest, window_k=60, min_k=30)
        assert "drift_reason_summary" in summary
        assert isinstance(summary["drift_reason_summary"], str)
        assert len(summary["drift_reason_summary"]) <= 130

    def test_integration_summary_in_full_flow(self):
        """Full integration: discover + load + compute includes reason summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                run_id = f"2026020{i+1}_000000_aaa00{i}"
                run_dir = os.path.join(tmpdir, run_id)
                os.makedirs(os.path.join(run_dir, "DecisionRiskAgent"))
                with open(os.path.join(run_dir, "run_summary.json"), "w") as f:
                    json.dump({"status": "SUCCESS"}, f)
                with open(os.path.join(run_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                    json.dump({"action": "ABSTAIN", "because": ["test"]}, f)

            current_id = "20260204_000000_cur001"
            current_dir = os.path.join(tmpdir, current_id)
            os.makedirs(os.path.join(current_dir, "DecisionRiskAgent"))
            with open(os.path.join(current_dir, "DecisionRiskAgent", "decision_action.json"), "w") as f:
                json.dump({"action": "ENTER"}, f)

            eligible, cov = discover_eligible_runs(tmpdir, current_id)
            history_df = load_history(tmpdir, eligible)
            latest_row = extract_run_row(current_dir, current_id)
            summary = compute_drift_summary(
                history_df, latest_row, window_k=60, min_k=30, coverage=cov,
            )
            assert "drift_reason_summary" in summary
            # 3 runs < min_k=30 -> INSUFFICIENT_HISTORY
            assert "INSUFFICIENT_HISTORY" in summary["drift_reason_summary"]
