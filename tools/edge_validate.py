#!/usr/bin/env python
"""
Edge Validator — deterministic edge gate checker for MA150+ATR strategy.

Reads existing run artifacts (no market data fetches) and evaluates
whether the strategy has a statistical edge per EDGE_DEFINITION.md.

Exit codes:
    0  All gates pass
    1  One or more gates fail
    2  Missing or invalid artifacts

Usage:
    python tools/edge_validate.py --run runs/PLTR/<RUN_ID>
    python tools/edge_validate.py --run runs/PLTR/<RUN_ID> --config config/edge.yaml
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PF_CAP = 999.0  # cap profit factor when no losing trades

_REQUIRED_ARTIFACTS = {
    "trades": os.path.join("BacktestAgent", "trades.parquet"),
    "walk_forward": os.path.join("RobustnessAgent", "walk_forward.json"),
    "monte_carlo": os.path.join("RobustnessAgent", "monte_carlo.json"),
    "regime_contribution": os.path.join(
        "RobustnessAgent", "regime_contribution.json"
    ),
}

# Last-resort defaults — ONLY used when tests explicitly request them via
# _default_thresholds() helper.  Runtime CLI always loads config/edge.yaml.
_DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "n_min": 30,
    "e_min": 0.0,
    "pf_min": 1.0,
    "mdd_max": 5.0,
    "roll_k": 20,
    "pos_roll_ratio_min": 0.5,
    "wf_e_min": 0.0,
    "wf_pos_folds_min": 0.5,
    "roll_fail_streak": 5,
    "dd_shock": 10.0,
    "reset_streak": 3,
}


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_edge_config(
    config_path: Optional[str] = None,
    *,
    _allow_defaults: bool = False,
) -> Dict[str, Any]:
    """Load edge thresholds from config/edge.yaml.

    Runtime behaviour (default):
        - If *config_path* is None, resolves to ``<project_root>/config/edge.yaml``.
        - If the file does not exist, prints an error and calls ``sys.exit(2)``
          (missing config is a hard fail — same semantics as a missing artifact).

    Test/internal callers may pass ``_allow_defaults=True`` to fall back to
    ``_DEFAULT_THRESHOLDS`` when the file is absent.  This is *not* used by
    the CLI entry-point.
    """
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
            "edge.yaml",
        )

    if not os.path.exists(config_path):
        if _allow_defaults:
            return dict(_DEFAULT_THRESHOLDS)
        print(
            f"MISSING CONFIG: {config_path} — edge thresholds cannot be loaded. "
            "Run tools/edge_calibrate.py to generate it, or pass --config.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        import yaml

        with open(config_path, "r") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as exc:
        if _allow_defaults:
            return dict(_DEFAULT_THRESHOLDS)
        print(
            f"INVALID CONFIG: {config_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    gates = raw.get("edge_gates", {})
    result = dict(_DEFAULT_THRESHOLDS)
    for key in _DEFAULT_THRESHOLDS:
        if key in gates:
            result[key] = gates[key]
    return result


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------

def load_artifacts(run_dir: str) -> Dict[str, Any]:
    """Load all required artifacts from a run directory.

    Returns dict with keys: trades, walk_forward, monte_carlo, regime_contribution.
    Prints error and calls sys.exit(2) on missing/invalid artifact.
    """
    artifacts: Dict[str, Any] = {}

    for name, rel_path in _REQUIRED_ARTIFACTS.items():
        full_path = os.path.join(run_dir, rel_path)
        if not os.path.exists(full_path):
            print(f"MISSING ARTIFACT: {rel_path}", file=sys.stderr)
            sys.exit(2)

    # Load trades
    trades_path = os.path.join(run_dir, _REQUIRED_ARTIFACTS["trades"])
    try:
        trades_df = pd.read_parquet(trades_path)
    except Exception as exc:
        print(f"INVALID ARTIFACT: {_REQUIRED_ARTIFACTS['trades']}: {exc}",
              file=sys.stderr)
        sys.exit(2)

    if "r_multiple" not in trades_df.columns:
        print(
            "INVALID ARTIFACT: trades.parquet missing 'r_multiple' column",
            file=sys.stderr,
        )
        sys.exit(2)

    artifacts["trades"] = trades_df

    # Load JSON artifacts
    for name in ("walk_forward", "monte_carlo", "regime_contribution"):
        json_path = os.path.join(run_dir, _REQUIRED_ARTIFACTS[name])
        try:
            with open(json_path, "r") as f:
                artifacts[name] = json.load(f)
        except Exception as exc:
            print(
                f"INVALID ARTIFACT: {_REQUIRED_ARTIFACTS[name]}: {exc}",
                file=sys.stderr,
            )
            sys.exit(2)

    return artifacts


# ---------------------------------------------------------------------------
# Edge metrics computation (pure, deterministic)
# ---------------------------------------------------------------------------

def compute_edge_metrics(
    trades_df: pd.DataFrame,
    walk_forward: Dict[str, Any],
    monte_carlo: Dict[str, Any],
    regime_contribution: Dict[str, Any],
    roll_k: int = 20,
) -> Dict[str, Any]:
    """Compute all edge metrics from artifacts.

    All computations are deterministic — no randomness, no side effects.
    """
    r_vals = trades_df["r_multiple"].values.astype(float)
    n = len(r_vals)

    # ---- Core metrics ----
    if n == 0:
        e_r = 0.0
        pf = 0.0
        mdd_r = 0.0
        win_rate = 0.0
        avg_win = 0.0
        avg_loss = 0.0
    else:
        e_r = float(np.mean(r_vals))

        pos_sum = float(np.sum(r_vals[r_vals > 0]))
        neg_sum = float(np.abs(np.sum(r_vals[r_vals < 0])))
        if neg_sum > 0:
            pf = pos_sum / neg_sum
        elif pos_sum > 0:
            pf = _PF_CAP
        else:
            pf = 0.0

        # MDD_R: max peak-to-trough on cumulative R curve
        cum_r = np.cumsum(r_vals)
        running_max = np.maximum.accumulate(cum_r)
        drawdowns = running_max - cum_r
        mdd_r = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        wins = r_vals[r_vals > 0]
        losses = r_vals[r_vals < 0]
        win_rate = float(len(wins) / n)
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(np.mean(losses))) if len(losses) > 0 else 0.0

    # ---- Rolling expectancy ----
    if n >= roll_k:
        n_windows = n - roll_k + 1
        rolling_means = np.array([
            np.mean(r_vals[i : i + roll_k]) for i in range(n_windows)
        ])
        pos_roll_ratio = float(np.mean(rolling_means > 0))
        # Kill-switch: trailing streak of negative windows
        trailing_negative = 0
        for val in reversed(rolling_means):
            if val <= 0:
                trailing_negative += 1
            else:
                break
    else:
        pos_roll_ratio = 0.0 if n > 0 else 0.0
        trailing_negative = 0

    # ---- Walk-forward ----
    wf_windows = walk_forward.get("windows", [])
    if wf_windows:
        wf_expectancies = [w.get("expectancy", 0.0) for w in wf_windows]
        wf_median_e = float(np.median(wf_expectancies))
        wf_pos_folds = float(np.mean(np.array(wf_expectancies) > 0))
    else:
        wf_median_e = 0.0
        wf_pos_folds = 0.0

    # ---- Monte Carlo DD reference ----
    mc_dd = monte_carlo.get("max_drawdown", {})
    mc_dd_p95 = mc_dd.get("p95", None)

    # ---- Regime contribution ----
    buckets = regime_contribution.get("buckets", [])
    regime_table: List[Dict[str, Any]] = []
    for bucket in buckets:
        regime_table.append({
            "regime": bucket.get("regime", "UNKNOWN"),
            "count": bucket.get("count", 0),
            "mean_return": bucket.get("mean_return", 0.0),
            "no_trade": bucket.get("mean_return", 0.0) < 0,
        })

    return {
        "n": n,
        "e_r": round(e_r, 6),
        "pf": round(pf, 6),
        "mdd_r": round(mdd_r, 6),
        "win_rate": round(win_rate, 6),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "pos_roll_ratio": round(pos_roll_ratio, 6),
        "trailing_negative_windows": trailing_negative,
        "wf_median_e": round(wf_median_e, 6),
        "wf_pos_folds": round(wf_pos_folds, 6),
        "mc_dd_p95": mc_dd_p95,
        "regime_table": regime_table,
    }


# ---------------------------------------------------------------------------
# Gate checking
# ---------------------------------------------------------------------------

def check_gates(
    metrics: Dict[str, Any],
    thresholds: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Evaluate each edge gate.

    Returns dict of {gate_name: {passed, value, threshold, direction}}.
    A gate passes when the value meets or exceeds (or is at/below for max) the threshold.
    """
    gates: Dict[str, Dict[str, Any]] = {}

    # 3.1 Minimum sample size
    gates["n_min"] = {
        "passed": metrics["n"] >= thresholds["n_min"],
        "value": metrics["n"],
        "threshold": thresholds["n_min"],
        "direction": ">=",
    }

    # 3.2 Core profitability
    gates["e_min"] = {
        "passed": metrics["e_r"] >= thresholds["e_min"],
        "value": metrics["e_r"],
        "threshold": thresholds["e_min"],
        "direction": ">=",
    }
    gates["pf_min"] = {
        "passed": metrics["pf"] >= thresholds["pf_min"],
        "value": metrics["pf"],
        "threshold": thresholds["pf_min"],
        "direction": ">=",
    }

    # 3.3 Drawdown
    gates["mdd_max"] = {
        "passed": metrics["mdd_r"] <= thresholds["mdd_max"],
        "value": metrics["mdd_r"],
        "threshold": thresholds["mdd_max"],
        "direction": "<=",
    }

    # 3.4 Stability — rolling
    gates["pos_roll_ratio_min"] = {
        "passed": metrics["pos_roll_ratio"] >= thresholds["pos_roll_ratio_min"],
        "value": metrics["pos_roll_ratio"],
        "threshold": thresholds["pos_roll_ratio_min"],
        "direction": ">=",
    }

    # 3.4 Stability — walk-forward
    gates["wf_e_min"] = {
        "passed": metrics["wf_median_e"] >= thresholds["wf_e_min"],
        "value": metrics["wf_median_e"],
        "threshold": thresholds["wf_e_min"],
        "direction": ">=",
    }
    gates["wf_pos_folds_min"] = {
        "passed": metrics["wf_pos_folds"] >= thresholds["wf_pos_folds_min"],
        "value": metrics["wf_pos_folds"],
        "threshold": thresholds["wf_pos_folds_min"],
        "direction": ">=",
    }

    return gates


