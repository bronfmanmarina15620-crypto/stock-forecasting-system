"""
DashboardAgent - Generates final dashboard and HTML report.
"""

import json
import os

import pandas as pd
from typing import Dict, Any
from datetime import datetime
from .base_agent import BaseAgent
from determinism import content_hash_sha256


class DashboardAgent(BaseAgent):
    """Agent responsible for generating the final dashboard."""

    def run(self) -> Dict[str, Any]:
        """Generate final dashboard and report."""
        self.logger.info("Starting dashboard generation")

        try:
            # Load all agent outputs
            data_output = self.load_agent_output("DataAgent")
            feature_output = self.load_agent_output("FeatureAgent")
            regime_output = self.load_agent_output("RegimeAgent")
            model_output = self.load_agent_output("EventModelAgent")
            backtest_output = self.load_agent_output("BacktestAgent")
            strategy_output = self.load_agent_output("StrategyAgent")
            decision_output = self.load_agent_output("DecisionRiskAgent")
            portfolio_output = self.load_agent_output("PortfolioAgent")

            # Phase 5: Load volatility regime data (safe fallback)
            vol_regime_latest = self._load_volatility_regime_latest()
            regime_breakdown = self._load_regime_breakdown()

            # Phase 6: Load robustness summary (safe fallback)
            robustness_summary = self._load_robustness_summary()

            # Generate final HTML report
            html_report = self._generate_html_report(
                data_output=data_output,
                feature_output=feature_output,
                regime_output=regime_output,
                model_output=model_output,
                backtest_output=backtest_output,
                strategy_output=strategy_output,
                decision_output=decision_output,
                portfolio_output=portfolio_output,
                vol_regime_latest=vol_regime_latest,
                regime_breakdown=regime_breakdown,
                robustness_summary=robustness_summary,
            )

            # Generate JSON report
            json_report = self._generate_json_report(
                data_output=data_output,
                backtest_output=backtest_output,
                strategy_output=strategy_output,
                decision_output=decision_output,
                portfolio_output=portfolio_output,
                vol_regime_latest=vol_regime_latest,
                regime_breakdown=regime_breakdown,
                robustness_summary=robustness_summary,
            )

            # Embed deterministic content fingerprint
            json_report["content_hash_sha256"] = content_hash_sha256(json_report)

            # Save to run directory root
            html_path = self.run_dir + "/final_report.html"
            json_path = self.run_dir + "/final_report.json"

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_report)

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_report, f, indent=2, ensure_ascii=False, sort_keys=True)

            output = {
                "status": "SUCCESS",
                "html_report_path": html_path,
                "json_report_path": json_path,
            }

            self.save_output(output)
            self.logger.info("Dashboard generation complete")
            return output

        except Exception as e:
            self.logger.error(f"Dashboard generation failed: {str(e)}")
            return {"status": "FAILED", "error": str(e)}

    # ------------------------------------------------------------------
    # Phase 5: Volatility regime helpers
    # ------------------------------------------------------------------

    def _load_volatility_regime_latest(self) -> Dict[str, Any]:
        """Load regime_latest.json, returning empty dict on absence."""
        path = os.path.join(
            self.run_dir, "VolatilityRegimeAgent", "regime_latest.json"
        )
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def _load_regime_breakdown(self) -> list:
        """Load regime_breakdown.json, returning empty list on absence."""
        path = os.path.join(
            self.run_dir, "BacktestAgent", "regime_breakdown.json"
        )
        if not os.path.exists(path):
            return []
        with open(path, "r") as f:
            return json.load(f)

    def _load_robustness_summary(self) -> Dict[str, Any]:
        """Load Phase 6 RobustnessAgent/summary.json, returning empty dict on absence."""
        path = os.path.join(
            self.run_dir, "RobustnessAgent", "summary.json"
        )
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def _generate_html_report(self, **kwargs) -> str:
        """Generate comprehensive HTML report."""
        data_output = kwargs["data_output"]
        backtest_output = kwargs["backtest_output"]
        decision_output = kwargs["decision_output"]
        strategy_output = kwargs["strategy_output"]
        portfolio_output = kwargs["portfolio_output"]

        decision_stats = decision_output["decision_stats"]
        decision_action = decision_output["decision_action"]
        portfolio_plan = portfolio_output["portfolio_plan"]
        risk_summary = portfolio_output["risk_summary"]
        ml_overall = backtest_output.get("metrics", {}).get("legacy_ml", {})

        # Phase 2 strategy fields
        ma150_trend_ok = decision_action.get("ma150_trend_ok", False)
        rhv_block = decision_action.get("range_high_vol", False)
        entry_ready = decision_action.get("entry_signal", False)
        stop_today = decision_action.get("stop_price")
        because = decision_action.get("because", [])

        stop_str = f"{stop_today:.4f}" if stop_today is not None else "N/A (flat)"
        because_html = "".join(f"<li>{b}</li>" for b in because) if because else "<li>No reasons available</li>"

        # Phase 3 backtest metrics
        bt_metrics = backtest_output.get("metrics", {})

        # Phase 5 volatility regime
        vol_regime_latest = kwargs.get("vol_regime_latest", {})
        regime_breakdown = kwargs.get("regime_breakdown", [])
        vr_regime = vol_regime_latest.get("regime", "N/A")
        vr_ratio = vol_regime_latest.get("atr_ratio")
        vr_slope = vol_regime_latest.get("atr_slope")
        vr_mult = vol_regime_latest.get("multiplier", 1.0)
        vr_thresholds = vol_regime_latest.get("thresholds", {})

        vr_ratio_str = f"{vr_ratio:.3f}" if vr_ratio is not None else "N/A"
        vr_slope_str = f"{vr_slope:.6f}" if vr_slope is not None else "N/A"

        # Build regime breakdown table rows
        rb_rows = ""
        for rb in regime_breakdown:
            rb_rows += (
                f"<tr>"
                f"<td>{rb['regime']}</td>"
                f"<td>{rb['trade_count']}</td>"
                f"<td>{rb['win_rate']:.1%}</td>"
                f"<td>{rb['avg_return']:.2%}</td>"
                f"<td>{rb['avg_r_multiple']:.2f}</td>"
                f"</tr>"
            )
        if not rb_rows:
            rb_rows = "<tr><td colspan='5'>No trades to break down</td></tr>"

        # Phase 6: Robustness summary
        robustness_summary = kwargs.get("robustness_summary", {})
        robustness_html = self._generate_robustness_html(robustness_summary)

        html = f"""
<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Forecasting System - {self.config.ticker}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
        }}
        .card {{
            background-color: #ecf0f1;
            padding: 20px;
            margin: 15px 0;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }}
        .metric {{
            display: inline-block;
            margin: 10px 20px 10px 0;
        }}
        .metric-label {{
            font-weight: bold;
            color: #7f8c8d;
        }}
        .metric-value {{
            font-size: 1.3em;
            color: #2c3e50;
        }}
        .status-success {{
            color: #27ae60;
            font-weight: bold;
        }}
        .status-warning {{
            color: #f39c12;
            font-weight: bold;
        }}
        .status-failed {{
            color: #e74c3c;
            font-weight: bold;
        }}
        .action-enter {{
            background-color: #2ecc71;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            font-weight: bold;
            display: inline-block;
        }}
        .action-abstain {{
            background-color: #95a5a6;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            font-weight: bold;
            display: inline-block;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #34495e;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Stock Forecasting System Report</h1>

        <div class="card">
            <h3>Run Information</h3>
            <div class="metric">
                <span class="metric-label">Ticker:</span>
                <span class="metric-value">{self.config.ticker}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Date:</span>
                <span class="metric-value">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Data Range:</span>
                <span class="metric-value">{data_output['start_date']} to {data_output['end_date']}</span>
            </div>
        </div>

        <h2>Current Decision ({self.config.ticker})</h2>
        <div class="card">
            <div class="action-{decision_action['action'].lower()}">
                {decision_action['action']}
            </div>
            <div style="margin-top: 15px;">
                <div class="metric">
                    <span class="metric-label">MA150 Trend OK:</span>
                    <span class="metric-value">{ma150_trend_ok}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">RANGE_HIGH_VOL Block:</span>
                    <span class="metric-value">{rhv_block}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Entry Ready:</span>
                    <span class="metric-value">{entry_ready}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">ATR Stop:</span>
                    <span class="metric-value">{stop_str}</span>
                </div>
            </div>
            <div style="margin-top: 10px;">
                <strong>Because:</strong>
                <ul>{because_html}</ul>
            </div>
        </div>

        <h2>Backtest Performance (Phase 3)</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Total Return:</span>
                <span class="metric-value">{bt_metrics.get('total_return', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Max Drawdown:</span>
                <span class="metric-value">{bt_metrics.get('max_drawdown', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Sharpe:</span>
                <span class="metric-value">{bt_metrics.get('sharpe', 0):.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Trades:</span>
                <span class="metric-value">{bt_metrics.get('num_trades', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Win Rate:</span>
                <span class="metric-value">{bt_metrics.get('win_rate', 0):.1%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Exposure:</span>
                <span class="metric-value">{bt_metrics.get('exposure_time_pct', 0):.1f}%</span>
            </div>
        </div>

        <h2>Risk Management (Phase 4)</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Avg Exposure:</span>
                <span class="metric-value">{bt_metrics.get('avg_exposure_pct', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Max Exposure:</span>
                <span class="metric-value">{bt_metrics.get('max_exposure_pct', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Avg R-Multiple:</span>
                <span class="metric-value">{bt_metrics.get('avg_r_multiple', 0):.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Worst R-Multiple:</span>
                <span class="metric-value">{bt_metrics.get('worst_r_multiple', 0):.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Best R-Multiple:</span>
                <span class="metric-value">{bt_metrics.get('best_r_multiple', 0):.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Median R-Multiple:</span>
                <span class="metric-value">{bt_metrics.get('median_r_multiple', 0):.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Trades Skipped (stop bounds):</span>
                <span class="metric-value">{bt_metrics.get('pct_trades_skipped_due_to_stop_bounds', 0):.1%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Trades Capped (max position):</span>
                <span class="metric-value">{bt_metrics.get('pct_trades_capped_by_max_position', 0):.1%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Realized Risk/Trade Avg:</span>
                <span class="metric-value">{bt_metrics.get('realized_risk_per_trade_avg', 0):.4f}</span>
            </div>
        </div>

        <h2>Volatility Regime (Phase 5)</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Current Regime:</span>
                <span class="metric-value">{vr_regime}</span>
            </div>
            <div class="metric">
                <span class="metric-label">ATR Ratio (14/100):</span>
                <span class="metric-value">{vr_ratio_str}</span>
            </div>
            <div class="metric">
                <span class="metric-label">ATR Slope:</span>
                <span class="metric-value">{vr_slope_str}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Size Multiplier:</span>
                <span class="metric-value">{vr_mult}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Thresholds:</span>
                <span class="metric-value">quiet&lt;{vr_thresholds.get('quiet', 0.8)}, expand&gt;{vr_thresholds.get('expansion', 1.2)}, extreme&gt;{vr_thresholds.get('extreme', 1.5)}</span>
            </div>
        </div>

        <h2>Regime Breakdown (Phase 5)</h2>
        <div class="card">
            <table>
                <tr>
                    <th>Regime</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Avg Return</th>
                    <th>Avg R</th>
                </tr>
                {rb_rows}
            </table>
        </div>

        {robustness_html}

        <h2>ML Validation</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">AUC:</span>
                <span class="metric-value">{ml_overall.get('auc', 'N/A')}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Base Rate:</span>
                <span class="metric-value">{ml_overall.get('base_rate', 'N/A')}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Total Samples:</span>
                <span class="metric-value">{ml_overall.get('total_samples', 'N/A')}</span>
            </div>
        </div>

        <h2>Strategy Summary (MA150+ATR)</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Entries:</span>
                <span class="metric-value">{strategy_output.get('entries', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Exits:</span>
                <span class="metric-value">{strategy_output.get('exits', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Days in Position:</span>
                <span class="metric-value">{strategy_output.get('days_in_position', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Regime OK Days:</span>
                <span class="metric-value">{strategy_output.get('regime_ok_days', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">RANGE_HIGH_VOL Days:</span>
                <span class="metric-value">{strategy_output.get('range_high_vol_days', 0)}</span>
            </div>
        </div>

        <h2>Decision Statistics</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Abstain Days:</span>
                <span class="metric-value">{decision_stats['abstain_percentage']:.1f}%</span>
            </div>
            <div class="metric">
                <span class="metric-label">Signals/Month:</span>
                <span class="metric-value">{decision_stats['signals_per_month']:.1f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Expected Value/Signal:</span>
                <span class="metric-value">{decision_stats['expected_value_per_signal']:.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Max Drawdown:</span>
                <span class="metric-value">{decision_stats['max_drawdown']:.1%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Win Rate:</span>
                <span class="metric-value">{decision_stats['win_rate']:.1%}</span>
            </div>
        </div>

        <h2>Portfolio Plan (PASSIVE MODE)</h2>
        <div class="card">
            <p><strong>Note:</strong> Portfolio is in PASSIVE mode (planning only, no execution)</p>
            <div class="metric">
                <span class="metric-label">Cash:</span>
                <span class="metric-value">${portfolio_plan['cash_usd']:,.0f} ({portfolio_plan['cash_percentage']:.1f}%)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Positions:</span>
                <span class="metric-value">{risk_summary['num_positions']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Risk Level:</span>
                <span class="metric-value">{risk_summary['current_risk_level']}</span>
            </div>
        </div>

        <h2>System Status</h2>
        <div class="card">
            <table>
                <tr><th>Agent</th><th>Status</th></tr>
                <tr><td>DataAgent</td><td class="status-{data_output['status'].lower()}">{data_output['status']}</td></tr>
                <tr><td>BacktestAgent</td><td class="status-{backtest_output['status'].lower()}">{backtest_output['status']}</td></tr>
                <tr><td>StrategyAgent</td><td class="status-{strategy_output['status'].lower()}">{strategy_output['status']}</td></tr>
                <tr><td>DecisionRiskAgent</td><td class="status-{decision_output['status'].lower()}">{decision_output['status']}</td></tr>
                <tr><td>PortfolioAgent</td><td class="status-{portfolio_output['status'].lower()}">{portfolio_output['status']}</td></tr>
            </table>
        </div>

        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #7f8c8d; font-size: 0.9em;">
            <p>Generated by Multi-Agent Stock Forecasting System</p>
        </div>
    </div>
</body>
</html>
        """
        return html

    def _generate_robustness_html(self, summary: Dict[str, Any]) -> str:
        """Generate Phase 6 robustness HTML section."""
        if not summary:
            return ""

        wf = summary.get("walk_forward_stability", {})
        mc = summary.get("monte_carlo_tail_risk", {})
        sr = summary.get("sensitivity_range", {})

        # Walk-forward summary table
        wf_html = f"""
        <h2>Robustness Validation (Phase 6)</h2>

        <h3>Walk-Forward Stability</h3>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Windows:</span>
                <span class="metric-value">{wf.get('n_windows', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Mean Return:</span>
                <span class="metric-value">{wf.get('mean_return', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Std Return:</span>
                <span class="metric-value">{wf.get('std_return', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Min/Max Return:</span>
                <span class="metric-value">{wf.get('min_return', 0):.2%} / {wf.get('max_return', 0):.2%}</span>
            </div>
        </div>
        """

        # Monte Carlo percentile block
        mc_html = f"""
        <h3>Monte Carlo Tail Risk (1000 reshuffles)</h3>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Return P5:</span>
                <span class="metric-value">{mc.get('return_p5', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Return P50:</span>
                <span class="metric-value">{mc.get('return_p50', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Return P95:</span>
                <span class="metric-value">{mc.get('return_p95', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Worst DD:</span>
                <span class="metric-value">{mc.get('dd_worst', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">DD P5:</span>
                <span class="metric-value">{mc.get('dd_p5', 0):.2%}</span>
            </div>
        </div>
        """

        # Sensitivity heatmap summary (table)
        sens_html = f"""
        <h3>Parameter Sensitivity</h3>
        <div class="card">
            <div class="metric">
                <span class="metric-label">Grid Points:</span>
                <span class="metric-value">{sr.get('grid_points', 0)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Return Range:</span>
                <span class="metric-value">{sr.get('min_return', 0):.2%} to {sr.get('max_return', 0):.2%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Capacity:</span>
                <span class="metric-value">{summary.get('capacity_category', 'unknown')}</span>
            </div>
        </div>
        """

        return wf_html + mc_html + sens_html

    def _generate_json_report(self, **kwargs) -> Dict[str, Any]:
        """Generate JSON summary report with Phase 2 + Phase 3 fields."""
        decision_output = kwargs["decision_output"]
        strategy_output = kwargs["strategy_output"]
        backtest_output = kwargs["backtest_output"]
        decision_action = decision_output.get("decision_action", {})

        # Phase 2 fields for "today"
        strategy_today = {
            "ma150_trend_ok": decision_action.get("ma150_trend_ok", False),
            "range_high_vol_block": decision_action.get("range_high_vol", False),
            "range_high_vol_reason": (
                next(
                    (r for r in decision_action.get("because", []) if "RANGE_HIGH_VOL" in r),
                    None,
                )
            ),
            "entry_rule_ready": decision_action.get("entry_signal", False),
            "atr_stop_today": decision_action.get("stop_price"),
            "because": decision_action.get("because", []),
        }

        # Phase 3 backtest summary
        bt_metrics = backtest_output.get("metrics", {})
        backtest_section = {
            "status": backtest_output.get("status", "UNKNOWN"),
            "predictions_path": backtest_output.get("predictions_path"),
            "metrics": bt_metrics,
            "summary": {
                "total_return": bt_metrics.get("total_return"),
                "max_drawdown": bt_metrics.get("max_drawdown"),
                "sharpe": bt_metrics.get("sharpe"),
                "num_trades": bt_metrics.get("num_trades"),
                "win_rate": bt_metrics.get("win_rate"),
                "exposure_time_pct": bt_metrics.get("exposure_time_pct"),
                "days_range_high_vol_pct": bt_metrics.get(
                    "days_range_high_vol_pct"),
                "last_trade_summary": backtest_output.get(
                    "last_trade_summary"),
                # Phase 4 risk
                "avg_exposure_pct": bt_metrics.get("avg_exposure_pct"),
                "max_exposure_pct": bt_metrics.get("max_exposure_pct"),
                "avg_r_multiple": bt_metrics.get("avg_r_multiple"),
                "median_r_multiple": bt_metrics.get("median_r_multiple"),
                "worst_r_multiple": bt_metrics.get("worst_r_multiple"),
                "best_r_multiple": bt_metrics.get("best_r_multiple"),
                "pct_trades_skipped_due_to_stop_bounds": bt_metrics.get(
                    "pct_trades_skipped_due_to_stop_bounds"),
                "pct_trades_capped_by_max_position": bt_metrics.get(
                    "pct_trades_capped_by_max_position"),
                "realized_risk_per_trade_avg": bt_metrics.get(
                    "realized_risk_per_trade_avg"),
            },
        }

        return {
            "ticker": self.config.ticker,
            "run_timestamp": datetime.now().isoformat(),
            "data": kwargs["data_output"],
            "backtest": backtest_section,
            "strategy": {
                "status": strategy_output.get("status", "UNKNOWN"),
                "params": strategy_output.get("params", {}),
                "entries": strategy_output.get("entries", 0),
                "exits": strategy_output.get("exits", 0),
                "days_in_position": strategy_output.get("days_in_position", 0),
                "today": strategy_today,
            },
            "decision": decision_output,
            "portfolio": kwargs["portfolio_output"],
            "volatility_regime": kwargs.get("vol_regime_latest", {}),
            "volatility_regime_breakdown": kwargs.get("regime_breakdown", []),
            "robustness": kwargs.get("robustness_summary", {}),
        }
