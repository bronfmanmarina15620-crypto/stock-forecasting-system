"""
DecisionRiskAgent - Converts probabilities into ENTER/ABSTAIN decisions.

Phase 2 integration point:
    Strategy logic currently lives in:
        - agents/decision_risk_agent.py  (signal generation: ENTER/ABSTAIN)
        - agents/backtest_agent.py       (walk-forward ML backtest)
        - agents/regime_agent.py         (regime labels: MA20/50 crossover + vol)
        - agents/feature_agent.py        (ATR14, MA20/50/200 features)

    Integration point: StrategyAgent (new) runs before DecisionRiskAgent.
    DecisionRiskAgent will consume StrategyAgent's entry_signal / regime_ok /
    range_high_vol to produce ENTER or ABSTAIN (never SHORT).
"""

import pandas as pd
import numpy as np
import pickle
from typing import Dict, Any
from .base_agent import BaseAgent
from determinism import content_hash_sha256


class DecisionRiskAgent(BaseAgent):
    """Agent responsible for decision making and risk assessment."""
    
    def run(self) -> Dict[str, Any]:
        """Generate trading decisions."""
        self.logger.info("Starting decision generation")
        
        try:
            # Load dependencies
            backtest_output = self.load_agent_output('BacktestAgent')
            
            # CRITICAL: Load the actual predictions parquet file, not just the JSON
            import os
            predictions_path = os.path.join(self.run_dir, 'BacktestAgent', 'predictions_oos.parquet')
            if not os.path.exists(predictions_path):
                raise FileNotFoundError(f"predictions_oos.parquet not found at {predictions_path}")
            
            import pandas as pd
            predictions = pd.read_parquet(predictions_path)
            print(f"DEBUG: Loaded predictions from parquet, shape: {predictions.shape}")
            print(f"DEBUG: Columns: {predictions.columns.tolist()}")
            model_output = self.load_agent_output('EventModelAgent')
            regime_output = self.load_agent_output('RegimeAgent')
            
            if any(o['status'] not in ['SUCCESS', 'WARNING'] for o in [backtest_output, model_output, regime_output]):
                return {
                    'status': 'FAILED',
                    'error': 'Dependencies failed'
                }
            
            # predictions already loaded above from parquet file
            
            # Generate signals
            signals = self._generate_signals(predictions)
            
            # Calculate strategy P&L
            strategy_pnl = self._calculate_strategy_pnl(signals)
            
            # Create decision explanation
            decision_explain = self._create_decision_explanation(signals, strategy_pnl)
            
            # Get current decision (last available)
            decision_action = self._get_current_decision(predictions)
            
            # Generate abstain stats
            abstain_stats = self._generate_abstain_stats(signals, decision_explain)

            # Embed deterministic content fingerprint
            decision_action['content_hash_sha256'] = content_hash_sha256(decision_action)

            # Save artifacts
            self.save_artifact('signals.csv', signals)
            self.save_artifact('decision_explain.json', decision_explain)
            self.save_artifact('strategy_pnl.parquet', strategy_pnl)
            self.save_artifact('decision_action.json', decision_action)
            self.save_artifact('abstain_stats.json', abstain_stats)

            # Prepare output
            output = {
                'status': 'SUCCESS',
                'signals_path': self.get_artifact_path('signals.csv'),
                'decision_action': decision_action,
                'decision_stats': decision_explain
            }
            
            self.save_output(output)
            self.logger.info("Decision generation complete")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Decision generation failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _generate_signals(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """
        Generate ENTER/ABSTAIN signals based on rules.
        
        Default: ABSTAIN
        ENTER only if:
        - probability > threshold
        - regime is allowed
        """
        # Debug: print column names
        print(f"DEBUG: predictions columns = {predictions.columns.tolist()}")
        
        signals = predictions.copy()
        signals['action'] = self.config.decision.default_action
        
        # Apply decision rules
        prob_threshold = self.config.decision.probability_threshold
        allowed_regimes = self.config.decision.allowed_regimes
        
        # Find the probability column - try multiple names
        prob_col = None
        for possible_name in ['y_pred_proba', 'y_pred', 'probability', 'prob']:
            if possible_name in signals.columns:
                prob_col = possible_name
                print(f"DEBUG: Using probability column: {prob_col}")
                break
        
        if prob_col is None:
            # Last resort - find any column with 'pred' or 'prob' in the name
            for col in signals.columns:
                if 'pred' in col.lower() or 'prob' in col.lower():
                    prob_col = col
                    print(f"DEBUG: Found probability column by search: {prob_col}")
                    break
        
        if prob_col is None:
            raise ValueError(f"Cannot find probability column in: {signals.columns.tolist()}")
        
        enter_condition = (
            (signals[prob_col] > prob_threshold) &
            (signals['regime'].isin(allowed_regimes))
        )
        
        signals.loc[enter_condition, 'action'] = 'ENTER'
        
        return signals
    def _calculate_strategy_pnl(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Calculate strategy P&L with realistic frictions."""
        pnl = signals.copy()
        
        # Realized return (forward 5-day return from actual labels)
        pnl['forward_return'] = pnl['y_true'] * (self.config.event.threshold_pct / 100)
        
        # Trading costs
        commission = self.config.backtest.commission_pct
        spread = self.config.backtest.spread_bps / 10000
        slippage = self.config.backtest.slippage_bps / 10000
        
        total_friction = commission + spread + slippage
        
        # Strategy return (only on ENTER days)
        pnl['strategy_return'] = 0.0
        enter_mask = pnl['action'] == 'ENTER'
        
        # If we enter, we pay frictions both ways (entry + exit)
        if 'forward_return' in pnl.columns:
            pnl.loc[enter_mask, 'strategy_return'] = (
                pnl.loc[enter_mask, 'forward_return'] - (total_friction * 2)
            )
        else:
            # Calculate from y_true
            y_true_col = 'y_true' if 'y_true' in pnl.columns else pnl.columns[1]
            pnl.loc[enter_mask, 'strategy_return'] = (
                pnl.loc[enter_mask, y_true_col] * (self.config.event.threshold_pct / 100) - (total_friction * 2)
            )
        
        # Cumulative returns
        pnl['cum_return'] = (1 + pnl['strategy_return']).cumprod()
        
        # Drawdown
        pnl['cum_max'] = pnl['cum_return'].cummax()
        pnl['drawdown'] = (pnl['cum_return'] - pnl['cum_max']) / pnl['cum_max']
        
        return pnl
    
    def _create_decision_explanation(
        self,
        signals: pd.DataFrame,
        strategy_pnl: pd.DataFrame
    ) -> Dict[str, Any]:
        """Create explanation of decision statistics."""
        total_days = len(signals)
        enter_days = (signals['action'] == 'ENTER').sum()
        abstain_days = (signals['action'] == 'ABSTAIN').sum()
        
        # Expected value per signal (average return on ENTER days)
        enter_returns = strategy_pnl[strategy_pnl['action'] == 'ENTER']['strategy_return']
        ev_per_signal = float(enter_returns.mean()) if len(enter_returns) > 0 else 0.0
        
        # Max drawdown
        max_dd = float(strategy_pnl['drawdown'].min())
        
        # Signals per month
        signals['date'] = pd.to_datetime(signals['date'])
        signals_per_month = signals.groupby(signals['date'].dt.to_period('M'))['action'].apply(
            lambda x: (x == 'ENTER').sum()
        ).mean()
        
        # Win rate
        win_rate = float((enter_returns > 0).mean()) if len(enter_returns) > 0 else 0.0
        
        return {
            'total_days': int(total_days),
            'enter_days': int(enter_days),
            'abstain_days': int(abstain_days),
            'abstain_percentage': float(abstain_days / total_days * 100),
            'signals_per_month': float(signals_per_month),
            'expected_value_per_signal': ev_per_signal,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'decision_rules': {
                'probability_threshold': self.config.decision.probability_threshold,
                'allowed_regimes': self.config.decision.allowed_regimes
            }
        }
    
    def _get_current_decision(self, predictions: pd.DataFrame) -> Dict[str, Any]:
        """Get the most recent decision for PLTR."""
        if len(predictions) == 0:
            return {
                'action': 'ABSTAIN',
                'reason': 'No predictions available'
            }
        
        # Debug
        print(f"DEBUG: _get_current_decision columns = {predictions.columns.tolist()}")
        
        # Get last row
        last = predictions.iloc[-1]
        
        # Find probability column
        prob_col = None
        for possible_name in ['y_pred_proba', 'y_pred', 'probability', 'prob']:
            if possible_name in predictions.columns:
                prob_col = possible_name
                break
        
        if prob_col is None:
            for col in predictions.columns:
                if 'pred' in col.lower() or 'prob' in col.lower():
                    prob_col = col
                    break
        
        if prob_col is None:
            return {
                'action': 'ABSTAIN',
                'reason': f'Cannot find probability column in {predictions.columns.tolist()}'
            }
        
        # Apply decision logic
        action = self.config.decision.default_action
        probability = float(last[prob_col])
        regime = last['regime']
        
        if (probability > self.config.decision.probability_threshold and
            regime in self.config.decision.allowed_regimes):
            action = 'ENTER'
        
        return {
            'action': action,
            'probability': probability,
            'confidence': 0.8,  # Placeholder
            'expected_value_estimate': 0.0,  # Placeholder
            'drawdown_risk_estimate': 0.0,  # Placeholder
            'regime': regime,
            'date': str(last['date']) if 'date' in predictions.columns else str(last.name)
        }

    def _generate_abstain_stats(
        self,
        signals: pd.DataFrame,
        decision_explain: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate abstain statistics required by validator."""
        total = len(signals)
        enter_count = int((signals['action'] == 'ENTER').sum())
        abstain_count = int((signals['action'] == 'ABSTAIN').sum())

        return {
            'abstain_ratio': float(abstain_count / total) if total > 0 else 1.0,
            'enter_count': enter_count,
            'abstain_count': abstain_count,
            'signals_per_month': decision_explain.get('signals_per_month', 0.0),
            'total_days': total
        }