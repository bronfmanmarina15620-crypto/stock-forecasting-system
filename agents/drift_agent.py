"""
DriftAgent - Shadow History drift/quality metrics.

Reads prior successful runs from ``runs/<TICKER>/`` and computes
z-score-based drift metrics by comparing the current run's key
observables against the historical distribution.

Runs AFTER BacktestAgent (needs decision + regime artifacts) and
BEFORE DashboardAgent (dashboard reads drift_summary.json).

Outputs (under ``DriftAgent/``):
  - ``drift_summary.json``         — stable schema with drift status
  - ``drift_timeseries.parquet``   — one row per historical run + current
  - ``status.txt``                 — plain text status line

Fail-safe: if history is missing or too short, emits
``drift_status="INSUFFICIENT_HISTORY"`` and never crashes.
"""

import json
import os
from typing import Any, Dict

import pandas as pd

from .base_agent import BaseAgent
from analytics.drift_metrics import (
    build_timeseries_row,
    compute_drift_summary,
    discover_eligible_runs,
    extract_run_row,
    load_history,
)


# Default history window parameters
_DEFAULT_WINDOW_K = 60
_DEFAULT_MIN_K = 30


class DriftAgent(BaseAgent):
    """Compute drift metrics from shadow run history."""

    def run(self) -> Dict[str, Any]:
        self.logger.info("Starting drift analysis")

        try:
            run_id = os.path.basename(self.run_dir)
            ticker_dir = os.path.dirname(self.run_dir)

            # ── 1. Discover eligible prior runs ──────────────────────
            eligible_ids, coverage = discover_eligible_runs(ticker_dir, run_id)
            self.logger.info(
                f"Found {len(eligible_ids)} eligible prior runs "
                f"(scanned {coverage['total_scanned']}, "
                f"excluded {coverage['runs_excluded']})"
            )

            # ── 2. Load history ──────────────────────────────────────
            history_df = load_history(ticker_dir, eligible_ids)

            # ── 3. Extract current run row ───────────────────────────
            latest_row = extract_run_row(self.run_dir, run_id)

            # ── 4. Compute drift summary ─────────────────────────────
            summary = compute_drift_summary(
                history_df,
                latest_row,
                window_k=_DEFAULT_WINDOW_K,
                min_k=_DEFAULT_MIN_K,
                coverage=coverage,
            )

            # ── 5. Build timeseries row ──────────────────────────────
            ts_row = build_timeseries_row(latest_row, summary)

            # Combine history + current for the timeseries parquet
            ts_rows = []
            for rid in eligible_ids[-_DEFAULT_WINDOW_K:]:
                rd = os.path.join(ticker_dir, rid)
                row = extract_run_row(rd, rid)
                # For historical rows, z-scores are not individually computed
                # (they are relative to the window at the time of that run)
                ts_rows.append({
                    "run_id": row["run_id"],
                    "run_ts": row["run_ts"],
                    "decision": row["decision"],
                    "confidence": row["confidence"],
                    "ma150_slope": row["ma150_slope"],
                    "atr_percentile": row["atr_percentile"],
                    "confidence_zscore": None,
                    "ma150_slope_zscore": None,
                    "atr_percentile_zscore": None,
                    "overall_flag": None,
                })
            # Append current run with z-scores
            ts_rows.append(ts_row)

            ts_df = pd.DataFrame(ts_rows)

            # ── 6. Persist artifacts ─────────────────────────────────
            self._write_json("drift_summary.json", summary)

            ts_path = os.path.join(self.agent_dir, "drift_timeseries.parquet")
            ts_df.to_parquet(ts_path, index=False)
            self.logger.info("Wrote drift_timeseries.parquet")

            status_line = (
                f"drift_status={summary['drift_status']} "
                f"overall_flag={summary['overall_drift_flag']} "
                f"history_n={summary['history_window_used']}"
            )
            status_path = os.path.join(self.agent_dir, "status.txt")
            with open(status_path, "w") as f:
                f.write(status_line + "\n")

            # ── 7. Return output ─────────────────────────────────────
            output = {
                "status": "SUCCESS",
                "drift_status": summary["drift_status"],
                "overall_drift_flag": summary["overall_drift_flag"],
                "history_window_used": summary["history_window_used"],
            }
            self.save_output(output)
            self.logger.info(
                f"Drift analysis complete: {status_line}"
            )
            return output

        except Exception as e:
            self.logger.error(f"Drift analysis failed: {e}")
            # Fail-safe: emit degraded output, never crash the pipeline
            fallback_summary = {
                "schema_version": "1.0",
                "drift_status": "ERROR",
                "overall_drift_flag": "OK",
                "history_window_used": 0,
                "history_window_max": _DEFAULT_WINDOW_K,
                "history_window_min_required": _DEFAULT_MIN_K,
                "decision_rate_enter": None,
                "decision_rate_abstain": None,
                "decision_rate_exit": None,
                "confidence_mean_zscore": None,
                "ma150_slope_drift_zscore": None,
                "atr_percentile_drift_zscore": None,
                "latest_run_id": None,
                "latest_decision": None,
                "total_runs_scanned": 0,
                "eligible_runs_found": 0,
                "runs_used_in_window": 0,
                "runs_excluded": 0,
                "excluded_reasons": {
                    "not_success": 0,
                    "missing_decision": 0,
                    "missing_required_artifacts": 0,
                    "validate_failed": 0,
                    "other": 0,
                },
                "excluded_run_ids_sample": [],
                "excluded_run_ids_by_reason_sample": {},
                "error": str(e),
            }
            try:
                self._write_json("drift_summary.json", fallback_summary)
                status_path = os.path.join(self.agent_dir, "status.txt")
                with open(status_path, "w") as f:
                    f.write(f"drift_status=ERROR error={e}\n")
            except Exception:
                pass

            output = {
                "status": "SUCCESS",
                "drift_status": "ERROR",
                "overall_drift_flag": "OK",
                "history_window_used": 0,
            }
            self.save_output(output)
            return output

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _write_json(self, filename: str, data: dict) -> None:
        path = os.path.join(self.agent_dir, filename)
        from determinism import dump_canonical_json
        dump_canonical_json(path, data)
        self.logger.info(f"Wrote {filename}")
