"""
PortfolioAgent - Portfolio management (PASSIVE MODE - planning only).
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from .base_agent import BaseAgent


class PortfolioAgent(BaseAgent):
    """Agent responsible for portfolio management (passive mode)."""
    
    def run(self) -> Dict[str, Any]:
        """Generate portfolio plan (passive mode - no execution)."""
        self.logger.info("Starting portfolio planning (PASSIVE MODE)")
        
        try:
            # Load dependencies
            decision_output = self.load_agent_output('DecisionRiskAgent')
            
            if decision_output['status'] != 'SUCCESS':
                return {
                    'status': 'FAILED',
                    'error': 'DecisionRiskAgent failed'
                }
            
            # In passive mode, just create a plan based on decision
            decision_action = decision_output['decision_action']
            
            # Generate portfolio plan
            portfolio_plan = self._generate_portfolio_plan(decision_action)
            
            # Generate portfolio report
            portfolio_report = self._generate_portfolio_report(portfolio_plan)
            
            # Generate risk summary
            risk_summary = self._generate_risk_summary(portfolio_plan)
            
            # Save artifacts
            self.save_artifact('portfolio_plan.json', portfolio_plan)
            self.save_artifact('portfolio_report.html', portfolio_report)
            self.save_artifact('risk_summary.json', risk_summary)
            
            # Prepare output
            output = {
                'status': 'SUCCESS',
                'mode': 'PASSIVE',
                'portfolio_plan': portfolio_plan,
                'risk_summary': risk_summary
            }
            
            self.save_output(output)
            self.logger.info("Portfolio planning complete (passive mode)")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Portfolio planning failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _generate_portfolio_plan(self, decision_action: Dict[str, Any]) -> Dict[str, Any]:
        """Generate portfolio allocation plan."""
        action = decision_action['action']
        
        # Calculate position size
        if action == 'ENTER':
            # Use max position size from config
            position_size_pct = self.config.portfolio.max_position_size_pct
            
            # Calculate dollar amount
            capital = self.config.portfolio.initial_capital
            position_value = capital * position_size_pct
            cash = capital * (1 - position_size_pct)
            
            positions = {
                self.config.ticker: {
                    'action': 'BUY',
                    'weight': position_size_pct,
                    'value_usd': position_value
                }
            }
        else:
            # Stay in cash
            position_value = 0.0
            cash = self.config.portfolio.initial_capital
            positions = {}
        
        return {
            'mode': 'PASSIVE',
            'action': action,
            'positions': positions,
            'cash_usd': cash,
            'cash_percentage': (cash / self.config.portfolio.initial_capital) * 100,
            'total_value': self.config.portfolio.initial_capital,
            'note': 'This is a PLAN only. No actual trades are executed.'
        }
    
    def _generate_portfolio_report(self, portfolio_plan: Dict[str, Any]) -> str:
        """Generate HTML portfolio report."""
        report = f"""
        <html>
        <head>
            <title>Portfolio Plan</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                .warning {{ background-color: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; }}
            </style>
        </head>
        <body>
        <h1>Portfolio Plan (PASSIVE MODE)</h1>
        
        <div class="warning">
            <strong>Note:</strong> This is a planning-only mode. No actual trades are executed.
        </div>
        
        <h2>Current Plan</h2>
        <ul>
            <li>Action: {portfolio_plan['action']}</li>
            <li>Cash: ${portfolio_plan['cash_usd']:,.2f} ({portfolio_plan['cash_percentage']:.1f}%)</li>
            <li>Total Value: ${portfolio_plan['total_value']:,.2f}</li>
        </ul>
        
        <h2>Positions</h2>
        """
        
        if portfolio_plan['positions']:
            report += "<ul>"
            for ticker, pos in portfolio_plan['positions'].items():
                report += f"""
                <li>{ticker}: {pos['action']} - Weight: {pos['weight']*100:.1f}% (${pos['value_usd']:,.2f})</li>
                """
            report += "</ul>"
        else:
            report += "<p>No positions (100% cash)</p>"
        
        report += """
        </body>
        </html>
        """
        
        return report
    
    def _generate_risk_summary(self, portfolio_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Generate risk summary."""
        # Calculate concentration risk
        num_positions = len(portfolio_plan['positions'])
        
        if num_positions == 0:
            concentration = 0.0
            max_position_weight = 0.0
        else:
            weights = [p['weight'] for p in portfolio_plan['positions'].values()]
            concentration = sum(w**2 for w in weights)  # HHI
            max_position_weight = max(weights)
        
        return {
            'mode': 'PASSIVE',
            'num_positions': num_positions,
            'cash_percentage': portfolio_plan['cash_percentage'],
            'concentration_hhi': concentration,
            'max_position_weight': max_position_weight,
            'max_drawdown_limit': self.config.portfolio.max_portfolio_drawdown_pct,
            'current_risk_level': 'LOW' if num_positions == 0 else 'MEDIUM'
        }