def check_kill_switch(
    metrics: Dict[str, Any],
    thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate kill-switch conditions.

    Returns {triggered: bool, reasons: list[str]}.
    """
    reasons: List[str] = []

    # 5.1 Rolling edge breakdown
    streak = metrics.get("trailing_negative_windows", 0)
    if streak >= thresholds["roll_fail_streak"]:
        reasons.append(
            f"rolling_fail_streak: {streak} >= {thresholds['roll_fail_streak']}"
        )

    # 5.2 Drawdown shock
    if metrics["mdd_r"] >= thresholds["dd_shock"]:
        reasons.append(
            f"dd_shock: MDD_R {metrics['mdd_r']:.4f} >= {thresholds['dd_shock']}"
        )

    return {
        "triggered": len(reasons) > 0,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(
    metrics: Dict[str, Any],
    gates: Dict[str, Dict[str, Any]],
    kill_switch: Dict[str, Any],
) -> None:
    """Print a concise human-readable edge validation report."""
    print("=" * 60)
    print("EDGE VALIDATION REPORT")
    print("=" * 60)

    # Core metrics
    print(f"\n--- Core Metrics ---")
    print(f"  Trade count (N):    {metrics['n']}")
    print(f"  Expectancy E[R]:    {metrics['e_r']:.6f}")
    print(f"  Win rate:           {metrics['win_rate']:.4f}")
    print(f"  Avg win (R):        {metrics['avg_win']:.4f}")
    print(f"  Avg loss (R):       {metrics['avg_loss']:.4f}")
    print(f"  Profit factor:      {metrics['pf']:.4f}")
    print(f"  Max DD in R:        {metrics['mdd_r']:.4f}")

    # Rolling
    print(f"\n--- Rolling Expectancy ---")
    print(f"  Pos-roll ratio:     {metrics['pos_roll_ratio']:.4f}")
    print(f"  Trailing neg wins:  {metrics['trailing_negative_windows']}")

    # Walk-forward
    print(f"\n--- Walk-Forward ---")
    print(f"  Median E_test:      {metrics['wf_median_e']:.6f}")
    print(f"  Pos folds ratio:    {metrics['wf_pos_folds']:.4f}")

    # Monte Carlo
    if metrics.get("mc_dd_p95") is not None:
        print(f"\n--- Monte Carlo ---")
        print(f"  DD p95:             {metrics['mc_dd_p95']:.4f}")

    # Regime table
    regime_table = metrics.get("regime_table", [])
    if regime_table:
        print(f"\n--- Regime Contribution ---")
        for row in regime_table:
            flag = " [NO-TRADE]" if row["no_trade"] else ""
            print(
                f"  {row['regime']:20s}  N={row['count']:3d}  "
                f"mean_ret={row['mean_return']:+.6f}{flag}"
            )

    # Gate results
    print(f"\n--- Gate Results ---")
    all_pass = True
    for name, gate in gates.items():
        status = "PASS" if gate["passed"] else "FAIL"
        if not gate["passed"]:
            all_pass = False
        print(
            f"  {name:25s}  {status}  "
            f"(value={gate['value']:.6f} {gate['direction']} {gate['threshold']})"
        )

    # Kill-switch
    print(f"\n--- Kill-Switch ---")
    if kill_switch["triggered"]:
        print(f"  TRIGGERED")
        for reason in kill_switch["reasons"]:
            print(f"    - {reason}")
    else:
        print(f"  Not triggered")

    # Verdict
    print(f"\n{'=' * 60}")
    if kill_switch["triggered"]:
        print("VERDICT: FAIL (kill-switch triggered)")
    elif not all_pass:
        print("VERDICT: FAIL (one or more gates failed)")
    else:
        print("VERDICT: PASS (all gates passed)")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns exit code 0/1/2."""
    parser = argparse.ArgumentParser(
        description="Edge validation for MA150+ATR strategy runs."
    )
    parser.add_argument(
        "--run",
        required=True,
        help="Path to run directory (e.g. runs/PLTR/20260222_120000_abc123)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to edge config YAML (default: config/edge.yaml)",
    )
    parser.add_argument(
        "--thresholds-override",
        default=None,
        help="Explicit path to override YAML. Suppresses missing-config error.",
    )
    args = parser.parse_args(argv)

    # Load config — --thresholds-override takes precedence
    config_path = args.thresholds_override or args.config
    thresholds = load_edge_config(config_path)

    # Load artifacts (exits 2 on missing)
    artifacts = load_artifacts(args.run)

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

    # Check kill-switch
    kill_switch = check_kill_switch(metrics, thresholds)

    # Report
    print_report(metrics, gates, kill_switch)

    # Exit code
    all_pass = all(g["passed"] for g in gates.values())
    if kill_switch["triggered"] or not all_pass:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
