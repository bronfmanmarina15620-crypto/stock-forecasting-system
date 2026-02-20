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
    "avg_r_multiple",
    "worst_r_multiple",
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


def validate_artifacts(run_path: Path) -> Tuple[List[str], List[str]]:
    """Validate that all required artifacts exist."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 1: Checking Required Artifacts")
    print("=" * 60)

    for folder, files in REQUIRED_ARTIFACTS.items():
        base = run_path if folder == "_ROOT_" else run_path / folder

        if not base.exists():
            fail_reasons.append(f"Missing folder: {base}")
            print(f"[X] Missing folder: {folder}")
            continue

        print(f"\n[OK] Folder exists: {folder}")

        for filename in files:
            filepath = base / filename
            if check_file_exists(filepath, fail_reasons):
                print(f"  [OK] {filename}")
            else:
                print(f"  [X] {filename}")

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
]


def validate_content_hashes(run_path: Path) -> Tuple[List[str], List[str]]:
    """Verify that embedded content_hash_sha256 matches recomputed hash."""
    fail_reasons = []
    warnings = []

    print("\n" + "=" * 60)
    print("STEP 8: Validating content_hash_sha256 Integrity")
    print("=" * 60)

    for relpath in _CONTENT_HASH_TARGETS:
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

def validate_run(run_path_str: str) -> bool:
    """Run all validations on a run directory. Returns True if passed."""
    run_path = Path(run_path_str).resolve()

    if not run_path.exists():
        print(f"\n[X] FAIL: Run path does not exist: {run_path}")
        return False

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
    ]

    for validator in validators:
        failures, warnings = validator(run_path)
        all_failures.extend(failures)
        all_warnings.extend(warnings)

    return print_summary(all_failures, all_warnings)


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
    args = parser.parse_args()

    print("=" * 60)
    print("RUN VALIDATION")
    print("=" * 60)
    print(f"Run path: {args.run}")

    success = validate_run(args.run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
