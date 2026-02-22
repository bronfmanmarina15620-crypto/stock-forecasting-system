#!/usr/bin/env python
"""
Edge Threshold Calibrator — deterministic, rule-based threshold calibration
from historical run artifacts.

Scans past runs, computes edge metrics per run, and proposes thresholds
using explicit statistical rules (percentile + floor/ceiling).

Deterministic: stable sort, stable rounding, no use of current time.

Exit codes:
    0  Calibration succeeded
    2  No eligible runs found

Usage:
    python tools/edge_calibrate.py --ticker PLTR --runs-root runs/PLTR \
        --out config/edge.yaml \
        --report runs/PLTR/edge_calibration_report.json
"""

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tools.edge_validate import (
    _DEFAULT_THRESHOLDS,
    compute_edge_metrics,
    load_artifacts,
    load_edge_config,
)

# ---------------------------------------------------------------------------
# Constants: calibration rules
# ---------------------------------------------------------------------------

# Minimum number of unique metric values to trust percentile-based calibration.
# Below this, the floor/ceiling dominates.
_MIN_DIVERSITY = 3

# ---------------------------------------------------------------------------
# MINIMUM MEANINGFUL FLOORS — calibration can NEVER go below these.
# Rationale: the previous "0.0" floors for robustness gates and "2" for n_min
# created degenerate "always-pass" thresholds.  These floors guarantee that
# passing edge validation requires genuine statistical evidence.
# ---------------------------------------------------------------------------
MINIMUM_MEANINGFUL_FLOORS: Dict[str, float] = {
    "n_min": 30,              # need >= 30 trades for any statistical claim
    "e_min": 0.0,             # expectancy >= 0 is economically meaningful
    "pf_min": 1.0,            # profit factor >= 1 = breakeven
    "pos_roll_ratio_min": 0.5,  # majority of rolling windows must be positive
    "wf_pos_folds_min": 0.5,   # majority of WF folds must be positive
}

# Theoretical floors for "minimum" gates (economic meaning).
# These are now derived from MINIMUM_MEANINGFUL_FLOORS.
_FLOORS: Dict[str, float] = {
    "n_min": MINIMUM_MEANINGFUL_FLOORS["n_min"],
    "e_min": MINIMUM_MEANINGFUL_FLOORS["e_min"],
    "pf_min": MINIMUM_MEANINGFUL_FLOORS["pf_min"],
    "pos_roll_ratio_min": MINIMUM_MEANINGFUL_FLOORS["pos_roll_ratio_min"],
    "wf_e_min": 0.0,
    "wf_pos_folds_min": MINIMUM_MEANINGFUL_FLOORS["wf_pos_folds_min"],
}

# ---------------------------------------------------------------------------
# ELIGIBILITY SUFFICIENCY GATE — minimum runs to produce trustworthy
# calibration.  If not met, calibrate exits 2 and does NOT overwrite
# config/edge.yaml (report is still written for diagnostics).
# ---------------------------------------------------------------------------
MIN_ELIGIBLE_RUNS = 10     # need at least 10 eligible runs
MIN_PASS_LIKE_RUNS = 3     # need at least 3 PASS-like runs (N>=2, E>0)

# Ceiling for "maximum" gates.
_CEILINGS: Dict[str, float] = {
    "mdd_max": 15.0,
}

# Structural parameters: kept at defaults, not calibrated from data.
_STRUCTURAL_KEYS = {"roll_k", "roll_fail_streak", "dd_shock", "reset_streak"}

# Percentile used for "minimum" gates (lower quantile = conservative).
_MIN_GATE_PERCENTILE = 20

# Percentile used for n_min (p25 = 75% of runs pass).
_N_MIN_PERCENTILE = 25

# Percentile used for "maximum" gates (upper quantile = conservative).
_MAX_GATE_PERCENTILE = 90

# Headroom multiplier for mdd_max.
_MDD_HEADROOM = 2.0

# Floor for mdd_max (don't go below this even if observed MDD is tiny).
_MDD_FLOOR = 5.0

# YAML key order (stable output).
_YAML_KEY_ORDER = [
    "n_min",
    "e_min",
    "pf_min",
    "mdd_max",
    "roll_k",
    "pos_roll_ratio_min",
    "wf_e_min",
    "wf_pos_folds_min",
    "roll_fail_streak",
    "dd_shock",
    "reset_streak",
]


# ---------------------------------------------------------------------------
# Scanning and metric collection
# ---------------------------------------------------------------------------


