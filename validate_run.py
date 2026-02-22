#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_run.py - Strict validator for stock forecasting system runs

Usage:
    python validate_run.py --run runs/PLTR/20260214_151806_xaji0y

Exit Codes:
    0 = PASS (all validations passed)
    1 = FAIL (one or more validations failed)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

from determinism import CONTENT_HASH_KEY, content_hash_sha256
from data.snapshot_store import verify_snapshot_hash, snapshot_path
from artifacts.contract import (
    CRITICAL_ARTIFACTS,
    OPTIONAL_ARTIFACTS,
    CONTENT_HASH_TARGETS as _CONTRACT_HASH_TARGETS,
    SHADOW_HASH_TARGETS as _CONTRACT_SHADOW_TARGETS,
)

try:
    import pyarrow.parquet as pq
    PYARROW_AVAILABLE = True
except ImportError:
    pq = None
    PYARROW_AVAILABLE = False


# ============================================================
# CONFIGURATION
# ============================================================

REQUIRED_ARTIFACTS = {
    "BacktestAgent": [
        "trades.parquet",
        "pnl_series.parquet",
        "metrics.json",
        "costs_assumptions.json",
        "risk_explain.json",
    ],
    "DecisionRiskAgent": [
        "signals.csv",
        "abstain_stats.json",
        "decision_action.json",
        "decision_explain.json",
    ],
    "RobustnessAgent": [
        "summary.json",
        "monte_carlo.json",
    ],
    # final_report.html/json are saved to run root by DashboardAgent
    "_ROOT_": [
        "status.txt",
        "status.json",
        "config.json",
        "config_snapshot.yaml",
        "final_report.html",
        "final_report.json",
    ],
}

REQUIRED_METRICS_FIELDS = [
    "EV_per_trade",
    "max_drawdown",
    "win_rate",
    "avg_trades_per_month",
    # Phase 3
    "total_return",
    "cagr",
    "sharpe",
    "exposure_time_pct",
    "num_trades",
    "days_regime_ok_pct",
    "days_range_high_vol_pct",
    # Phase 4 risk
    "avg_exposure_pct",
    "max_exposure_pct",
    "avg_r_multiple",
    "median_r_multiple",
    "worst_r_multiple",
    "best_r_multiple",
    "pct_trades_skipped_due_to_stop_bounds",
    "pct_trades_capped_by_max_position",
    "realized_risk_per_trade_avg",
]

REQUIRED_ABSTAIN_STATS_FIELDS = [
    "abstain_ratio",
    "enter_count",
    "abstain_count",
    "signals_per_month",
]

SANITY_THRESHOLDS = {
    "shuffled_labels_auc_max": 0.55,
    "future_shift_auc_max": 0.55,
}

MIN_OOS_ROWS_WARN = 250

