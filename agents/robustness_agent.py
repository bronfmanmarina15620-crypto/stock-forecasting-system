"""
RobustnessAgent — Phase 6: Robustness & Statistical Validation.

Produces evaluation/validation outputs WITHOUT changing any trading logic.
All outputs are deterministic given identical input data.

Artifacts (under RobustnessAgent/):
    walk_forward.json       Per-window walk-forward stats
    walk_forward.csv        Same, tabular
    sensitivity_map.json    Grid search around strategy params
    sensitivity_map.csv     Same, tabular
    monte_carlo.json        Trade-sequence reshuffle simulation
    monte_carlo.csv         Distribution summary percentiles
    exposure_decomposition.json
    regime_contribution.json
    capacity_test.json
    summary.json            Top-level summary + key risk stats
"""

import math
import os
import json
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .base_agent import BaseAgent
from determinism import content_hash_sha256


# ============================================================
# Constants
# ============================================================

_DEFAULT_WALK_FORWARD_WINDOWS = 6
_MONTE_CARLO_N = 1000
_MONTE_CARLO_SEED = 20260221  # fixed seed for determinism

# Sensitivity grid multipliers around base values
_ATR_MULT_FACTORS = [0.8, 0.9, 1.0, 1.1, 1.2]
_RISK_PCT_FACTORS = [0.5, 0.75, 1.0, 1.25, 1.5]