def scan_eligible_runs(runs_root: str) -> List[str]:
    """Return sorted list of run directory paths that have all required artifacts.

    Only includes directories (not files) directly under runs_root.
    Skips entries starting with '_'.
    """
    if not os.path.isdir(runs_root):
        return []

    eligible = []
    for entry in sorted(os.listdir(runs_root)):
        if entry.startswith("_"):
            continue
        run_dir = os.path.join(runs_root, entry)
        if not os.path.isdir(run_dir):
            continue
        # Check all required artifacts
        required = [
            os.path.join("BacktestAgent", "trades.parquet"),
            os.path.join("RobustnessAgent", "walk_forward.json"),
            os.path.join("RobustnessAgent", "monte_carlo.json"),
            os.path.join("RobustnessAgent", "regime_contribution.json"),
        ]
        if all(os.path.exists(os.path.join(run_dir, p)) for p in required):
            eligible.append(run_dir)

    return eligible


def collect_metrics(
    run_dirs: List[str], roll_k: int = 20
) -> List[Dict[str, Any]]:
    """Compute edge metrics for each run directory.

    Skips runs where load_artifacts raises SystemExit (missing/invalid).
    Returns list of metric dicts, one per successful run.
    """
    results = []
    for run_dir in run_dirs:
        try:
            artifacts = load_artifacts(run_dir)
        except SystemExit:
            continue

        metrics = compute_edge_metrics(
            trades_df=artifacts["trades"],
            walk_forward=artifacts["walk_forward"],
            monte_carlo=artifacts["monte_carlo"],
            regime_contribution=artifacts["regime_contribution"],
            roll_k=roll_k,
        )
        metrics["_run_dir"] = run_dir
        results.append(metrics)

    return results


# ---------------------------------------------------------------------------
# Calibration logic
# ---------------------------------------------------------------------------


def _unique_count(values: np.ndarray) -> int:
    """Count unique values in array."""
    return len(np.unique(values))


def _calibrate_min_gate(
    values: np.ndarray,
    percentile: int,
    floor: float,
    decimals: int = 4,
) -> Dict[str, Any]:
    """Calibrate a minimum-type gate threshold.

    If diversity (unique values) < _MIN_DIVERSITY, uses floor.
    Otherwise uses p{percentile}, then max(floor, proposed).
    """
    n_unique = _unique_count(values)
    use_floor = n_unique < _MIN_DIVERSITY

    if use_floor:
        proposed = floor
        rule = f"floor (diversity={n_unique} < {_MIN_DIVERSITY})"
    else:
        proposed = float(np.percentile(values, percentile))
        rule = f"p{percentile}"

    calibrated = round(max(floor, proposed), decimals)

    return {
        "value": calibrated,
        "rule": rule,
        "floor": floor,
        "proposed_raw": round(float(proposed), decimals + 2),
        "n_unique": n_unique,
        "distribution": {
            "min": round(float(np.min(values)), decimals + 2),
            "p10": round(float(np.percentile(values, 10)), decimals + 2),
            "p20": round(float(np.percentile(values, 20)), decimals + 2),
            "p25": round(float(np.percentile(values, 25)), decimals + 2),
            "median": round(float(np.median(values)), decimals + 2),
            "p75": round(float(np.percentile(values, 75)), decimals + 2),
            "p80": round(float(np.percentile(values, 80)), decimals + 2),
            "p90": round(float(np.percentile(values, 90)), decimals + 2),
            "max": round(float(np.max(values)), decimals + 2),
            "std": round(float(np.std(values)), decimals + 2),
            "count": len(values),
        },
    }


def _calibrate_max_gate(
    values: np.ndarray,
    percentile: int,
    ceiling: float,
    headroom: float,
    floor: float,
    decimals: int = 1,
) -> Dict[str, Any]:
    """Calibrate a maximum-type gate threshold.

    proposed = max(p{percentile} * headroom, floor)
    calibrated = min(ceiling, proposed)
    """
    n_unique = _unique_count(values)

    raw_percentile = float(np.percentile(values, percentile))
    proposed = max(raw_percentile * headroom, floor)
    calibrated = round(min(ceiling, proposed), decimals)

    return {
        "value": calibrated,
        "rule": f"min(ceil={ceiling}, max(p{percentile}*{headroom}, floor={floor}))",
        "ceiling": ceiling,
        "headroom": headroom,
        "proposed_raw": round(float(proposed), decimals + 2),
        "n_unique": n_unique,
        "distribution": {
            "min": round(float(np.min(values)), decimals + 2),
            "p10": round(float(np.percentile(values, 10)), decimals + 2),
            "p20": round(float(np.percentile(values, 20)), decimals + 2),
            "median": round(float(np.median(values)), decimals + 2),
            "p80": round(float(np.percentile(values, 80)), decimals + 2),
            "p90": round(float(np.percentile(values, 90)), decimals + 2),
            "max": round(float(np.max(values)), decimals + 2),
            "std": round(float(np.std(values)), decimals + 2),
            "count": len(values),
        },
    }


