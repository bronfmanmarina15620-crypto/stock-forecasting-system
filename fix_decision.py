# fix_decision.py - תיקון DecisionRiskAgent
print("🔧 מתקן את DecisionRiskAgent...")

with open('agents/decision_risk_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# תקן את הפונקציה _generate_signals
old_code = '''    def _generate_signals(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """
        Generate ENTER/ABSTAIN signals based on rules.
        
        Default: ABSTAIN
        ENTER only if:
        - probability > threshold
        - regime is allowed
        """
        signals = predictions.copy()
        signals['action'] = self.config.decision.default_action
        
        # Apply decision rules
        prob_threshold = self.config.decision.probability_threshold
        allowed_regimes = self.config.decision.allowed_regimes
        
        enter_condition = (
            (signals['y_pred_proba'] > prob_threshold) &
            (signals['regime'].isin(allowed_regimes))
        )
        
        signals.loc[enter_condition, 'action'] = 'ENTER'
        
        return signals'''

new_code = '''    def _generate_signals(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """
        Generate ENTER/ABSTAIN signals based on rules.
        
        Default: ABSTAIN
        ENTER only if:
        - probability > threshold
        - regime is allowed
        """
        signals = predictions.copy()
        signals['action'] = self.config.decision.default_action
        
        # Apply decision rules
        prob_threshold = self.config.decision.probability_threshold
        allowed_regimes = self.config.decision.allowed_regimes
        
        # Handle different column names
        prob_col = 'y_pred_proba' if 'y_pred_proba' in signals.columns else 'y_pred'
        if prob_col not in signals.columns:
            # Try to find probability column by position
            for col in signals.columns:
                if 'prob' in col.lower() or 'pred' in col.lower():
                    prob_col = col
                    break
        
        enter_condition = (
            (signals[prob_col] > prob_threshold) &
            (signals['regime'].isin(allowed_regimes))
        )
        
        signals.loc[enter_condition, 'action'] = 'ENTER'
        
        return signals'''

content = content.replace(old_code, new_code)

# תקן גם את _calculate_strategy_pnl
old_pnl = '''        # If we enter, we pay frictions both ways (entry + exit)
        pnl.loc[enter_mask, 'strategy_return'] = (
            pnl.loc[enter_mask, 'forward_return'] - (total_friction * 2)
        )'''

new_pnl = '''        # If we enter, we pay frictions both ways (entry + exit)
        if 'forward_return' in pnl.columns:
            pnl.loc[enter_mask, 'strategy_return'] = (
                pnl.loc[enter_mask, 'forward_return'] - (total_friction * 2)
            )
        else:
            # Calculate from y_true
            y_true_col = 'y_true' if 'y_true' in pnl.columns else pnl.columns[1]
            pnl.loc[enter_mask, 'strategy_return'] = (
                pnl.loc[enter_mask, y_true_col] * (self.config.event.threshold_pct / 100) - (total_friction * 2)
            )'''

content = content.replace(old_pnl, new_pnl)

# תקן את _get_current_decision
old_decision = '''        # Get last row
        last = predictions.iloc[-1]
        
        # Apply decision logic
        action = self.config.decision.default_action
        probability = float(last['y_pred_proba'])
        regime = last['regime']'''

new_decision = '''        # Get last row
        last = predictions.iloc[-1]
        
        # Apply decision logic
        action = self.config.decision.default_action
        
        # Handle different column names
        prob_col = 'y_pred_proba' if 'y_pred_proba' in predictions.columns else 'y_pred'
        if prob_col not in predictions.columns:
            for col in predictions.columns:
                if 'prob' in col.lower() or 'pred' in col.lower():
                    prob_col = col
                    break
        
        probability = float(last[prob_col])
        regime = last['regime']'''

content = content.replace(old_decision, new_decision)

with open('agents/decision_risk_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ DecisionRiskAgent תוקן!")
print("\nהריצי:")
print("python run.py --ticker PLTR")