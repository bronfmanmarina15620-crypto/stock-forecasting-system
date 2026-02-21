"""
DecisionRiskAgent - Converts signals into ENTER/ABSTAIN decisions.

Phase 2 integration:
    StrategyAgent (MA150+ATR) runs before this agent and produces
    strategy_signals.parquet with entry_signal, regime_ok, range_high_vol,
    position, stop_price.

    The current decision uses STRATEGY signals (entry_signal / position).
    Historical ML-based signals (from BacktestAgent) are preserved for
    backward-compatible metrics and validation.
"""

import json
import os

import pandas as pd
import numpy as np
from typing import Dict, Any

from .base_agent import BaseAgent
from determinism import content_hash_sha256

_VALID_ACTIONS = {"ENTER", "ABSTAIN"}


def _validate_decision_action(decision: Dict[str, Any]) -> None:
    """Validate decision_action invariants for Phase 2.

    Raises ValueError on any violation:
    - action must be ENTER or ABSTAIN (long-only, no EXIT/UNKNOWN)
    - ENTER requires position == 1
    - ABSTAIN requires non-empty "because" list
    """
    action = decision.get("action")
    if action not in _VALID_ACTIONS:
        raise ValueError(
            f"decision_action invalid action: '{action}'. "
            f"Must be one of {_VALID_ACTIONS}"
        )
    if action == "ENTER":
        if decision.get("position") != 1:
            raise ValueError(
                f"decision_action ENTER requires position=1, "
                f"got position={decision.get('position')}"
            )
    if action == "ABSTAIN":
        because = decision.get("because", [])
        if not because:
            raise ValueError(
                "decision_action ABSTAIN requires non-empty 'because' list"
            )