def calibrate_thresholds(
    all_metrics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Propose calibrated thresholds from collected metrics.

    Returns dict with:
        "thresholds": {key: value} — the calibrated values
        "details": {key: calibration_detail} — per-key stats and rules
        "eligible_runs": int
        "pass_like_runs": int
        "insufficient_data": list[str] — metrics where floor was forced due to
            degenerate data (N < roll_k for most runs, no WF folds, etc.)
    """
    # All eligible metrics arrays
    all_n = np.array([m["n"] for m in all_metrics], dtype=float)
    all_e_r = np.array([m["e_r"] for m in all_metrics], dtype=float)

    # "PASS-like" filter: N >= 2 and e_r > 0
    pass_like = [m for m in all_metrics if m["n"] >= 2 and m["e_r"] > 0]

    insufficient_data: List[str] = []
    details = {}
    thresholds = {}

    # ---- n_min: from ALL eligible (always use percentile, no diversity guard) ----
    n_min_proposed = max(
        _FLOORS["n_min"],
        int(math.floor(float(np.percentile(all_n, _N_MIN_PERCENTILE)))),
    )
    details["n_min"] = {
        "value": n_min_proposed,
        "rule": f"max(floor={int(_FLOORS['n_min'])}, floor(p{_N_MIN_PERCENTILE}))",
        "floor": _FLOORS["n_min"],
        "proposed_raw": float(np.percentile(all_n, _N_MIN_PERCENTILE)),
        "n_unique": _unique_count(all_n),
        "distribution": {
            "min": float(np.min(all_n)),
            "p25": float(np.percentile(all_n, 25)),
            "median": float(np.median(all_n)),
            "p75": float(np.percentile(all_n, 75)),
            "max": float(np.max(all_n)),
            "count": len(all_n),
        },
    }
    thresholds["n_min"] = n_min_proposed

    # ---- Profitability and stability: from PASS-like ----
    if pass_like:
        pl_e_r = np.array([m["e_r"] for m in pass_like], dtype=float)
        pl_pf = np.array([m["pf"] for m in pass_like], dtype=float)
        pl_mdd_r = np.array([m["mdd_r"] for m in pass_like], dtype=float)
        pl_pos_roll = np.array(
            [m["pos_roll_ratio"] for m in pass_like], dtype=float
        )
        pl_wf_e = np.array(
            [m["wf_median_e"] for m in pass_like], dtype=float
        )
        pl_wf_folds = np.array(
            [m["wf_pos_folds"] for m in pass_like], dtype=float
        )
    else:
        # No PASS-like runs: all values are empty → use floors
        pl_e_r = all_e_r
        pl_pf = np.array([m["pf"] for m in all_metrics], dtype=float)
        pl_mdd_r = np.array([m["mdd_r"] for m in all_metrics], dtype=float)
        pl_pos_roll = np.array(
            [m["pos_roll_ratio"] for m in all_metrics], dtype=float
        )
        pl_wf_e = np.array(
            [m["wf_median_e"] for m in all_metrics], dtype=float
        )
        pl_wf_folds = np.array(
            [m["wf_pos_folds"] for m in all_metrics], dtype=float
        )

    details["e_min"] = _calibrate_min_gate(
        pl_e_r, _MIN_GATE_PERCENTILE, _FLOORS["e_min"],
    )
    thresholds["e_min"] = details["e_min"]["value"]

    details["pf_min"] = _calibrate_min_gate(
        pl_pf, _MIN_GATE_PERCENTILE, _FLOORS["pf_min"],
    )
    thresholds["pf_min"] = details["pf_min"]["value"]

    details["mdd_max"] = _calibrate_max_gate(
        pl_mdd_r, _MAX_GATE_PERCENTILE, _CEILINGS["mdd_max"],
        _MDD_HEADROOM, _MDD_FLOOR,
    )
    thresholds["mdd_max"] = details["mdd_max"]["value"]

    details["pos_roll_ratio_min"] = _calibrate_min_gate(
        pl_pos_roll, _MIN_GATE_PERCENTILE, _FLOORS["pos_roll_ratio_min"],
        decimals=2,
    )
    thresholds["pos_roll_ratio_min"] = details["pos_roll_ratio_min"]["value"]

    details["wf_e_min"] = _calibrate_min_gate(
        pl_wf_e, _MIN_GATE_PERCENTILE, _FLOORS["wf_e_min"],
    )
    thresholds["wf_e_min"] = details["wf_e_min"]["value"]

    details["wf_pos_folds_min"] = _calibrate_min_gate(
        pl_wf_folds, _MIN_GATE_PERCENTILE, _FLOORS["wf_pos_folds_min"],
        decimals=2,
    )
    thresholds["wf_pos_folds_min"] = details["wf_pos_folds_min"]["value"]

    # ---- Mark INSUFFICIENT_DATA when distribution is degenerate ----
    # pos_roll_ratio: if most runs have N < roll_k, the metric is 0.0 for
    # all of them — the percentile is meaningless, floor dominates.
    if _unique_count(pl_pos_roll) < _MIN_DIVERSITY:
        insufficient_data.append("pos_roll_ratio_min")
        details["pos_roll_ratio_min"]["insufficient_data"] = True

    if _unique_count(pl_wf_folds) < _MIN_DIVERSITY:
        insufficient_data.append("wf_pos_folds_min")
        details["wf_pos_folds_min"]["insufficient_data"] = True

    # ---- Structural: keep defaults ----
    for key in _STRUCTURAL_KEYS:
        thresholds[key] = _DEFAULT_THRESHOLDS[key]
        details[key] = {
            "value": _DEFAULT_THRESHOLDS[key],
            "rule": "structural_default",
        }

    return {
        "thresholds": thresholds,
        "details": details,
        "eligible_runs": len(all_metrics),
        "pass_like_runs": len(pass_like),
        "insufficient_data": insufficient_data,
    }


# ---------------------------------------------------------------------------
# YAML output (stable, deterministic)
# ---------------------------------------------------------------------------

# Comments per key for human-readable YAML.
_YAML_COMMENTS: Dict[str, str] = {
    "n_min": "minimum trade count",
    "e_min": "minimum expectancy E[R] (mean R-multiple)",
    "pf_min": "minimum profit factor (sum wins / abs sum losses)",
    "mdd_max": "max drawdown in R (cumulative R units)",
    "roll_k": "rolling window size (trades)",
    "pos_roll_ratio_min": "fraction of rolling windows with E_roll > 0",
    "wf_e_min": "median walk-forward expectancy (%-return based)",
    "wf_pos_folds_min": "fraction of folds with positive expectancy",
    "roll_fail_streak": "consecutive negative rolling windows -> kill",
    "dd_shock": "drawdown in R exceeding this -> kill",
    "reset_streak": "consecutive positive windows to reset kill-switch",
}

# Section labels for YAML comments.
_YAML_SECTIONS: Dict[str, str] = {
    "n_min": "Section 3.1: Minimum sample size",
    "e_min": "Section 3.2: Core profitability",
    "mdd_max": "Section 3.3: Drawdown",
    "roll_k": "Section 3.4: Stability -- rolling expectancy",
    "wf_e_min": "Section 3.4: Stability -- walk-forward",
    "roll_fail_streak": "Section 5: Kill-switch",
}


def _format_value(value: Any) -> str:
    """Format a threshold value for YAML output."""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Remove trailing zeros but keep at least one decimal
        if value == int(value):
            return f"{value:.1f}"
        return f"{value:g}"
    return str(value)


def write_edge_yaml(thresholds: Dict[str, Any], out_path: str) -> None:
    """Write config/edge.yaml with stable formatting and comments."""
    lines = [
        "# Edge validation thresholds -- EDGE_DEFINITION.md Section 6",
        "# Calibrated by tools/edge_calibrate.py (rule-based, deterministic).",
        "# Do not change without updating EDGE_DEFINITION.md and tests.",
        "",
        "edge_gates:",
    ]

    for key in _YAML_KEY_ORDER:
        value = thresholds[key]
        formatted = _format_value(value)

        # Section comment
        if key in _YAML_SECTIONS:
            lines.append(f"  # {_YAML_SECTIONS[key]}")

        # Key: value  # comment
        comment = _YAML_COMMENTS.get(key, "")
        # Align comments at column 35 from start of value line
        kv = f"  {key}: {formatted}"
        pad = max(1, 35 - len(kv))
        lines.append(f"{kv}{' ' * pad}# {comment}")

    lines.append("")  # trailing newline

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


def write_report(
    calibration: Dict[str, Any],
    run_dirs: List[str],
    out_path: str,
    *,
    rejection_reason: Optional[str] = None,
) -> None:
    """Write calibration report as JSON."""
    report = {
        "eligible_runs": calibration["eligible_runs"],
        "pass_like_runs": calibration["pass_like_runs"],
        "run_dirs": [os.path.basename(d) for d in run_dirs],
        "thresholds": calibration["thresholds"],
        "calibration_details": calibration["details"],
        "insufficient_data": calibration.get("insufficient_data", []),
    }
    if rejection_reason:
        report["rejected"] = True
        report["rejection_reason"] = rejection_reason

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Calibrate edge validation thresholds from historical runs."
    )
    parser.add_argument(
        "--ticker", default="PLTR", help="Ticker symbol (default: PLTR)"
    )
    parser.add_argument(
        "--runs-root",
        default=None,
        help="Root directory for runs (default: runs/<TICKER>)",
    )
    parser.add_argument(
        "--out",
        default="config/edge.yaml",
        help="Output path for calibrated edge.yaml (default: config/edge.yaml)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Output path for calibration report JSON (optional)",
    )
    args = parser.parse_args(argv)

    runs_root = args.runs_root or os.path.join("runs", args.ticker)

    print(f"Scanning runs under: {runs_root}")
    eligible_dirs = scan_eligible_runs(runs_root)
    print(f"Eligible runs: {len(eligible_dirs)}")

    if not eligible_dirs:
        print("ERROR: No eligible runs found. Cannot calibrate.", file=sys.stderr)
        return 2

    # Use current roll_k from config for metric computation.
    # Use _allow_defaults=True since config/edge.yaml may not exist yet
    # (this is the tool that *creates* it).
    current_config = load_edge_config(_allow_defaults=True)
    roll_k = current_config.get("roll_k", 20)

    print(f"Computing metrics (roll_k={roll_k})...")
    all_metrics = collect_metrics(eligible_dirs, roll_k=roll_k)

    if not all_metrics:
        print(
            "ERROR: No runs produced valid metrics. Cannot calibrate.",
            file=sys.stderr,
        )
        return 2

    print(f"Runs with valid metrics: {len(all_metrics)}")

    # Calibrate
    calibration = calibrate_thresholds(all_metrics)
    thresholds = calibration["thresholds"]

    print(f"\nCalibrated thresholds:")
    for key in _YAML_KEY_ORDER:
        detail = calibration["details"][key]
        rule = detail["rule"]
        print(f"  {key:25s} = {_format_value(thresholds[key]):>8s}  ({rule})")

    print(f"\nPass-like runs: {calibration['pass_like_runs']}/{calibration['eligible_runs']}")

    if calibration.get("insufficient_data"):
        print(f"INSUFFICIENT_DATA metrics: {calibration['insufficient_data']}")

    # ---- Eligibility sufficiency gate ----
    # Require enough runs for trustworthy calibration.  If not met, exit 2
    # and do NOT overwrite config/edge.yaml (report is still written).
    rejection_reason = None
    if calibration["eligible_runs"] < MIN_ELIGIBLE_RUNS:
        rejection_reason = (
            f"eligible_runs={calibration['eligible_runs']} < "
            f"MIN_ELIGIBLE_RUNS={MIN_ELIGIBLE_RUNS}"
        )
    elif calibration["pass_like_runs"] < MIN_PASS_LIKE_RUNS:
        rejection_reason = (
            f"pass_like_runs={calibration['pass_like_runs']} < "
            f"MIN_PASS_LIKE_RUNS={MIN_PASS_LIKE_RUNS}"
        )

    if rejection_reason:
        print(
            f"\nREJECTED: {rejection_reason}. "
            f"config/edge.yaml NOT overwritten.",
            file=sys.stderr,
        )
        # Still write report for diagnostics
        if args.report:
            write_report(
                calibration, eligible_dirs, args.report,
                rejection_reason=rejection_reason,
            )
            print(f"Wrote diagnostic report: {args.report}")
        return 2

    # Write YAML
    write_edge_yaml(thresholds, args.out)
    print(f"\nWrote: {args.out}")

    # Write report
    if args.report:
        write_report(calibration, eligible_dirs, args.report)
        print(f"Wrote: {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
