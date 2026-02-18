"""
DashboardAgent - Generates final dashboard and HTML report.
"""

import pandas as pd
from typing import Dict, Any
from datetime import datetime
from .base_agent import BaseAgent


class DashboardAgent(BaseAgent):
    """Agent responsible for generating the final dashboard."""
    
    def run(self) -> Dict[str, Any]:
        """Generate final dashboard and report."""
        self.logger.info("Starting dashboard generation")
        
        try:
            # Load all agent outputs
            data_output = self.load_agent_output('DataAgent')
            feature_output = self.load_agent_output('FeatureAgent')
            regime_output = self.load_agent_output('RegimeAgent')
            model_output = self.load_agent_output('EventModelAgent')
            backtest_output = self.load_agent_output('BacktestAgent')
            decision_output = self.load_agent_output('DecisionRiskAgent')
            portfolio_output = self.load_agent_output('PortfolioAgent')
            
            # Generate final HTML report
            html_report = self._generate_html_report(
                data_output=data_output,
                feature_output=feature_output,
                regime_output=regime_output,
                model_output=model_output,
                backtest_output=backtest_output,
                decision_output=decision_output,
                portfolio_output=portfolio_output
            )
            
            # Generate JSON report
            json_report = self._generate_json_report(
                data_output=data_output,
                backtest_output=backtest_output,
                decision_output=decision_output,
                portfolio_output=portfolio_output
            )
            
            # Save in DashboardAgent subdirectory
            import os
            dashboard_dir = os.path.join(self.run_dir, 'DashboardAgent')
            os.makedirs(dashboard_dir, exist_ok=True)
            
            html_path = os.path.join(dashboard_dir, 'final_report.html')
            json_path = os.path.join(dashboard_dir, 'final_report.json')
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_report)
            
            import json
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_report, f, indent=2, ensure_ascii=False)
            
            # ALSO save copy at root for backward compatibility
            root_html_path = self.run_dir + '/final_report.html'
            with open(root_html_path, 'w', encoding='utf-8') as f:
                f.write(html_report)
            
            # Prepare output
            output = {
                'status': 'SUCCESS',
                'html_report_path': html_path,
                'json_report_path': json_path
            }
            
            self.save_output(output)
            self.logger.info("Dashboard generation complete")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Dashboard generation failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _generate_html_report(self, **kwargs) -> str:
        """Generate comprehensive HTML report."""
        data_output = kwargs['data_output']
        backtest_output = kwargs['backtest_output']
        decision_output = kwargs['decision_output']
        portfolio_output = kwargs['portfolio_output']
        
        # Extract key metrics
        decision_stats = decision_output['decision_stats']
        decision_action = decision_output['decision_action']
        portfolio_plan = portfolio_output['portfolio_plan']
        risk_summary = portfolio_output['risk_summary']
        
        metrics = backtest_output['metrics']['overall']
        
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
        .rtl {{
            direction: rtl;
            text-align: right;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Stock Forecasting System Report</h1>
        
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
        
        <h2>🎯 Current Decision ({self.config.ticker})</h2>
        <div class="card">
            <div class="action-{decision_action['action'].lower()}">
                {decision_action['action']}
            </div>
            <div style="margin-top: 15px;">
                <div class="metric">
                    <span class="metric-label">Probability:</span>
                    <span class="metric-value">{decision_action['probability']:.1%}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Regime:</span>
                    <span class="metric-value">{decision_action['regime']}</span>
                </div>
            </div>
        </div>
        
        <h2>📈 Backtest Performance</h2>
        <div class="card">
            <div class="metric">
                <span class="metric-label">AUC:</span>
                <span class="metric-value">{metrics['auc']:.3f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Base Rate:</span>
                <span class="metric-value">{metrics['base_rate']:.1%}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Total Samples:</span>
                <span class="metric-value">{metrics['total_samples']}</span>
            </div>
        </div>
        
        <h2>⚖️ Decision Statistics</h2>
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
        
        <h2>💼 Portfolio Plan (PASSIVE MODE)</h2>
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
        
        <h2>🔍 System Status</h2>
        <div class="card">
            <table>
                <tr>
                    <th>Agent</th>
                    <th>Status</th>
                </tr>
                <tr>
                    <td>DataAgent</td>
                    <td class="status-{data_output['status'].lower()}">{data_output['status']}</td>
                </tr>
                <tr>
                    <td>BacktestAgent</td>
                    <td class="status-{backtest_output['status'].lower()}">{backtest_output['status']}</td>
                </tr>
                <tr>
                    <td>DecisionRiskAgent</td>
                    <td class="status-{decision_output['status'].lower()}">{decision_output['status']}</td>
                </tr>
                <tr>
                    <td>PortfolioAgent</td>
                    <td class="status-{portfolio_output['status'].lower()}">{portfolio_output['status']}</td>
                </tr>
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
    
    def _generate_json_report(self, **kwargs) -> Dict[str, Any]:
        """Generate JSON summary report."""
        return {
            'ticker': self.config.ticker,
            'run_timestamp': datetime.now().isoformat(),
            'data': kwargs['data_output'],
            'backtest': kwargs['backtest_output'],
            'decision': kwargs['decision_output'],
            'portfolio': kwargs['portfolio_output']
        }
