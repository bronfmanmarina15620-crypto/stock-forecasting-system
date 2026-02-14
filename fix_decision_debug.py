# fix_decision_debug.py - תיקון עם הדפסת debug
print("🔧 מתקן DecisionRiskAgent עם debug...")

with open('agents/decision_risk_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא והחלף את כל הפונקציה _generate_signals
old_func_start = "    def _generate_signals(self, predictions: pd.DataFrame) -> pd.DataFrame:"

new_function = '''    def _generate_signals(self, predictions: pd.DataFrame) -> pd.DataFrame:
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
        
        return signals'''

# מצא את המיקום של הפונקציה
start_idx = content.find(old_func_start)
if start_idx != -1:
    # מצא את סוף הפונקציה (הפונקציה הבאה או סוף הקובץ)
    next_func_idx = content.find("\n    def _calculate_strategy_pnl", start_idx)
    if next_func_idx != -1:
        # החלף את כל הפונקציה
        content = content[:start_idx] + new_function + content[next_func_idx:]
    else:
        print("❌ לא מצאתי את הפונקציה הבאה")
else:
    print("❌ לא מצאתי את _generate_signals")

# תקן גם את _get_current_decision
old_decision_start = "    def _get_current_decision(self, predictions: pd.DataFrame) -> Dict[str, Any]:"
new_decision_func = '''    def _get_current_decision(self, predictions: pd.DataFrame) -> Dict[str, Any]:
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
        }'''

start_idx = content.find(old_decision_start)
if start_idx != -1:
    next_func_idx = content.find("\nimport pandas as pd", start_idx)
    if next_func_idx == -1:
        # זה הפונקציה האחרונה
        content = content[:start_idx] + new_decision_func
    else:
        content = content[:start_idx] + new_decision_func + content[next_func_idx:]

with open('agents/decision_risk_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ DecisionRiskAgent תוקן עם debug!")
print("\nעכשיו הריצי:")
print("python run.py --ticker PLTR")
print("\nאת תראי הדפסות DEBUG שיראו מה בדיוק יש בעמודות")