FINAL_REPORT_REQUIRED_KEYS = [
    "ticker",
    "run_timestamp",
    "data",
    "backtest",
    "decision",
    "portfolio",
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_file_exists(path: Path, fail_reasons: List[str]) -> bool:
    """Check if file exists and add to fail_reasons if not."""
    if not path.exists():
        fail_reasons.append(f"Missing file: {path}")
        return False
    return True


SHADOW_ARTIFACTS = {
    "ShadowMonitorAgent": [
        "shadow_metrics.json",
        "shadow_summary.json",
    ],
}

# DriftAgent artifacts — validated only when the folder exists.
DRIFT_ARTIFACTS = {
    "DriftAgent": [
        "drift_summary.json",
    ],
}


def validate_artifacts(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate that all required artifacts exist.

    Uses the canonical contract from artifacts/contract.py:
      - CRITICAL_ARTIFACTS → missing = FAIL
      - OPTIONAL_ARTIFACTS → missing = WARN (informational)
    Shadow/Drift artifacts are validated only when their folder exists.
    """
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 1: Checking Required Artifacts")
    print("=" * 60)

    # --- CRITICAL artifacts (FAIL on missing) ---
    print("\n  CRITICAL artifacts:")
    for relpath in CRITICAL_ARTIFACTS:
        filepath = run_path / relpath
        if filepath.exists():
            print(f"  [OK] {relpath}")
        else:
            fail_reasons.append(f"Missing CRITICAL artifact: {relpath}")
            print(f"  [X]  {relpath}")

    # --- Shadow artifacts (FAIL only when folder exists) ---
    shadow_dir = run_path / "ShadowMonitorAgent"
    if shadow_dir.exists():
        print("\n  Shadow artifacts (folder present):")
        for folder, files in SHADOW_ARTIFACTS.items():
            for filename in files:
                filepath = run_path / folder / filename
                if filepath.exists():
                    print(f"  [OK] {folder}/{filename}")
                else:
                    fail_reasons.append(f"Missing shadow artifact: {folder}/{filename}")
                    print(f"  [X]  {folder}/{filename}")

    # --- Drift artifacts (FAIL only when folder exists) ---
    drift_dir = run_path / "DriftAgent"
    if drift_dir.exists():
        print("\n  Drift artifacts (folder present):")
        for folder, files in DRIFT_ARTIFACTS.items():
            for filename in files:
                filepath = run_path / folder / filename
                if filepath.exists():
                    print(f"  [OK] {folder}/{filename}")
                else:
                    fail_reasons.append(f"Missing drift artifact: {folder}/{filename}")
                    print(f"  [X]  {folder}/{filename}")

    # --- OPTIONAL artifacts (WARN on missing) ---
    print("\n  OPTIONAL artifacts:")
    for relpath in OPTIONAL_ARTIFACTS:
        filepath = run_path / relpath
        if filepath.exists():
            print(f"  [OK] {relpath}")
        else:
            warnings.append(f"Missing OPTIONAL artifact: {relpath}")
            print(f"  [--] {relpath}")

    return fail_reasons, warnings


def validate_sanity_tests(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate sanity tests from sanity_tests.json."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 2: Validating Sanity Tests")
    print("=" * 60)

    # Search legacy_ml/ subfolder first, then top-level (backward compat)
    sanity_path = run_path / "BacktestAgent" / "legacy_ml" / "sanity_tests.json"
    if not sanity_path.exists():
        sanity_path = run_path / "BacktestAgent" / "sanity_tests.json"
    if not sanity_path.exists():
        warnings.append("sanity_tests.json not found (legacy ML artifacts optional)")
        print("[!] sanity_tests.json not found (legacy ML artifacts optional)")
        return fail_reasons, warnings

    try:
        sanity = load_json(sanity_path)

        # Check if skipped (insufficient data)
        if sanity.get('status') == 'SKIPPED':
            reason = sanity.get('reason', 'unknown')
            warnings.append(f"Sanity tests skipped: {reason}")
            print(f"[!] Sanity tests skipped: {reason}")
            return fail_reasons, warnings

        # Extract AUC values (support both flat and nested structure)
        shuffled_auc = sanity.get("shuffled_labels_auc")
        future_auc = sanity.get("future_shift_auc")

        # Fallback to nested structure
        if shuffled_auc is None and isinstance(sanity.get("shuffled_labels"), dict):
            shuffled_auc = sanity["shuffled_labels"].get("auc")
        if future_auc is None and isinstance(sanity.get("future_shift"), dict):
            future_auc = sanity["future_shift"].get("auc")

        # Validate shuffled labels test
        if shuffled_auc is None:
            fail_reasons.append("sanity_tests.json missing shuffled_labels_auc")
            print("[X] Missing shuffled_labels_auc")
        else:
            shuffled_auc = float(shuffled_auc)
            threshold = SANITY_THRESHOLDS["shuffled_labels_auc_max"]
            if shuffled_auc > threshold:
                fail_reasons.append(
                    f"Sanity FAIL: shuffled_labels_auc={shuffled_auc:.3f} > {threshold}"
                )
                print(f"[X] Shuffled labels AUC: {shuffled_auc:.3f} (FAIL - should be <= {threshold})")
            else:
                print(f"[OK] Shuffled labels AUC: {shuffled_auc:.3f} (PASS)")

        # Validate future shift test
        if future_auc is None:
            fail_reasons.append("sanity_tests.json missing future_shift_auc")
            print("[X] Missing future_shift_auc")
        else:
            future_auc = float(future_auc)
            threshold = SANITY_THRESHOLDS["future_shift_auc_max"]
            if future_auc > threshold:
                fail_reasons.append(
                    f"Sanity FAIL: future_shift_auc={future_auc:.3f} > {threshold}"
                )
                print(f"[X] Future shift AUC: {future_auc:.3f} (FAIL - should be <= {threshold})")
            else:
                print(f"[OK] Future shift AUC: {future_auc:.3f} (PASS)")

    except Exception as e:
        fail_reasons.append(f"Failed parsing sanity_tests.json: {e}")
        print(f"[X] Error parsing sanity_tests.json: {e}")

    return fail_reasons, warnings


def validate_metrics(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate metrics.json has required fields."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 3: Validating Metrics")
    print("=" * 60)

    metrics_path = run_path / "BacktestAgent" / "metrics.json"

    if not metrics_path.exists():
        fail_reasons.append(f"Missing metrics.json: {metrics_path}")
        print("[X] metrics.json not found")
        return fail_reasons, warnings

    try:
        metrics = load_json(metrics_path)

        print("\nRequired fields:")
        for field_name in REQUIRED_METRICS_FIELDS:
            if field_name in metrics:
                value = metrics[field_name]
                print(f"  [OK] {field_name}: {value}")
            else:
                fail_reasons.append(f"metrics.json missing field: {field_name}")
                print(f"  [X] {field_name}: MISSING")

    except Exception as e:
        fail_reasons.append(f"Failed parsing metrics.json: {e}")
        print(f"[X] Error parsing metrics.json: {e}")

    return fail_reasons, warnings


def validate_abstain_stats(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate abstain_stats.json has required fields."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 4: Validating Abstain Statistics")
    print("=" * 60)

    abstain_path = run_path / "DecisionRiskAgent" / "abstain_stats.json"

    if not abstain_path.exists():
        fail_reasons.append(f"Missing abstain_stats.json: {abstain_path}")
        print("[X] abstain_stats.json not found")
        return fail_reasons, warnings

    try:
        stats = load_json(abstain_path)

        print("\nRequired fields:")
        for field_name in REQUIRED_ABSTAIN_STATS_FIELDS:
            if field_name in stats:
                value = stats[field_name]
                print(f"  [OK] {field_name}: {value}")
            else:
                fail_reasons.append(f"abstain_stats.json missing field: {field_name}")
                print(f"  [X] {field_name}: MISSING")

    except Exception as e:
        fail_reasons.append(f"Failed parsing abstain_stats.json: {e}")
        print(f"[X] Error parsing abstain_stats.json: {e}")

    return fail_reasons, warnings


def validate_oos_samples(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate OOS sample count."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 5: Validating OOS Sample Size")
    print("=" * 60)

    # Search legacy_ml/ subfolder first, then top-level (backward compat)
    pred_path = run_path / "BacktestAgent" / "legacy_ml" / "predictions_oos.parquet"
    if not pred_path.exists():
        pred_path = run_path / "BacktestAgent" / "predictions_oos.parquet"
    if not pred_path.exists():
        warnings.append("predictions_oos.parquet not found (legacy ML artifacts optional)")
        print("[!] predictions_oos.parquet not found (legacy ML artifacts optional)")
        return fail_reasons, warnings

    if not PYARROW_AVAILABLE:
        warnings.append("pyarrow not installed; cannot count OOS rows")
        print("[!] pyarrow not installed - cannot verify row count")
        return fail_reasons, warnings

    try:
        table = pq.read_table(pred_path)
        oos_rows = table.num_rows

        print(f"\nOOS rows: {oos_rows}")

        if oos_rows < MIN_OOS_ROWS_WARN:
            warnings.append(
                f"INSUFFICIENT_OOS_SAMPLES: {oos_rows} rows (< {MIN_OOS_ROWS_WARN} recommended)"
            )
            print(f"[!] WARNING: Only {oos_rows} OOS samples (< {MIN_OOS_ROWS_WARN} recommended)")
        else:
            print(f"[OK] Sufficient OOS samples (>= {MIN_OOS_ROWS_WARN})")

    except Exception as e:
        fail_reasons.append(f"Failed reading predictions_oos.parquet: {e}")
        print(f"[X] Error reading predictions_oos.parquet: {e}")

    return fail_reasons, warnings


def validate_final_report_schema(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate final_report.json schema."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 6: Validating final_report.json Schema")
    print("=" * 60)

    report_path = run_path / "final_report.json"

    if not report_path.exists():
        fail_reasons.append(f"Missing final_report.json: {report_path}")
        print("[X] final_report.json not found")
        return fail_reasons, warnings

    try:
        report = load_json(report_path)

        for key in FINAL_REPORT_REQUIRED_KEYS:
            if key in report:
                print(f"  [OK] {key}: present")
            else:
                fail_reasons.append(f"final_report.json missing key: {key}")
                print(f"  [X] {key}: MISSING")

        # Validate decision action
        if 'decision' in report:
            decision = report['decision']
            if 'decision_action' in decision:
                action = decision['decision_action']
                if 'action' in action:
                    if action['action'] in ('ENTER', 'ABSTAIN'):
                        print(f"  [OK] decision.action: {action['action']}")
                    else:
                        fail_reasons.append(
                            f"Invalid action: {action['action']} (must be ENTER or ABSTAIN)"
                        )
                        print(f"  [X] Invalid action: {action['action']}")

    except Exception as e:
        fail_reasons.append(f"Failed parsing final_report.json: {e}")
        print(f"[X] Error parsing final_report.json: {e}")

    return fail_reasons, warnings


def validate_status_json(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate status.json structure."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 7: Validating status.json")
    print("=" * 60)

    status_path = run_path / "status.json"

    if not status_path.exists():
        fail_reasons.append(f"Missing status.json: {status_path}")
        print("[X] status.json not found")
        return fail_reasons, warnings

    try:
        status = load_json(status_path)

        required_keys = ['overall_status', 'ticker', 'timestamp', 'stages', 'integrity']
        for key in required_keys:
            if key in status:
                val = status[key]
                display = val if not isinstance(val, dict) else 'present'
                print(f"  [OK] {key}: {display}")
            else:
                fail_reasons.append(f"status.json missing key: {key}")
                print(f"  [X] {key}: MISSING")

        if status.get('integrity') == 'RED':
            fail_reasons.append("Integrity is RED")
            print("  [X] Integrity: RED")

    except Exception as e:
        fail_reasons.append(f"Failed parsing status.json: {e}")
        print(f"[X] Error parsing status.json: {e}")

    return fail_reasons, warnings


# Files covered by the content_hash_sha256 integrity check.
# Paths are relative to the run directory.
_CONTENT_HASH_TARGETS = [
    "BacktestAgent/metrics.json",
    "final_report.json",
    "DecisionRiskAgent/decision_action.json",
    "RobustnessAgent/summary.json",
    "RobustnessAgent/monte_carlo.json",
    "RobustnessAgent/walk_forward.json",
    "RobustnessAgent/sensitivity_map.json",
    "RobustnessAgent/exposure_decomposition.json",
    "RobustnessAgent/regime_contribution.json",
    "RobustnessAgent/capacity_test.json",
]

# Shadow-mode hash targets — validated only when present.
_SHADOW_HASH_TARGETS = [
    "ShadowMonitorAgent/shadow_metrics.json",
    "ShadowMonitorAgent/shadow_summary.json",
]


def validate_content_hashes(run_path: Path) -> Tuple[List[str], List[str]]:
    """Verify that embedded content_hash_sha256 matches recomputed hash."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 8: Validating content_hash_sha256 Integrity")
    print("=" * 60)

    # Include shadow targets when their folder exists
    targets = list(_CONTENT_HASH_TARGETS)
    if (run_path / "ShadowMonitorAgent").exists():
        targets.extend(_SHADOW_HASH_TARGETS)

    for relpath in targets:
        filepath = run_path / relpath
        if not filepath.exists():
            # Missing files are already caught by validate_artifacts
            print(f"  [--] {relpath}: skipped (file missing)")
            continue

        try:
            data = load_json(filepath)
        except Exception as e:
            fail_reasons.append(f"{relpath}: failed to parse JSON: {e}")
            print(f"  [X] {relpath}: failed to parse JSON: {e}")
            continue

        stored = data.get(CONTENT_HASH_KEY)
        if stored is None:
            fail_reasons.append(
                f"{relpath}: missing {CONTENT_HASH_KEY} field"
            )
            print(f"  [X] {relpath}: missing {CONTENT_HASH_KEY}")
            continue

        recomputed = content_hash_sha256(data)

        if stored == recomputed:
            print(f"  [OK] {relpath}: {stored[:16]}...")
        else:
            fail_reasons.append(
                f"{relpath}: {CONTENT_HASH_KEY} mismatch — "
                f"stored={stored[:16]}… recomputed={recomputed[:16]}…"
            )
            print(f"  [X] {relpath}: MISMATCH")
            print(f"       stored:     {stored}")
            print(f"       recomputed: {recomputed}")

    return fail_reasons, warnings


def validate_snapshot_hash(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate data snapshot exists and its hash matches."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 8b: Validating Data Snapshot Hash")
    print("=" * 60)

    snap_file = snapshot_path(str(run_path))
    if not Path(snap_file).exists():
        fail_reasons.append("Missing data snapshot: DataAgent/data_snapshot.parquet")
        print("[X] data_snapshot.parquet not found")
        return fail_reasons, warnings

    try:
        if verify_snapshot_hash(str(run_path)):
            print("[OK] Snapshot hash verified")
        else:
            fail_reasons.append("Data snapshot hash mismatch")
            print("[X] Snapshot hash MISMATCH")
    except FileNotFoundError as e:
        fail_reasons.append(f"Snapshot verification failed: {e}")
        print(f"[X] {e}")
    except Exception as e:
        fail_reasons.append(f"Snapshot verification error: {e}")
        print(f"[X] Error verifying snapshot: {e}")

    return fail_reasons, warnings


def validate_drift_summary(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate DriftAgent/drift_summary.json if present (optional)."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 9: Validating Drift Summary (optional)")
    print("=" * 60)

    drift_dir = run_path / "DriftAgent"
    if not drift_dir.exists():
        print("[--] DriftAgent folder not present (skipped)")
        return fail_reasons, warnings

    summary_path = drift_dir / "drift_summary.json"
    if not summary_path.exists():
        fail_reasons.append("DriftAgent folder exists but drift_summary.json is missing")
        print("[X] drift_summary.json missing")
        return fail_reasons, warnings

    try:
        summary = load_json(summary_path)

        # Required schema fields
        for key in ["schema_version", "drift_status"]:
            if key in summary:
                print(f"  [OK] {key}: {summary[key]}")
            else:
                fail_reasons.append(f"drift_summary.json missing key: {key}")
                print(f"  [X] {key}: MISSING")

        # drift_status must be a known value
        valid_statuses = {"OK", "INSUFFICIENT_HISTORY", "ERROR"}
        ds = summary.get("drift_status")
        if ds and ds not in valid_statuses:
            fail_reasons.append(
                f"drift_summary.json invalid drift_status: {ds}"
            )
            print(f"  [X] drift_status invalid: {ds}")

        # overall_drift_flag must be OK or WARN
        flag = summary.get("overall_drift_flag")
        if flag and flag not in {"OK", "WARN"}:
            fail_reasons.append(
                f"drift_summary.json invalid overall_drift_flag: {flag}"
            )
            print(f"  [X] overall_drift_flag invalid: {flag}")
        elif flag:
            print(f"  [OK] overall_drift_flag: {flag}")

        # Coverage sanity checks (optional — only validated when keys present)
        scanned = summary.get("total_runs_scanned")
        eligible = summary.get("eligible_runs_found")
        used = summary.get("runs_used_in_window")
        if eligible is not None and used is not None:
            print(f"  [OK] coverage present: used={used} eligible={eligible}")
            # Identity: total_runs_scanned >= eligible >= used
            if scanned is not None:
                if scanned < eligible:
                    fail_reasons.append(
                        f"drift_summary.json: total_runs_scanned ({scanned}) "
                        f"< eligible_runs_found ({eligible})"
                    )
                    print(f"  [X] scanned < eligible: {scanned} < {eligible}")
                else:
                    print(f"  [OK] total_runs_scanned={scanned} >= eligible={eligible}")
            if eligible < used:
                fail_reasons.append(
                    f"drift_summary.json: eligible_runs_found ({eligible}) "
                    f"< runs_used_in_window ({used})"
                )
                print(f"  [X] eligible < used: {eligible} < {used}")
            reasons = summary.get("excluded_reasons")
            if reasons is not None:
                expected_keys = {
                    "not_success", "missing_decision",
                    "missing_required_artifacts", "validate_failed", "other",
                }
                missing_keys = expected_keys - set(reasons.keys())
                if missing_keys:
                    warnings.append(
                        f"drift_summary.json excluded_reasons missing keys: "
                        f"{sorted(missing_keys)}"
                    )
                    print(f"  [!] excluded_reasons missing keys: {sorted(missing_keys)}")
                else:
                    print(f"  [OK] excluded_reasons keys complete")
            # Debug sample bounds (optional)
            sample = summary.get("excluded_run_ids_sample")
            if sample is not None:
                if len(sample) > 10:
                    fail_reasons.append(
                        f"drift_summary.json: excluded_run_ids_sample "
                        f"has {len(sample)} entries (max 10)"
                    )
                    print(f"  [X] excluded_run_ids_sample too long: {len(sample)}")
                else:
                    print(f"  [OK] excluded_run_ids_sample: {len(sample)} entries")
            by_reason = summary.get("excluded_run_ids_by_reason_sample")
            if by_reason is not None:
                for reason, ids in by_reason.items():
                    if len(ids) > 5:
                        fail_reasons.append(
                            f"drift_summary.json: excluded_run_ids_by_reason_sample"
                            f"[{reason}] has {len(ids)} entries (max 5)"
                        )
                        print(f"  [X] per-reason sample [{reason}] too long: {len(ids)}")
                if all(len(ids) <= 5 for ids in by_reason.values()):
                    print(f"  [OK] excluded_run_ids_by_reason_sample: all <= 5")
        else:
            print(f"  [--] coverage keys not present (older schema, OK)")

        # drift_reason_summary sanity (optional)
        reason_summary = summary.get("drift_reason_summary")
        if reason_summary is not None:
            if not isinstance(reason_summary, str):
                fail_reasons.append(
                    f"drift_summary.json: drift_reason_summary is not a string"
                )
                print(f"  [X] drift_reason_summary: not a string")
            elif len(reason_summary) > 130:
                fail_reasons.append(
                    f"drift_summary.json: drift_reason_summary too long "
                    f"({len(reason_summary)} > 130)"
                )
                print(f"  [X] drift_reason_summary too long: {len(reason_summary)}")
            else:
                print(f"  [OK] drift_reason_summary: {reason_summary}")

    except Exception as e:
        fail_reasons.append(f"Failed parsing drift_summary.json: {e}")
        print(f"[X] Error parsing drift_summary.json: {e}")

    return fail_reasons, warnings


# ============================================================
# STEP 10: Edge Validation Gates
# ============================================================

def validate_edge_gates(run_path: Path) -> Tuple[List[str], List[str], int]:
    """Validate edge gates using tools/edge_validate.py.

    Checks that the strategy has a statistical edge per EDGE_DEFINITION.md.
    Requires BacktestAgent/trades.parquet and RobustnessAgent artifacts.

    Returns:
        (fail_reasons, warnings, edge_exit_code) — exit code semantics:
        0 = edge PASS, 1 = gates FAIL, 2 = missing/invalid artifacts.
    """
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 10: Edge Validation Gates")
    print("=" * 60)

    # Import edge validator functions
    try:
        from tools.edge_validate import (
            load_edge_config,
            load_artifacts as load_edge_artifacts,
            compute_edge_metrics,
            check_gates,
            check_kill_switch,
        )
    except ImportError as e:
        fail_reasons.append(f"Cannot import edge validator: {e}")
        print(f"  [X] Cannot import tools.edge_validate: {e}")
        return fail_reasons, warnings, 2

    # Load thresholds — intercept sys.exit(2) from missing config
    try:
        thresholds = load_edge_config()
    except SystemExit as exc:
        if exc.code == 2:
            fail_reasons.append(
                "Edge validation: missing or invalid config/edge.yaml (exit code 2)"
            )
            print("  [X] EDGE: MISSING — config/edge.yaml absent or invalid")
            return fail_reasons, warnings, 2
        raise

    # Load artifacts — intercept sys.exit(2) from load_artifacts
    run_dir_str = str(run_path)
    try:
        artifacts = load_edge_artifacts(run_dir_str)
    except SystemExit as exc:
        if exc.code == 2:
            fail_reasons.append(
                "Edge validation: missing or invalid artifacts (exit code 2)"
            )
            print("  [X] EDGE: MISSING — required artifacts absent or invalid")
            return fail_reasons, warnings, 2
        raise

    # Compute metrics
    metrics = compute_edge_metrics(
        trades_df=artifacts["trades"],
        walk_forward=artifacts["walk_forward"],
        monte_carlo=artifacts["monte_carlo"],
        regime_contribution=artifacts["regime_contribution"],
        roll_k=thresholds["roll_k"],
    )

    # Check gates
    gates = check_gates(metrics, thresholds)
    kill_switch = check_kill_switch(metrics, thresholds)

    # Build summary line
    all_pass = all(g["passed"] for g in gates.values())
    ks_triggered = kill_switch["triggered"]

    if all_pass and not ks_triggered:
        status = "PASS"
        edge_exit_code = 0
    else:
        status = "FAIL"
        edge_exit_code = 1

    summary_line = (
        f"EDGE: {status} "
        f"(N={metrics['n']}, E={metrics['e_r']:.4f}, "
        f"PF={metrics['pf']:.4f}, MDD_R={metrics['mdd_r']:.4f})"
    )
    print(f"  [{status}] {summary_line}")

    # Print gate details
    for name, gate in gates.items():
        g_status = "OK" if gate["passed"] else "X "
        print(
            f"    [{g_status}] {name}: "
            f"{gate['value']:.6f} {gate['direction']} {gate['threshold']}"
        )

    if ks_triggered:
        print("    [X ] kill-switch TRIGGERED:")
        for reason in kill_switch["reasons"]:
            print(f"         - {reason}")

    # Regime table
    for row in metrics.get("regime_table", []):
        flag = " [NO-TRADE]" if row["no_trade"] else ""
        print(
            f"    regime={row['regime']:15s} N={row['count']:3d} "
            f"mean_ret={row['mean_return']:+.6f}{flag}"
        )

    # Classify failure for operator diagnostics
    if edge_exit_code == 0:
        edge_class = "NONE"
    elif edge_exit_code == 1:
        edge_class = "EDGE_GATES_FAIL"
    else:
        # exit_code 2: distinguish config vs artifact issues from fail_reasons
        if any("config" in f.lower() for f in fail_reasons):
            edge_class = "MISSING_CONFIG"
        else:
            edge_class = "MISSING_ARTIFACTS"
    print(f"  EDGE_CLASS: {edge_class}")

    if status == "FAIL":
        fail_reasons.append(summary_line)

    return fail_reasons, warnings, edge_exit_code


def print_summary(fail_reasons: List[str], warnings: List[str]):
    """Print final validation summary."""
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    if warnings:
        print("\n[!] WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if fail_reasons:
        print("\n[X] VALIDATION FAILED")
        print("\nFailure reasons:")
        for r in fail_reasons:
            print(f"  - {r}")
        print("\n" + "=" * 60)
        return False

    print("\n[OK] VALIDATION PASSED")
    if not warnings:
        print("All checks passed successfully!")
    else:
        print("All critical checks passed (warnings present).")
    print("=" * 60)
    return True


# ============================================================
# MAIN
# ============================================================

def validate_run(run_path_str: str, *, skip_edge: bool = False) -> int:
    """Run all validations on a run directory.

    Args:
        run_path_str: Path to the run directory.
        skip_edge: If True, skip STEP 10 (edge validation gates).
            Used by determinism CI to isolate reproducibility checks
            from edge/performance gating.

    Returns:
        0 = all passed
        1 = validation failed
    """
    run_path = Path(run_path_str).resolve()

    if not run_path.exists():
        print(f"\n[X] FAIL: Run path does not exist: {run_path}")
        return 1

    all_failures = []
    all_warnings = []

    validators = [
        validate_artifacts,
        validate_sanity_tests,
        validate_metrics,
        validate_abstain_stats,
        validate_oos_samples,
        validate_final_report_schema,
        validate_status_json,
        validate_content_hashes,
        validate_snapshot_hash,
        validate_drift_summary,
    ]

    for validator in validators:
        failures, warnings = validator(run_path)
        all_failures.extend(failures)
        all_warnings.extend(warnings)

    if skip_edge:
        print("\n" + "=" * 60)
        print("STEP 10: Edge Validation Gates")
        print("=" * 60)
        print("  [--] Skipped (--skip-edge)")
    else:
        # Run edge validation separately to capture exit code
        edge_failures, edge_warnings, _edge_exit_code = validate_edge_gates(run_path)
        all_failures.extend(edge_failures)
        all_warnings.extend(edge_warnings)

    passed = print_summary(all_failures, all_warnings)

    return 0 if passed else 1


def main():
    """Main validation function."""
    parser = argparse.ArgumentParser(
        description="Validate stock forecasting system run artifacts"
    )
    parser.add_argument(
        "--run",
        required=True,
        help="Path to run directory (e.g., runs/PLTR/20260214_151806_xaji0y)"
    )
    parser.add_argument(
        "--compare-to",
        default=None,
        help="Compare this run to another run directory for parity check"
    )
    parser.add_argument(
        "--skip-edge",
        action="store_true",
        default=False,
        help="Skip STEP 10 (edge validation gates). "
             "Use for determinism CI where only reproducibility matters."
    )
    args = parser.parse_args()

    print("=" * 60)
    print("RUN VALIDATION")
    print("=" * 60)
    print(f"Run path: {args.run}")
    if args.skip_edge:
        print("Mode: structural only (--skip-edge)")

    exit_code = validate_run(args.run, skip_edge=args.skip_edge)

    # If validation passed and --compare-to is set, run parity check
    if exit_code == 0 and args.compare_to:
        print()
        from tools.compare_runs import compare_runs
        result = compare_runs(args.run, args.compare_to)
        if not result["passed"]:
            print("\n[X] PARITY CHECK FAILED")
            exit_code = 1
        else:
            print("\n[OK] PARITY CHECK PASSED")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