class RobustnessAgent(BaseAgent):
    """Phase 6 robustness & statistical validation agent."""

    def run(self) -> Dict[str, Any]:
        """Execute all robustness computations."""
        self.logger.info("Starting Phase 6 robustness validation")

        try:
            # ---- Load upstream artifacts ----
            data_output = self.load_agent_output("DataAgent")
            backtest_output = self.load_agent_output("BacktestAgent")
            strategy_output = self.load_agent_output("StrategyAgent")

            prices_df = pd.read_parquet(data_output["data_path"])
            close = prices_df["Close"]
            volume = prices_df["Volume"] if "Volume" in prices_df.columns else None

            trades_path = os.path.join(
                self.run_dir, "BacktestAgent", "trades.parquet"
            )
            trades = pd.read_parquet(trades_path)

            pnl_path = os.path.join(
                self.run_dir, "BacktestAgent", "pnl_series.parquet"
            )
            pnl_series = pd.read_parquet(pnl_path)

            metrics_path = os.path.join(
                self.run_dir, "BacktestAgent", "metrics.json"
            )
            with open(metrics_path, "r") as f:
                bt_metrics = json.load(f)

            signals_path = os.path.join(
                self.run_dir, "StrategyAgent", "strategy_signals.parquet"
            )
            strategy_signals = pd.read_parquet(signals_path)

            # ---- Config snapshot ----
            strategy_cfg = self.config.strategy
            backtest_cfg = self.config.backtest

            # ---- Run each analysis ----
            walk_forward = self._walk_forward_validation(
                strategy_signals, close, trades, pnl_series
            )
            sensitivity = self._parameter_sensitivity(
                strategy_signals, close, strategy_cfg, backtest_cfg
            )
            monte_carlo = self._monte_carlo_reshuffle(trades)
            exposure = self._exposure_decomposition(
                pnl_series, strategy_signals, close
            )
            regime_contrib = self._regime_contribution(trades)
            capacity = self._capacity_test(close, volume, backtest_cfg)

            # ---- Build summary ----
            summary = self._build_summary(
                walk_forward, sensitivity, monte_carlo,
                exposure, regime_contrib, capacity, bt_metrics,
            )

            # ---- Embed content hashes for determinism verification ----
            for artifact in (walk_forward, sensitivity, monte_carlo,
                             exposure, regime_contrib, capacity, summary):
                artifact["content_hash_sha256"] = content_hash_sha256(artifact)

            # ---- Save all artifacts ----
            self.save_artifact("walk_forward.json", walk_forward)
            self.save_artifact("sensitivity_map.json", sensitivity)
            self.save_artifact("monte_carlo.json", monte_carlo)
            self.save_artifact("exposure_decomposition.json", exposure)
            self.save_artifact("regime_contribution.json", regime_contrib)
            self.save_artifact("capacity_test.json", capacity)
            self.save_artifact("summary.json", summary)

            # CSV companions
            self._save_walk_forward_csv(walk_forward)
            self._save_sensitivity_csv(sensitivity)
            self._save_monte_carlo_csv(monte_carlo)

            output = {
                "status": "SUCCESS",
                "summary": summary,
            }
            self.save_output(output)
            self.logger.info("Phase 6 robustness validation complete")
            return output

        except Exception as e:
            self.logger.error(f"Robustness validation failed: {e}")
            import traceback
            traceback.print_exc()
            return {"status": "FAILED", "error": str(e)}

    # ==================================================================
    # A) Walk-Forward Validation
    # ==================================================================

    def _walk_forward_validation(
        self,
        strategy_signals: pd.DataFrame,
        close: pd.Series,
        trades: pd.DataFrame,
        pnl_series: pd.DataFrame,
        n_windows: int = _DEFAULT_WALK_FORWARD_WINDOWS,
    ) -> Dict[str, Any]:
        """Rolling train/test window evaluation using same strategy params.

        Does NOT refit — re-evaluates the identical strategy on each segment.
        """
        idx = strategy_signals.index
        n = len(idx)
        if n < 2 or n_windows < 1:
            return {"windows": [], "n_windows": 0}

        # Divide the data into n_windows+1 equal blocks; each window's
        # test set is one block, and everything before it is the "train" set.
        block_size = n // (n_windows + 1)
        if block_size < 10:
            # Not enough data for meaningful windows
            return {"windows": [], "n_windows": 0}

        windows: List[Dict[str, Any]] = []

        for w in range(n_windows):
            train_start_i = 0
            train_end_i = (w + 1) * block_size - 1
            test_start_i = (w + 1) * block_size
            test_end_i = min((w + 2) * block_size - 1, n - 1)

            if test_start_i >= n or test_end_i <= test_start_i:
                continue

            test_start_date = str(idx[test_start_i].date()) if hasattr(idx[test_start_i], "date") else str(idx[test_start_i])
            test_end_date = str(idx[test_end_i].date()) if hasattr(idx[test_end_i], "date") else str(idx[test_end_i])
            train_start_date = str(idx[train_start_i].date()) if hasattr(idx[train_start_i], "date") else str(idx[train_start_i])
            train_end_date = str(idx[train_end_i].date()) if hasattr(idx[train_end_i], "date") else str(idx[train_end_i])

            # Filter trades whose entry_date falls in the test window
            window_trades = self._filter_trades_by_date(
                trades, test_start_date, test_end_date
            )

            # Filter pnl_series to test window
            pnl_slice = pnl_series.iloc[test_start_i:test_end_i + 1]

            stats = self._window_stats(
                window_trades, pnl_slice, test_start_i, test_end_i
            )
            stats.update({
                "window": w + 1,
                "train_start": train_start_date,
                "train_end": train_end_date,
                "test_start": test_start_date,
                "test_end": test_end_date,
            })
            windows.append(stats)

        return {
            "windows": windows,
            "n_windows": len(windows),
        }

    def _filter_trades_by_date(
        self, trades: pd.DataFrame, start: str, end: str,
    ) -> pd.DataFrame:
        """Filter trades whose entry_date falls within [start, end]."""
        if len(trades) == 0:
            return trades
        mask = (trades["entry_date"] >= start) & (trades["entry_date"] <= end)
        return trades[mask]

    def _window_stats(
        self,
        trades: pd.DataFrame,
        pnl_slice: pd.DataFrame,
        start_i: int,
        end_i: int,
    ) -> Dict[str, Any]:
        """Compute per-window performance metrics."""
        n_days = end_i - start_i + 1
        n_trades = len(trades)

        # Equity-based return from pnl_slice
        if len(pnl_slice) > 1 and "equity_curve" in pnl_slice.columns:
            eq = pnl_slice["equity_curve"].values
            start_eq = eq[0] if eq[0] > 0 else 1.0
            end_eq = eq[-1]
            total_return = round(float((end_eq / start_eq) - 1), 6)

            # Max drawdown in this slice
            cummax = np.maximum.accumulate(eq)
            dd = np.where(cummax > 0, (eq - cummax) / cummax, 0.0)
            max_dd = round(float(np.min(dd)), 6) if len(dd) > 0 else 0.0
        else:
            total_return = 0.0
            max_dd = 0.0

        # Trade-based stats
        if n_trades > 0:
            rets = trades["return"].values
            win_rate = round(float((rets > 0).mean()), 4)
            expectancy = round(float(rets.mean()), 6)
        else:
            win_rate = 0.0
            expectancy = 0.0

        return {
            "total_return": total_return,
            "max_dd": max_dd,
            "trades_count": n_trades,
            "win_rate": win_rate,
            "expectancy": expectancy,
            "test_days": n_days,
        }

    # ==================================================================
    # B) Parameter Sensitivity Map
    # ==================================================================

    def _parameter_sensitivity(
        self,
        strategy_signals: pd.DataFrame,
        close: pd.Series,
        strategy_cfg: Any,
        backtest_cfg: Any,
    ) -> Dict[str, Any]:
        """Small grid around existing strategy params — re-runs backtest."""
        from strategy.ma150_atr import compute_ma150_atr_strategy

        base_atr_mult = strategy_cfg.atr_mult
        base_risk_pct = strategy_cfg.risk_per_trade

        # Need MA150 and ATR series — reconstruct from close
        ma150 = close.rolling(150).mean()
        atr = self._compute_atr(close, strategy_cfg.atr_length)

        grid_results: List[Dict[str, Any]] = []
        base_params = {
            "atr_length": strategy_cfg.atr_length,
            "slope_lookback": strategy_cfg.slope_lookback,
            "entry_lookback": strategy_cfg.entry_lookback,
            "atr_pct_high": strategy_cfg.atr_pct_high,
            "slope_min": strategy_cfg.slope_min,
        }

        for am_factor in _ATR_MULT_FACTORS:
            for rp_factor in _RISK_PCT_FACTORS:
                test_atr_mult = round(base_atr_mult * am_factor, 4)
                test_risk_pct = round(base_risk_pct * rp_factor, 6)

                # Re-run strategy with modified atr_mult
                signals = compute_ma150_atr_strategy(
                    close, ma150, atr,
                    atr_mult=test_atr_mult,
                    **base_params,
                )

                # Lightweight backtest (unit-share, no sizing)
                perf = self._quick_backtest(signals, close, backtest_cfg)

                # Compute MAR ratio (CAGR / abs(max_dd))
                mar = 0.0
                if perf["max_dd"] != 0:
                    mar = round(perf.get("cagr", 0.0) / abs(perf["max_dd"]), 4)

                grid_results.append({
                    "atr_mult": test_atr_mult,
                    "risk_pct": test_risk_pct,
                    "atr_mult_factor": am_factor,
                    "risk_pct_factor": rp_factor,
                    "total_return": perf["total_return"],
                    "max_dd": perf["max_dd"],
                    "cagr": perf.get("cagr", 0.0),
                    "mar": mar,
                    "trades_count": perf["trades_count"],
                })

        return {
            "base_atr_mult": base_atr_mult,
            "base_risk_pct": base_risk_pct,
            "grid": grid_results,
            "grid_shape": [len(_ATR_MULT_FACTORS), len(_RISK_PCT_FACTORS)],
        }

    def _compute_atr(self, close: pd.Series, period: int) -> pd.Series:
        """Compute ATR from close-only data (using close-to-close range)."""
        # Approximate ATR using absolute daily returns
        daily_range = close.diff().abs()
        return daily_range.rolling(period).mean()

    def _quick_backtest(
        self,
        signals: pd.DataFrame,
        close: pd.Series,
        backtest_cfg: Any,
    ) -> Dict[str, Any]:
        """Lightweight unit-share backtest for sensitivity grid."""
        one_way = (
            backtest_cfg.commission_pct
            + backtest_cfg.spread_bps / 10000
            + backtest_cfg.slippage_bps / 10000
        )
        round_trip = one_way * 2
        close_aligned = close.reindex(signals.index)

        trades: List[Dict[str, float]] = []
        in_trade = False
        entry_price = 0.0

        for i in range(len(signals)):
            entry_sig = bool(signals["entry_signal"].iloc[i])
            exit_sig = bool(signals["exit_signal"].iloc[i])
            price = float(close_aligned.iloc[i])

            if exit_sig and in_trade:
                net_ret = (price / entry_price - 1) - round_trip if entry_price > 0 else 0.0
                trades.append({"return": net_ret})
                in_trade = False

            if entry_sig and not in_trade:
                in_trade = True
                entry_price = price

        n_trades = len(trades)
        if n_trades == 0:
            return {"total_return": 0.0, "max_dd": 0.0, "cagr": 0.0, "trades_count": 0}

        # Compute equity curve from trade returns
        rets = [t["return"] for t in trades]
        equity = [1.0]
        for r in rets:
            equity.append(equity[-1] * (1 + r))
        equity_arr = np.array(equity)
        total_return = round(float(equity_arr[-1] - 1), 6)

        cummax = np.maximum.accumulate(equity_arr)
        dd = np.where(cummax > 0, (equity_arr - cummax) / cummax, 0.0)
        max_dd = round(float(np.min(dd)), 6)

        n_days = len(signals)
        years = n_days / 252.0
        if years > 0 and equity_arr[-1] > 0:
            cagr = round(float(equity_arr[-1] ** (1 / years) - 1), 6)
        else:
            cagr = 0.0

        return {
            "total_return": total_return,
            "max_dd": max_dd,
            "cagr": cagr,
            "trades_count": n_trades,
        }

    # ==================================================================
    # C) Monte Carlo Trade Reshuffle
    # ==================================================================

    def _monte_carlo_reshuffle(
        self,
        trades: pd.DataFrame,
        n_simulations: int = _MONTE_CARLO_N,
    ) -> Dict[str, Any]:
        """Reshuffle realized trade returns to build distribution."""
        if len(trades) == 0:
            return {
                "n_simulations": n_simulations,
                "n_trades": 0,
                "percentiles": {},
                "simulations_summary": [],
            }

        trade_returns = trades["return"].values.copy()
        n_trades = len(trade_returns)

        rng = np.random.RandomState(_MONTE_CARLO_SEED)

        final_returns = np.zeros(n_simulations)
        max_drawdowns = np.zeros(n_simulations)

        for sim in range(n_simulations):
            shuffled = rng.permutation(trade_returns)
            # Build equity curve
            equity = np.ones(n_trades + 1)
            for j in range(n_trades):
                equity[j + 1] = equity[j] * (1 + shuffled[j])

            final_returns[sim] = equity[-1] - 1.0

            # Max drawdown
            cummax = np.maximum.accumulate(equity)
            dd = np.where(cummax > 0, (equity - cummax) / cummax, 0.0)
            max_drawdowns[sim] = np.min(dd)

        # Percentiles
        pcts = [1, 5, 10, 25, 50, 75, 90, 95, 99]
        return_pcts = {
            f"p{p}": round(float(np.percentile(final_returns, p)), 6)
            for p in pcts
        }
        dd_pcts = {
            f"p{p}": round(float(np.percentile(max_drawdowns, p)), 6)
            for p in pcts
        }

        return {
            "n_simulations": n_simulations,
            "n_trades": n_trades,
            "seed": _MONTE_CARLO_SEED,
            "final_return": {
                "mean": round(float(np.mean(final_returns)), 6),
                "std": round(float(np.std(final_returns)), 6),
                "min": round(float(np.min(final_returns)), 6),
                "max": round(float(np.max(final_returns)), 6),
                "percentiles": return_pcts,
            },
            "max_drawdown": {
                "mean": round(float(np.mean(max_drawdowns)), 6),
                "std": round(float(np.std(max_drawdowns)), 6),
                "worst": round(float(np.min(max_drawdowns)), 6),
                "percentiles": dd_pcts,
            },
        }

    # ==================================================================
    # D) Exposure Decomposition
    # ==================================================================

    def _exposure_decomposition(
        self,
        pnl_series: pd.DataFrame,
        strategy_signals: pd.DataFrame,
        close: pd.Series,
    ) -> Dict[str, Any]:
        """Decompose portfolio exposure by time, regime, and benchmark."""
        n = len(pnl_series)
        if n == 0:
            return {
                "time_in_market_pct": 0.0,
                "avg_exposure_pct": 0.0,
                "exposure_high_vol_regime": None,
                "benchmark_correlation": None,
                "benchmark_unavailable": True,
            }

        position = pnl_series["position"].values
        time_in_market = round(float(np.sum(position > 0) / n * 100), 2)

        exposure_col = pnl_series.get("exposure_pct")
        avg_exposure = 0.0
        if exposure_col is not None and len(exposure_col) > 0:
            avg_exposure = round(float(exposure_col.mean()), 4)

        # Exposure during high-vol regime
        exposure_high_vol = self._exposure_by_regime(
            pnl_series, strategy_signals, "high_vol"
        )

        # Benchmark correlation (SPY) — only if available
        benchmark_corr, benchmark_unavailable = self._benchmark_correlation(
            pnl_series
        )

        return {
            "time_in_market_pct": time_in_market,
            "avg_exposure_pct": avg_exposure,
            "exposure_high_vol_regime": exposure_high_vol,
            "benchmark_correlation": benchmark_corr,
            "benchmark_unavailable": benchmark_unavailable,
        }

    def _exposure_by_regime(
        self,
        pnl_series: pd.DataFrame,
        strategy_signals: pd.DataFrame,
        regime_type: str,
    ) -> Optional[float]:
        """Compute average exposure during a specific regime flag."""
        if "range_high_vol" not in strategy_signals.columns:
            return None
        if "exposure_pct" not in pnl_series.columns:
            return None

        # Align indices
        rhv = strategy_signals["range_high_vol"].values
        exposure = pnl_series["exposure_pct"].values
        min_len = min(len(rhv), len(exposure))

        rhv = rhv[:min_len]
        exposure = exposure[:min_len]

        # high_vol mask from strategy signals
        mask = rhv.astype(bool)
        if mask.sum() == 0:
            return 0.0

        return round(float(exposure[mask].mean()), 4)

    def _benchmark_correlation(
        self, pnl_series: pd.DataFrame,
    ) -> Tuple[Optional[float], bool]:
        """Compute equity curve correlation to SPY if available."""
        # Check if SPY data exists in data cache
        cache_candidates = [
            os.path.join("data_cache", "SPY_YahooFinanceAdapter.parquet"),
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data_cache", "SPY_YahooFinanceAdapter.parquet",
            ),
        ]

        spy_path = None
        for candidate in cache_candidates:
            if os.path.exists(candidate):
                spy_path = candidate
                break

        if spy_path is None:
            return None, True

        try:
            spy_df = pd.read_parquet(spy_path)
            spy_close = spy_df["Close"]
            spy_returns = spy_close.pct_change().dropna()

            if "daily_return" not in pnl_series.columns:
                return None, True

            eq_returns = pnl_series["daily_return"].values
            if len(eq_returns) < 10:
                return None, True

            # Align by length (take last N of SPY to match)
            n = min(len(eq_returns), len(spy_returns))
            eq_tail = eq_returns[-n:]
            spy_tail = spy_returns.values[-n:]

            corr = float(np.corrcoef(eq_tail, spy_tail)[0, 1])
            if np.isnan(corr):
                return None, True

            return round(corr, 4), False

        except Exception:
            return None, True

    # ==================================================================
    # E) Regime Contribution Analysis
    # ==================================================================

    def _regime_contribution(
        self, trades: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Split performance by regime buckets from Phase 5."""
        regime_path = os.path.join(
            self.run_dir, "VolatilityRegimeAgent", "regime_series.parquet"
        )
        if not os.path.exists(regime_path) or len(trades) == 0:
            return {"buckets": [], "source": "volatility_regime"}

        regime_df = pd.read_parquet(regime_path)
        # Build date -> regime map
        regime_df["date_str"] = regime_df["date"].apply(
            lambda d: str(d.date()) if hasattr(d, "date") else str(d)
        )
        date_regime_map = dict(
            zip(regime_df["date_str"], regime_df["regime"])
        )

        trades_copy = trades.copy()
        trades_copy["regime"] = trades_copy["entry_date"].map(date_regime_map)
        trades_copy["regime"] = trades_copy["regime"].fillna("UNKNOWN")

        buckets: List[Dict[str, Any]] = []
        for regime, group in sorted(trades_copy.groupby("regime")):
            n = len(group)
            rets = group["return"].values
            total_ret = round(float(rets.sum()), 6)
            mean_ret = round(float(rets.mean()), 6) if n > 0 else 0.0
            buckets.append({
                "regime": regime,
                "count": n,
                "mean_return": mean_ret,
                "total_return": total_ret,
            })

        return {"buckets": buckets, "source": "volatility_regime"}

    # ==================================================================
    # F) Capacity Test
    # ==================================================================

    def _capacity_test(
        self,
        close: pd.Series,
        volume: Optional[pd.Series],
        backtest_cfg: Any,
    ) -> Dict[str, Any]:
        """Estimate ADV and max-position / ADV ratio."""
        if volume is None or len(volume) < 20:
            return {
                "adv_20d_usd": None,
                "max_position_usd": None,
                "position_adv_ratio": None,
                "category": "unknown",
                "volume_unavailable": True,
            }

        # Last 20 trading days
        recent_close = close.iloc[-20:]
        recent_volume = volume.iloc[-20:]
        adv_usd = float((recent_close * recent_volume).mean())

        # Max position from backtest config
        capital_base = backtest_cfg.capital_base
        max_position_pct = backtest_cfg.max_position_pct
        max_position_usd = capital_base * max_position_pct

        ratio = max_position_usd / adv_usd if adv_usd > 0 else 0.0

        # Categorize
        if ratio < 0.001:
            category = "tiny"
        elif ratio < 0.01:
            category = "small"
        elif ratio < 0.05:
            category = "moderate"
        else:
            category = "large"

        return {
            "adv_20d_usd": round(adv_usd, 2),
            "max_position_usd": round(max_position_usd, 2),
            "position_adv_ratio": round(ratio, 6),
            "category": category,
            "volume_unavailable": False,
        }

    # ==================================================================
    # Summary builder
    # ==================================================================

    def _build_summary(
        self,
        walk_forward: Dict,
        sensitivity: Dict,
        monte_carlo: Dict,
        exposure: Dict,
        regime_contrib: Dict,
        capacity: Dict,
        bt_metrics: Dict,
    ) -> Dict[str, Any]:
        """Build top-level summary with key risk stats."""
        # Walk-forward stability
        wf_windows = walk_forward.get("windows", [])
        wf_returns = [w["total_return"] for w in wf_windows]
        wf_stability = {
            "n_windows": len(wf_windows),
            "mean_return": round(float(np.mean(wf_returns)), 6) if wf_returns else 0.0,
            "std_return": round(float(np.std(wf_returns)), 6) if len(wf_returns) > 1 else 0.0,
            "min_return": round(float(np.min(wf_returns)), 6) if wf_returns else 0.0,
            "max_return": round(float(np.max(wf_returns)), 6) if wf_returns else 0.0,
        }

        # Monte Carlo tail risk
        mc_return = monte_carlo.get("final_return", {})
        mc_dd = monte_carlo.get("max_drawdown", {})
        mc_tail = {
            "return_p5": mc_return.get("percentiles", {}).get("p5", 0.0),
            "return_p50": mc_return.get("percentiles", {}).get("p50", 0.0),
            "return_p95": mc_return.get("percentiles", {}).get("p95", 0.0),
            "dd_worst": mc_dd.get("worst", 0.0),
            "dd_p5": mc_dd.get("percentiles", {}).get("p5", 0.0),
        }

        # Sensitivity range
        grid = sensitivity.get("grid", [])
        if grid:
            grid_returns = [g["total_return"] for g in grid]
            sensitivity_range = {
                "min_return": round(float(min(grid_returns)), 6),
                "max_return": round(float(max(grid_returns)), 6),
                "grid_points": len(grid),
            }
        else:
            sensitivity_range = {"min_return": 0.0, "max_return": 0.0, "grid_points": 0}

        return {
            "phase": "Phase 6: Robustness & Statistical Validation",
            "backtest_total_return": bt_metrics.get("total_return", 0.0),
            "backtest_max_drawdown": bt_metrics.get("max_drawdown", 0.0),
            "walk_forward_stability": wf_stability,
            "monte_carlo_tail_risk": mc_tail,
            "sensitivity_range": sensitivity_range,
            "time_in_market_pct": exposure.get("time_in_market_pct", 0.0),
            "benchmark_correlation": exposure.get("benchmark_correlation"),
            "capacity_category": capacity.get("category", "unknown"),
            "capacity_adv_ratio": capacity.get("position_adv_ratio"),
            "artifact_paths": {
                "walk_forward": "RobustnessAgent/walk_forward.json",
                "sensitivity_map": "RobustnessAgent/sensitivity_map.json",
                "monte_carlo": "RobustnessAgent/monte_carlo.json",
                "exposure_decomposition": "RobustnessAgent/exposure_decomposition.json",
                "regime_contribution": "RobustnessAgent/regime_contribution.json",
                "capacity_test": "RobustnessAgent/capacity_test.json",
            },
        }

    # ==================================================================
    # CSV helpers
    # ==================================================================

    def _save_walk_forward_csv(self, wf: Dict) -> None:
        windows = wf.get("windows", [])
        if not windows:
            return
        df = pd.DataFrame(windows)
        df.to_csv(
            os.path.join(self.agent_dir, "walk_forward.csv"), index=False
        )
        self.logger.info("Saved artifact: walk_forward.csv")

    def _save_sensitivity_csv(self, sens: Dict) -> None:
        grid = sens.get("grid", [])
        if not grid:
            return
        df = pd.DataFrame(grid)
        df.to_csv(
            os.path.join(self.agent_dir, "sensitivity_map.csv"), index=False
        )
        self.logger.info("Saved artifact: sensitivity_map.csv")

    def _save_monte_carlo_csv(self, mc: Dict) -> None:
        rows = []
        for section in ("final_return", "max_drawdown"):
            data = mc.get(section, {})
            pcts = data.get("percentiles", {})
            for k, v in sorted(pcts.items()):
                rows.append({"metric": section, "percentile": k, "value": v})
            rows.append({"metric": section, "percentile": "mean", "value": data.get("mean", 0.0)})
            rows.append({"metric": section, "percentile": "std", "value": data.get("std", 0.0)})
        if rows:
            df = pd.DataFrame(rows)
            df.to_csv(
                os.path.join(self.agent_dir, "monte_carlo.csv"), index=False
            )
            self.logger.info("Saved artifact: monte_carlo.csv")
