"""
Tests for artifacts/contract.py — artifact contract definitions,
schema validation, and decision enum enforcement.
"""

import json
import os

import pytest

from artifacts.contract import (
    CONTENT_HASH_TARGETS,
    CRITICAL_ARTIFACTS,
    FINAL_REPORT_REQUIRED_KEYS,
    METRICS_REQUIRED_KEYS,
    OPTIONAL_ARTIFACTS,
    PARITY_IGNORE,
    PARITY_JSON_TARGETS,
    PARITY_RAW_TARGETS,
    STATUS_JSON_REQUIRED_KEYS,
    SUMMARY_REQUIRED_KEYS,
    VALID_DECISIONS,
)


class TestCriticalArtifacts:
    """Tests for CRITICAL_ARTIFACTS list."""

    def test_not_empty(self):
        assert len(CRITICAL_ARTIFACTS) > 0

    def test_snapshot_included(self):
        assert "DataAgent/data_snapshot.parquet" in CRITICAL_ARTIFACTS
        assert "DataAgent/snapshot_hash.txt" in CRITICAL_ARTIFACTS

    def test_backtest_artifacts_included(self):
        assert "BacktestAgent/metrics.json" in CRITICAL_ARTIFACTS
        assert "BacktestAgent/trades.parquet" in CRITICAL_ARTIFACTS

    def test_decision_artifacts_included(self):
        assert "DecisionRiskAgent/decision_action.json" in CRITICAL_ARTIFACTS

    def test_root_artifacts_included(self):
        assert "final_report.json" in CRITICAL_ARTIFACTS
        assert "final_report.html" in CRITICAL_ARTIFACTS
        assert "status.json" in CRITICAL_ARTIFACTS
        assert "_meta.json" in CRITICAL_ARTIFACTS
        assert "run_summary.json" in CRITICAL_ARTIFACTS

    def test_no_duplicates(self):
        assert len(CRITICAL_ARTIFACTS) == len(set(CRITICAL_ARTIFACTS))


class TestOptionalArtifacts:
    """Tests for OPTIONAL_ARTIFACTS list."""

    def test_no_overlap_with_critical(self):
        overlap = set(CRITICAL_ARTIFACTS) & set(OPTIONAL_ARTIFACTS)
        assert overlap == set(), f"Overlap: {overlap}"


class TestContentHashTargets:
    """Tests for CONTENT_HASH_TARGETS list."""

    def test_all_are_json(self):
        for target in CONTENT_HASH_TARGETS:
            assert target.endswith(".json"), f"{target} is not .json"

    def test_metrics_included(self):
        assert "BacktestAgent/metrics.json" in CONTENT_HASH_TARGETS

    def test_final_report_included(self):
        assert "final_report.json" in CONTENT_HASH_TARGETS

    def test_decision_action_included(self):
        assert "DecisionRiskAgent/decision_action.json" in CONTENT_HASH_TARGETS


class TestValidDecisions:
    """Tests for VALID_DECISIONS enum."""

    def test_known_values(self):
        assert "ENTER" in VALID_DECISIONS
        assert "ABSTAIN" in VALID_DECISIONS
        assert "EXIT" in VALID_DECISIONS
        assert "UNKNOWN" in VALID_DECISIONS

    def test_no_unexpected_values(self):
        assert len(VALID_DECISIONS) == 4

    def test_invalid_rejected(self):
        assert "BUY" not in VALID_DECISIONS
        assert "SELL" not in VALID_DECISIONS
        assert "" not in VALID_DECISIONS


class TestSchemaKeys:
    """Tests for schema required keys lists."""

    def test_metrics_keys_not_empty(self):
        assert len(METRICS_REQUIRED_KEYS) > 0

    def test_final_report_keys_not_empty(self):
        assert len(FINAL_REPORT_REQUIRED_KEYS) > 0

    def test_status_json_keys_not_empty(self):
        assert len(STATUS_JSON_REQUIRED_KEYS) > 0

    def test_summary_keys_not_empty(self):
        assert len(SUMMARY_REQUIRED_KEYS) > 0


class TestParityTargets:
    """Tests for parity comparison target lists."""

    def test_json_targets_are_json(self):
        for t in PARITY_JSON_TARGETS:
            assert t.endswith(".json"), f"{t} is not .json"

    def test_raw_targets_not_json(self):
        for t in PARITY_RAW_TARGETS:
            assert not t.endswith(".json"), f"{t} should not be .json"

    def test_snapshot_in_raw_targets(self):
        assert "DataAgent/data_snapshot.parquet" in PARITY_RAW_TARGETS


class TestParityIgnore:
    """Tests for PARITY_IGNORE list."""

    def test_html_report_ignored(self):
        """final_report.html contains timestamps — must be ignored."""
        assert "final_report.html" in PARITY_IGNORE

    def test_html_not_in_parity_targets(self):
        """final_report.html must not be in any parity comparison list."""
        assert "final_report.html" not in PARITY_JSON_TARGETS
        assert "final_report.html" not in PARITY_RAW_TARGETS

    def test_volatile_files_ignored(self):
        for f in ["status.txt", "status.json", "_meta.json", "run_summary.json"]:
            assert f in PARITY_IGNORE, f"{f} should be in PARITY_IGNORE"


class TestContractConsistency:
    """Cross-list consistency checks."""

    def test_parity_json_targets_are_critical_or_optional(self):
        """Every parity JSON target must be declared in the contract."""
        all_known = set(CRITICAL_ARTIFACTS) | set(OPTIONAL_ARTIFACTS)
        for t in PARITY_JSON_TARGETS:
            assert t in all_known, f"{t} in PARITY_JSON_TARGETS but not in contract"

    def test_content_hash_targets_subset_of_parity_json(self):
        """Content hash targets should all be included in parity JSON comparison."""
        parity_set = set(PARITY_JSON_TARGETS)
        for t in CONTENT_HASH_TARGETS:
            assert t in parity_set, f"{t} in CONTENT_HASH_TARGETS but not in PARITY_JSON_TARGETS"


class TestAbstainNoTradeContract:
    """ABSTAIN/no-trade scenarios must not violate the artifact contract."""

    def test_abstain_decision_is_valid(self):
        assert "ABSTAIN" in VALID_DECISIONS

    def test_optional_artifacts_missing_does_not_break_critical(self):
        """Missing optional artifacts must never appear in the critical list."""
        for opt in OPTIONAL_ARTIFACTS:
            assert opt not in CRITICAL_ARTIFACTS, (
                f"{opt} is in BOTH optional and critical lists"
            )

    def test_regime_dependent_artifacts_are_optional(self):
        """Shadow/drift artifacts are optional — a no-trade regime must not fail."""
        regime_dependent = [
            "ShadowMonitorAgent/shadow_metrics.json",
            "ShadowMonitorAgent/shadow_summary.json",
            "DriftAgent/drift_summary.json",
        ]
        for art in regime_dependent:
            assert art in OPTIONAL_ARTIFACTS, (
                f"{art} should be OPTIONAL, not CRITICAL"
            )
            assert art not in CRITICAL_ARTIFACTS, (
                f"{art} is in CRITICAL but should be OPTIONAL"
            )
