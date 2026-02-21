"""
Pure, deterministic drift-metric functions for Shadow History analysis.

All functions are stateless and operate on plain dicts / pandas objects.
No filesystem I/O — callers (DriftAgent) handle loading and saving.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ── History loading helpers ──────────────────────────────────────────


_MAX_EXCLUDED_IDS_SAMPLE = 10
_MAX_PER_REASON_SAMPLE = 5


def _empty_coverage() -> Dict[str, Any]:
    """Return a zeroed-out coverage dict."""
    return {
        "total_scanned": 0,
        "eligible_runs_found": 0,
        "runs_excluded": 0,
        "excluded_reasons": {
            "not_success": 0,
            "missing_decision": 0,
            "missing_required_artifacts": 0,
            "validate_failed": 0,
            "other": 0,
        },
        # Debug sample lists (bounded, deterministic — sorted ascending)
        "_excluded_ids": [],
        "_excluded_ids_by_reason": {
            "not_success": [],
            "missing_decision": [],
            "missing_required_artifacts": [],
            "validate_failed": [],
            "other": [],
        },
    }


def _record_exclusion(
    coverage: Dict[str, Any], reason: str, run_id: str,
) -> None:
    """Increment exclusion counters and record run_id for debug samples."""
    coverage["runs_excluded"] += 1
    coverage["excluded_reasons"][reason] += 1
    coverage["_excluded_ids"].append(run_id)
    coverage["_excluded_ids_by_reason"][reason].append(run_id)


def discover_eligible_runs(
    ticker_dir: str,
    current_run_id: str,
) -> Tuple[List[str], Dict[str, Any]]:
    """Return eligible prior run IDs (sorted ascending) and coverage stats.

    Eligible means:
      - the folder contains a ``run_summary.json`` (or ``status.txt``)
        with status SUCCESS
      - ``DecisionRiskAgent/decision_action.json`` exists

    The *current* run is excluded (and not counted in coverage).

    Parameters
    ----------
    ticker_dir : str
        ``runs/<TICKER>/`` directory.
    current_run_id : str
        Run ID of the run being processed (to exclude).

    Returns
    -------
    Tuple[List[str], Dict[str, Any]]
        (eligible_ids, coverage_dict) where coverage_dict has keys:
        total_scanned, eligible_runs_found, runs_excluded, excluded_reasons.
    """
    eligible: List[str] = []
    coverage = _empty_coverage()

    if not os.path.isdir(ticker_dir):
        return eligible, coverage

    for name in sorted(os.listdir(ticker_dir)):
        # Skip hidden / special dirs (like _shadow_history)
        if name.startswith(("_", ".")):
            continue
        if name == current_run_id:
            continue

        run_path = os.path.join(ticker_dir, name)
        if not os.path.isdir(run_path):
            continue

        # This is a candidate run directory
        coverage["total_scanned"] += 1

        # Check SUCCESS status
        summary_path = os.path.join(run_path, "run_summary.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r") as f:
                    summary = json.load(f)
                if summary.get("status") != "SUCCESS":
                    _record_exclusion(coverage, "not_success", name)
                    continue
            except Exception:
                _record_exclusion(coverage, "not_success", name)
                continue
        else:
            # Fallback: check status.txt
            status_path = os.path.join(run_path, "status.txt")
            if not os.path.exists(status_path):
                _record_exclusion(coverage, "not_success", name)
                continue
            try:
                with open(status_path, "r") as f:
                    first_line = f.readline()
                if "SUCCESS" not in first_line:
                    _record_exclusion(coverage, "not_success", name)
                    continue
            except Exception:
                _record_exclusion(coverage, "not_success", name)
                continue

        # Check decision_action.json exists
        decision_path = os.path.join(
            run_path, "DecisionRiskAgent", "decision_action.json"
        )
        if not os.path.exists(decision_path):
            _record_exclusion(coverage, "missing_decision", name)
            continue

        eligible.append(name)

    coverage["eligible_runs_found"] = len(eligible)

    # Build bounded, deterministic sample lists.
    # _excluded_ids is already sorted ascending (input was sorted).
    coverage["excluded_run_ids_sample"] = (
        coverage.pop("_excluded_ids")[:_MAX_EXCLUDED_IDS_SAMPLE]
    )
    by_reason_raw = coverage.pop("_excluded_ids_by_reason")
    coverage["excluded_run_ids_by_reason_sample"] = {
        reason: ids[:_MAX_PER_REASON_SAMPLE]
        for reason, ids in by_reason_raw.items()
    }

    return eligible, coverage


def extract_run_row(run_dir: str, run_id: str) -> Dict[str, Any]:
    """Extract a single observation row from a completed run's artifacts.

    Returns a dict with keys:
        run_id, run_ts, decision, confidence, ma150_slope, atr_percentile
    Missing fields are ``None``.
    """
    row: Dict[str, Any] = {
        "run_id": run_id,
        "run_ts": _run_id_to_ts(run_id),
        "decision": None,
        "confidence": None,
        "ma150_slope": None,
        "atr_percentile": None,
    }

    # ── Decision ──
    decision_path = os.path.join(
        run_dir, "DecisionRiskAgent", "decision_action.json"
    )
    decision_data = _safe_load_json(decision_path)
    if decision_data is not None:
        row["decision"] = decision_data.get("action")
        row["confidence"] = decision_data.get("confidence")

    # ── Volatility regime (atr_ratio as atr_percentile proxy) ──
    regime_path = os.path.join(
        run_dir, "VolatilityRegimeAgent", "regime_latest.json"
    )
    regime_data = _safe_load_json(regime_path)
    if regime_data is not None:
        row["atr_percentile"] = regime_data.get("atr_ratio")
        # atr_slope can serve as a secondary drift indicator
        row["ma150_slope"] = regime_data.get("atr_slope")

    return row


def load_history(
    ticker_dir: str,
    run_ids: List[str],
) -> pd.DataFrame:
    """Load historical observation rows into a DataFrame.

    Parameters
    ----------
    ticker_dir : str
        ``runs/<TICKER>/`` directory.
    run_ids : List[str]
        List of eligible run_id strings.

    Returns
    -------
    pd.DataFrame
        Columns: run_id, run_ts, decision, confidence, ma150_slope,
        atr_percentile.  One row per run.
    """
    rows = []
    for rid in run_ids:
        run_dir = os.path.join(ticker_dir, rid)
        rows.append(extract_run_row(run_dir, rid))

    if not rows:
        return pd.DataFrame(
            columns=[
                "run_id", "run_ts", "decision", "confidence",
                "ma150_slope", "atr_percentile",
            ]
        )

    return pd.DataFrame(rows)


# ── Z-score computation ─────────────────────────────────────────────


def compute_zscore(
    latest_value: Optional[float],
    history_series: pd.Series,
) -> Optional[float]:
    """Compute z-score of *latest_value* relative to *history_series*.

    Returns None if:
      - latest_value is None / NaN
      - history has fewer than 2 non-null values
      - history std is 0
    """
    if latest_value is None:
        return None
    if pd.isna(latest_value):
        return None

    clean = history_series.dropna()
    if len(clean) < 2:
        return None

    mean = float(clean.mean())
    std = float(clean.std(ddof=1))
    if std == 0:
        return None

    return float((latest_value - mean) / std)


# ── Overall drift summary ───────────────────────────────────────────


def compute_decision_distribution(
    history_df: pd.DataFrame,
) -> Dict[str, float]:
    """Compute rolling proportions for ENTER / ABSTAIN / EXIT decisions.

    Returns a dict like {"ENTER": 0.3, "ABSTAIN": 0.7, "EXIT": 0.0}.
    """
    if len(history_df) == 0 or "decision" not in history_df.columns:
        return {"ENTER": 0.0, "ABSTAIN": 0.0, "EXIT": 0.0}

    counts = history_df["decision"].value_counts(normalize=True)
    return {
        "ENTER": float(counts.get("ENTER", 0.0)),
        "ABSTAIN": float(counts.get("ABSTAIN", 0.0)),
        "EXIT": float(counts.get("EXIT", 0.0)),
    }


def compute_drift_summary(
    history_df: pd.DataFrame,
    latest_row: Dict[str, Any],
    window_k: int = 60,
    min_k: int = 30,
    coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the full drift summary dict.

    Parameters
    ----------
    history_df : pd.DataFrame
        Historical rows (excluding the current run).
    latest_row : dict
        Current run's observation row.
    window_k : int
        Maximum number of prior runs to use (default 60).
    min_k : int
        Minimum required runs for OK status (default 30).
    coverage : dict, optional
        Coverage stats from ``discover_eligible_runs``.  When provided the
        counts are embedded in the returned summary.

    Returns
    -------
    dict
        Drift summary suitable for JSON serialisation.
    """
    # Trim history to last K runs
    if len(history_df) > window_k:
        history_df = history_df.iloc[-window_k:]

    n_history = len(history_df)

    # Status determination
    if n_history < min_k:
        drift_status = "INSUFFICIENT_HISTORY"
    else:
        drift_status = "OK"

    # Decision distribution (over history INCLUDING latest for context)
    combined = pd.concat(
        [history_df, pd.DataFrame([latest_row])],
        ignore_index=True,
    )
    decision_dist = compute_decision_distribution(combined)

    # Z-scores (latest vs history — current excluded from history)
    confidence_zscore = compute_zscore(
        latest_row.get("confidence"),
        history_df["confidence"] if "confidence" in history_df.columns else pd.Series(dtype=float),
    )
    ma150_slope_zscore = compute_zscore(
        latest_row.get("ma150_slope"),
        history_df["ma150_slope"] if "ma150_slope" in history_df.columns else pd.Series(dtype=float),
    )
    atr_percentile_zscore = compute_zscore(
        latest_row.get("atr_percentile"),
        history_df["atr_percentile"] if "atr_percentile" in history_df.columns else pd.Series(dtype=float),
    )

    # Overall drift flag
    available_zscores = [
        z for z in [confidence_zscore, ma150_slope_zscore, atr_percentile_zscore]
        if z is not None
    ]
    if drift_status == "INSUFFICIENT_HISTORY":
        overall_drift_flag = "OK"  # can't determine, default safe
    elif any(abs(z) >= 2.0 for z in available_zscores):
        overall_drift_flag = "WARN"
    else:
        overall_drift_flag = "OK"

    result = {
        "schema_version": "1.0",
        "drift_status": drift_status,
        "history_window_used": n_history,
        "history_window_max": window_k,
        "history_window_min_required": min_k,
        "decision_rate_enter": decision_dist.get("ENTER", 0.0),
        "decision_rate_abstain": decision_dist.get("ABSTAIN", 0.0),
        "decision_rate_exit": decision_dist.get("EXIT", 0.0),
        "confidence_mean_zscore": confidence_zscore,
        "ma150_slope_drift_zscore": ma150_slope_zscore,
        "atr_percentile_drift_zscore": atr_percentile_zscore,
        "overall_drift_flag": overall_drift_flag,
        "latest_run_id": latest_row.get("run_id"),
        "latest_decision": latest_row.get("decision"),
    }

    # Embed coverage telemetry (optional, backward compatible)
    if coverage is not None:
        result["total_runs_scanned"] = coverage.get("total_scanned", 0)
        result["eligible_runs_found"] = coverage.get("eligible_runs_found", 0)
        result["runs_used_in_window"] = n_history
        result["runs_excluded"] = coverage.get("runs_excluded", 0)
        result["excluded_reasons"] = coverage.get("excluded_reasons", {})
        result["excluded_run_ids_sample"] = coverage.get(
            "excluded_run_ids_sample", []
        )
        result["excluded_run_ids_by_reason_sample"] = coverage.get(
            "excluded_run_ids_by_reason_sample", {}
        )

    # Human-readable one-liner (additive, optional)
    result["drift_reason_summary"] = _build_reason_summary(result)

    return result