class DecisionRiskAgent(BaseAgent):
    """Agent responsible for decision making and risk assessment."""

    def run(self) -> Dict[str, Any]:
        """Generate trading decisions."""
        self.logger.info("Starting decision generation")

        try:
            # ----------------------------------------------------------
            # Load ML pipeline outputs (backward compat)
            # ----------------------------------------------------------
            backtest_output = self.load_agent_output("BacktestAgent")
            model_output = self.load_agent_output("EventModelAgent")
            regime_output = self.load_agent_output("RegimeAgent")

            if any(
                o["status"] not in ["SUCCESS", "WARNING"]
                for o in [backtest_output, model_output, regime_output]
            ):
                return {"status": "FAILED", "error": "Dependencies failed"}

            # Search legacy_ml/ subfolder first, then top-level, then empty
            predictions_path = os.path.join(
                self.run_dir, "BacktestAgent", "legacy_ml",
                "predictions_oos.parquet",
            )
            if not os.path.exists(predictions_path):
                predictions_path = os.path.join(
                    self.run_dir, "BacktestAgent",
                    "predictions_oos.parquet",
                )
            if os.path.exists(predictions_path):
                predictions = pd.read_parquet(predictions_path)
            else:
                predictions = pd.DataFrame(
                    columns=[
                        "date", "y_true", "y_pred_proba", "regime", "price",
                    ]
                )

            # ----------------------------------------------------------
            # Load strategy signals (Phase 2)
            # ----------------------------------------------------------
            strategy_output = self.load_agent_output("StrategyAgent")
            strategy_signals = pd.read_parquet(
                os.path.join(self.run_dir, "StrategyAgent", "strategy_signals.parquet")
            )
            strategy_explain_path = os.path.join(
                self.run_dir, "StrategyAgent", "strategy_explain.json"
            )
            with open(strategy_explain_path, "r") as f:
                strategy_explain = json.load(f)

            # ----------------------------------------------------------
            # Generate ML-based signals (backward compat for metrics)
            # ----------------------------------------------------------
            signals = self._generate_signals(predictions)

            # Calculate strategy P&L (ML-based, backward compat)
            strategy_pnl = self._calculate_strategy_pnl(signals)

            # Create decision explanation
            decision_explain = self._create_decision_explanation(
                signals, strategy_pnl, strategy_output
            )

            # ----------------------------------------------------------
            # Current decision from STRATEGY (Phase 2)
            # ----------------------------------------------------------
            decision_action = self._get_current_decision_strategy(
                strategy_signals, strategy_explain
            )

            # ----------------------------------------------------------
            # Phase 5: Volatility regime override
            # ----------------------------------------------------------
            decision_action = self._apply_volatility_regime(decision_action)

            # Generate abstain stats
            abstain_stats = self._generate_abstain_stats(signals, decision_explain)

            # Validate decision invariants before persisting
            _validate_decision_action(decision_action)

            # Embed deterministic content fingerprint
            decision_action["content_hash_sha256"] = content_hash_sha256(
                decision_action
            )

            # Save artifacts
            self.save_artifact("signals.csv", signals)
            self.save_artifact("decision_explain.json", decision_explain)
            self.save_artifact("strategy_pnl.parquet", strategy_pnl)
            self.save_artifact("decision_action.json", decision_action)
            self.save_artifact("abstain_stats.json", abstain_stats)

            # Prepare output
            output = {
                "status": "SUCCESS",
                "signals_path": self.get_artifact_path("signals.csv"),
                "decision_action": decision_action,
                "decision_stats": decision_explain,
            }

            self.save_output(output)
            self.logger.info("Decision generation complete")
            return output

        except Exception as e:
            self.logger.error(f"Decision generation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"status": "FAILED", "error": str(e)}

    # ------------------------------------------------------------------
    # ML-based signal generation (backward compat)
    # ------------------------------------------------------------------

    def _generate_signals(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """Generate ENTER/ABSTAIN signals from ML predictions.

        Default: ABSTAIN.  ENTER if probability > threshold AND regime allowed.
        """
        signals = predictions.copy()
        signals["action"] = self.config.decision.default_action

        prob_threshold = self.config.decision.probability_threshold
        allowed_regimes = self.config.decision.allowed_regimes

        # Find probability column
        prob_col = None
        for name in ["y_pred_proba", "y_pred", "probability", "prob"]:
            if name in signals.columns:
                prob_col = name
                break
        if prob_col is None:
            for col in signals.columns:
                if "pred" in col.lower() or "prob" in col.lower():
                    prob_col = col
                    break
        if prob_col is None:
            raise ValueError(
                f"Cannot find probability column in: {signals.columns.tolist()}"
            )

        enter_condition = (signals[prob_col] > prob_threshold) & (
            signals["regime"].isin(allowed_regimes)
        )
        signals.loc[enter_condition, "action"] = "ENTER"
        return signals

    def _calculate_strategy_pnl(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Calculate strategy P&L with realistic frictions."""
        pnl = signals.copy()
        pnl["forward_return"] = pnl["y_true"] * (
            self.config.event.threshold_pct / 100
        )

        commission = self.config.backtest.commission_pct
        spread = self.config.backtest.spread_bps / 10000
        slippage = self.config.backtest.slippage_bps / 10000
        total_friction = commission + spread + slippage

        pnl["strategy_return"] = 0.0
        enter_mask = pnl["action"] == "ENTER"
        pnl.loc[enter_mask, "strategy_return"] = (
            pnl.loc[enter_mask, "forward_return"] - (total_friction * 2)
        )

        pnl["cum_return"] = (1 + pnl["strategy_return"]).cumprod()
        pnl["cum_max"] = pnl["cum_return"].cummax()
        pnl["drawdown"] = (pnl["cum_return"] - pnl["cum_max"]) / pnl["cum_max"]
        return pnl

    def _create_decision_explanation(
        self,
        signals: pd.DataFrame,
        strategy_pnl: pd.DataFrame,
        strategy_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create explanation of decision statistics."""
        total_days = len(signals)
        enter_days = int((signals["action"] == "ENTER").sum())
        abstain_days = int((signals["action"] == "ABSTAIN").sum())

        enter_returns = strategy_pnl[strategy_pnl["action"] == "ENTER"][
            "strategy_return"
        ]
        ev_per_signal = float(enter_returns.mean()) if len(enter_returns) > 0 else 0.0
        max_dd = (
            float(strategy_pnl["drawdown"].min())
            if len(strategy_pnl) > 0 else 0.0
        )

        if total_days > 0:
            signals["date"] = pd.to_datetime(signals["date"])
            signals_per_month = float(
                signals.groupby(signals["date"].dt.to_period("M"))["action"]
                .apply(lambda x: (x == "ENTER").sum())
                .mean()
            )
        else:
            signals_per_month = 0.0

        win_rate = (
            float((enter_returns > 0).mean()) if len(enter_returns) > 0 else 0.0
        )

        return {
            "total_days": total_days,
            "enter_days": enter_days,
            "abstain_days": abstain_days,
            "abstain_percentage": float(abstain_days / total_days * 100) if total_days > 0 else 100.0,
            "signals_per_month": float(signals_per_month),
            "expected_value_per_signal": ev_per_signal,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "decision_rules": {
                "probability_threshold": self.config.decision.probability_threshold,
                "allowed_regimes": self.config.decision.allowed_regimes,
            },
            "strategy_summary": {
                "strategy": strategy_output.get("strategy", "MA150_ATR"),
                "params": strategy_output.get("params", {}),
                "entries": strategy_output.get("entries", 0),
                "exits": strategy_output.get("exits", 0),
                "days_in_position": strategy_output.get("days_in_position", 0),
                "regime_ok_days": strategy_output.get("regime_ok_days", 0),
                "range_high_vol_days": strategy_output.get("range_high_vol_days", 0),
            },
        }

    # ------------------------------------------------------------------
    # Strategy-based current decision (Phase 2)
    # ------------------------------------------------------------------

    def _get_current_decision_strategy(
        self,
        strategy_signals: pd.DataFrame,
        strategy_explain: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get current decision from MA150+ATR strategy signals.

        action = ENTER if position=1 (in position), ABSTAIN if position=0.
        """
        if len(strategy_signals) == 0:
            return {"action": "ABSTAIN", "because": ["No strategy data available"]}

        last = strategy_signals.iloc[-1]
        last_date = (
            str(last.name.date()) if hasattr(last.name, "date") else str(last.name)
        )

        position = int(last["position"])
        action = "ENTER" if position == 1 else "ABSTAIN"

        # Get reasons for this day
        reasons = strategy_explain.get(last_date, [])

        stop = float(last["stop_price"]) if not pd.isna(last["stop_price"]) else None

        return {
            "action": action,
            "regime_ok": bool(last["regime_ok"]) if not pd.isna(last["regime_ok"]) else False,
            "range_high_vol": bool(last["range_high_vol"]) if not pd.isna(last["range_high_vol"]) else False,
            "ma150_trend_ok": bool(last["ma150_trend_ok"]) if not pd.isna(last["ma150_trend_ok"]) else False,
            "entry_signal": bool(last["entry_signal"]),
            "exit_signal": bool(last["exit_signal"]),
            "position": position,
            "stop_price": stop,
            "because": reasons,
            "date": last_date,
        }

    # ------------------------------------------------------------------
    # Phase 5: Volatility regime filter
    # ------------------------------------------------------------------

    def _apply_volatility_regime(
        self, decision_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply Phase 5 volatility regime filter to the decision.

        - If regime == EXTREME: force ABSTAIN regardless of strategy signal.
        - Attach size multiplier fields for downstream consumers.
        """
        # Load volatility regime latest (safe fallback if agent disabled)
        vr_latest_path = os.path.join(
            self.run_dir, "VolatilityRegimeAgent", "regime_latest.json"
        )
        if not os.path.exists(vr_latest_path):
            # Agent not present or disabled — no override
            decision_action["volatility_regime"] = None
            decision_action["volatility_size_multiplier"] = 1.0
            return decision_action

        with open(vr_latest_path, "r") as f:
            vr_latest = json.load(f)

        regime = vr_latest.get("regime", "NORMAL")
        multiplier = float(vr_latest.get("multiplier", 1.0))

        # Attach volatility info to decision
        decision_action["volatility_regime"] = regime
        decision_action["volatility_size_multiplier"] = multiplier

        # EXTREME blocks ENTER -> force ABSTAIN
        if regime == "EXTREME" and decision_action.get("action") == "ENTER":
            decision_action["action"] = "ABSTAIN"
            decision_action["position"] = 0
            because = decision_action.get("because", [])
            if not isinstance(because, list):
                because = []
            because.append("blocked_by_volatility_regime_extreme")
            decision_action["because"] = because
            self.logger.info(
                "Phase 5: EXTREME volatility regime — "
                "forced ABSTAIN (blocked ENTER)"
            )

        # Ensure ABSTAIN has a because list (validator requirement)
        if decision_action.get("action") == "ABSTAIN":
            because = decision_action.get("because", [])
            if not because:
                decision_action["because"] = ["No entry signal"]

        return decision_action

    def _generate_abstain_stats(
        self, signals: pd.DataFrame, decision_explain: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate abstain statistics required by validator."""
        total = len(signals)
        enter_count = int((signals["action"] == "ENTER").sum())
        abstain_count = int((signals["action"] == "ABSTAIN").sum())

        return {
            "abstain_ratio": float(abstain_count / total) if total > 0 else 1.0,
            "enter_count": enter_count,
            "abstain_count": abstain_count,
            "signals_per_month": decision_explain.get("signals_per_month", 0.0),
            "total_days": total,
        }
