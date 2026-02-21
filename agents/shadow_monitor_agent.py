"""
ShadowMonitorAgent - Phase 7: monitoring-only shadow run.

Reads outputs from upstream agents (StrategyAgent, DecisionRiskAgent,
BacktestAgent, RegimeAgent) and produces compact drift/monitoring
artifacts.  NEVER places orders or calls any broker API.

Outputs (under ``ShadowMonitorAgent/``):
  - ``shadow_metrics.json``  — full monitoring payload
  - ``shadow_summary.json``  — single-line oriented summary

Both include ``content_hash_sha256`` for determinism validation.

A per-ticker append-only history JSONL is maintained at
``runs/<TICKER>/_shadow_history/shadow_history.jsonl`` for rolling
metrics.  This file is *stateful* and excluded from determinism checks.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent
from determinism import content_hash_sha256


class ShadowMonitorAgent(BaseAgent):
    """Monitoring-only agent for shadow (paper-run) mode."""

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        self.logger.info("Starting shadow monitoring")

        drift_flags: List[str] = []
        status = "OK"

        # ── collect upstream data (defensive) ────────────────────────
        decision_data = self._load_decision()
        if decision_data is None:
            drift_flags.append("MISSING_DECISION")
            status = "DEGRADED"

        strategy_data = self._load_strategy_output()
        if strategy_data is None:
            drift_flags.append("MISSING_STRATEGY")

        regime_data = self._load_regime_output()
        if regime_data is None:
            drift_flags.append("MISSING_REGIME")

        backtest_metrics = self._load_backtest_metrics()
        if backtest_metrics is None:
            drift_flags.append("MISSING_BACKTEST_METRICS")

        # ── derived fields ───────────────────────────────────────────
        run_id = os.path.basename(self.run_dir)
        ticker = self.config.ticker
        asof_date = self._resolve_asof_date(decision_data)
        decision = self._extract(decision_data, "action", "UNKNOWN")
        confidence = self._extract(decision_data, "confidence", None)
        regime_label = self._extract_regime_label(regime_data)
        ma150_distance_pct = self._extract_ma150_distance(strategy_data)
        atr_value = self._extract_atr(strategy_data)

        # ── rolling history ──────────────────────────────────────────
        enter_rolling_20 = self._update_history_and_compute_rolling(
            ticker, run_id, asof_date, decision, regime_label, status,
        )

        # ── build shadow_metrics ─────────────────────────────────────
        shadow_metrics: Dict[str, Any] = {
            "run_id": run_id,
            "ticker": ticker,
            "mode": "shadow",
            "asof_date": asof_date,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "confidence": confidence,
            "regime_label": regime_label,
            "ma150_distance_pct": ma150_distance_pct,
            "atr_value": atr_value,
            "enter_rolling_20": enter_rolling_20,
            "drift_flags": drift_flags,
            "status": status,
        }
        shadow_metrics["content_hash_sha256"] = content_hash_sha256(
            shadow_metrics
        )

        # ── build shadow_summary ─────────────────────────────────────
        shadow_summary: Dict[str, Any] = {
            "run_id": run_id,
            "ticker": ticker,
            "decision": decision,
            "regime_label": regime_label,
            "status": status,
            "top_flag": drift_flags[0] if drift_flags else None,
        }
        shadow_summary["content_hash_sha256"] = content_hash_sha256(
            shadow_summary
        )

        # ── persist artifacts ────────────────────────────────────────
        self._write_json("shadow_metrics.json", shadow_metrics)
        self._write_json("shadow_summary.json", shadow_summary)

        output = {
            "status": "SUCCESS",
            "shadow_decision": decision,
            "shadow_regime": regime_label,
            "shadow_status": status,
            "drift_flags": drift_flags,
        }
        self.save_output(output)
        self.logger.info(
            f"Shadow monitoring complete: decision={decision}, "
            f"regime={regime_label}, status={status}"
        )
        return output

    # ------------------------------------------------------------------
    # upstream loaders (defensive — never crash)
    # ------------------------------------------------------------------

    def _load_decision(self) -> Optional[Dict[str, Any]]:
        path = os.path.join(
            self.run_dir, "DecisionRiskAgent", "decision_action.json"
        )
        return self._safe_load_json(path)

    def _load_strategy_output(self) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.run_dir, "StrategyAgent", "output.json")
        return self._safe_load_json(path)

    def _load_regime_output(self) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.run_dir, "RegimeAgent", "output.json")
        return self._safe_load_json(path)

    def _load_backtest_metrics(self) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.run_dir, "BacktestAgent", "metrics.json")
        return self._safe_load_json(path)

    # ------------------------------------------------------------------
    # field extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _extract(data: Optional[dict], key: str, default: Any) -> Any:
        if data is None:
            return default
        return data.get(key, default)

    @staticmethod
    def _extract_regime_label(regime_data: Optional[dict]) -> str:
        if regime_data is None:
            return "na"
        # recent_regime may be top-level or nested under regime_definition
        label = regime_data.get("recent_regime")
        if label is None:
            rd = regime_data.get("regime_definition", {})
            label = rd.get("recent_regime")
        return label or "na"

    @staticmethod
    def _extract_ma150_distance(strategy_data: Optional[dict]) -> Optional[float]:
        if strategy_data is None:
            return None
        return strategy_data.get("ma150_distance_pct")

    @staticmethod
    def _extract_atr(strategy_data: Optional[dict]) -> Optional[float]:
        if strategy_data is None:
            return None
        return strategy_data.get("atr_latest")

    @staticmethod
    def _resolve_asof_date(decision_data: Optional[dict]) -> str:
        if decision_data is not None and "date" in decision_data:
            return str(decision_data["date"])
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # rolling history (append-only JSONL, per ticker)
    # ------------------------------------------------------------------

    def _update_history_and_compute_rolling(
        self,
        ticker: str,
        run_id: str,
        asof_date: str,
        decision: str,
        regime_label: str,
        status: str,
    ) -> Optional[int]:
        """Append one line to shadow_history.jsonl and return ENTER count
        over the last 20 entries (including the new one)."""
        # Resolve base: go up from run_dir to the ticker directory
        ticker_dir = os.path.dirname(self.run_dir)
        history_dir = os.path.join(ticker_dir, "_shadow_history")
        os.makedirs(history_dir, exist_ok=True)
        history_path = os.path.join(history_dir, "shadow_history.jsonl")

        entry = {
            "run_id": run_id,
            "asof_date": asof_date,
            "decision": decision,
            "regime_label": regime_label,
            "status": status,
        }

        # Atomic append
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

        # Read back and compute rolling ENTER count over last 20 lines
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tail = lines[-20:]
            enter_count = sum(
                1 for ln in tail
                if json.loads(ln).get("decision") == "ENTER"
            )
            return enter_count
        except Exception:
            return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _safe_load_json(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            self.logger.warning(f"File not found (degraded): {path}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            self.logger.warning(f"Failed to load {path}: {exc}")
            return None

    def _write_json(self, filename: str, data: dict) -> None:
        path = os.path.join(self.agent_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        self.logger.info(f"Wrote {filename}")