def build_timeseries_row(
    latest_row: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a single timeseries row combining raw values and z-scores.

    Used for drift_timeseries.parquet (one row per run).
    """
    return {
        "run_id": latest_row.get("run_id"),
        "run_ts": latest_row.get("run_ts"),
        "decision": latest_row.get("decision"),
        "confidence": latest_row.get("confidence"),
        "ma150_slope": latest_row.get("ma150_slope"),
        "atr_percentile": latest_row.get("atr_percentile"),
        "confidence_zscore": summary.get("confidence_mean_zscore"),
        "ma150_slope_zscore": summary.get("ma150_slope_drift_zscore"),
        "atr_percentile_zscore": summary.get("atr_percentile_drift_zscore"),
        "overall_flag": summary.get("overall_drift_flag"),
    }


# ── Reason summary (human-readable one-liner) ───────────────────────

_MAX_REASON_SUMMARY_LEN = 120


def _build_reason_summary(summary: Dict[str, Any]) -> str:
    """Build a compact human-readable drift reason string.

    Rules:
      - INSUFFICIENT_HISTORY / ERROR → status description
      - WARN → list which z-scores triggered (|z| >= 2, not None)
      - OK → "OK: no 2-sigma drift detected"
      - Truncate to 120 chars with ellipsis if needed.
    """
    status = summary.get("drift_status", "OK")
    flag = summary.get("overall_drift_flag", "OK")

    if status == "INSUFFICIENT_HISTORY":
        min_k = summary.get("history_window_min_required", 30)
        text = f"STATUS=INSUFFICIENT_HISTORY (need >={min_k} runs)"
    elif status == "ERROR":
        text = "STATUS=ERROR"
    elif flag == "WARN":
        # Stable ordering: confidence, ma150_slope, atr_percentile
        triggers = []
        _METRIC_KEYS = [
            ("confidence", "confidence_mean_zscore"),
            ("ma150_slope", "ma150_slope_drift_zscore"),
            ("atr_percentile", "atr_percentile_drift_zscore"),
        ]
        for label, key in _METRIC_KEYS:
            z = summary.get(key)
            if z is not None and abs(z) >= 2.0:
                triggers.append(f"{label} z={z:+.1f}")
        text = "WARN: " + "; ".join(triggers) if triggers else "WARN: unknown trigger"
    else:
        text = "OK: no 2-sigma drift detected"

    if len(text) > _MAX_REASON_SUMMARY_LEN:
        text = text[:_MAX_REASON_SUMMARY_LEN - 1] + "\u2026"
    return text


# ── Private helpers ──────────────────────────────────────────────────


def _run_id_to_ts(run_id: str) -> Optional[str]:
    """Parse a run_id like ``20260214_151806_xaji0y`` into ISO timestamp.

    Returns None on parse failure.
    """
    try:
        # First 15 chars: YYYYMMDD_HHMMSS
        ts_part = run_id[:15]
        from datetime import datetime
        dt = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
        return dt.isoformat()
    except (ValueError, IndexError):
        return None


def _safe_load_json(path: str) -> Optional[Dict[str, Any]]:
    """Load JSON file, returning None on any error."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
