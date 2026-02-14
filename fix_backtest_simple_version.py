# fix_backtest_simple_version.py
print("🔧 מפשט את BacktestAgent...")

with open('agents/backtest_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא והחלף את _calculate_metrics
old_start = "    def _calculate_metrics(self, predictions_oos: pd.DataFrame, regimes: pd.Series) -> Dict[str, Any]:"
new_function = '''    def _calculate_metrics(self, predictions_oos: pd.DataFrame, regimes: pd.Series) -> Dict[str, Any]:
        """Calculate comprehensive metrics."""
        from sklearn.metrics import roc_auc_score, brier_score_loss
        
        # Simple and robust column access
        if len(predictions_oos) == 0:
            return {
                'overall': {'auc': 0.5, 'brier_score': 0.25, 'base_rate': 0.0, 'total_samples': 0},
                'by_year': [],
                'by_regime': []
            }
        
        y_true = predictions_oos['y_true'].values
        y_pred = predictions_oos['y_pred_proba'].values
        
        # Overall metrics
        auc = float(roc_auc_score(y_true, y_pred))
        brier = float(brier_score_loss(y_true, y_pred))
        base_rate = float(y_true.mean())
        
        # By year - simplified
        predictions_oos['year'] = pd.to_datetime(predictions_oos['date']).dt.year
        yearly_metrics = []
        
        for year in predictions_oos['year'].unique():
            year_data = predictions_oos[predictions_oos['year'] == year]
            if len(year_data) > 10:
                try:
                    yearly_metrics.append({
                        'year': int(year),
                        'auc': float(roc_auc_score(year_data['y_true'], year_data['y_pred_proba'])),
                        'samples': len(year_data),
                        'base_rate': float(year_data['y_true'].mean())
                    })
                except:
                    pass
        
        # By regime - simplified
        regime_metrics = []
        for regime in predictions_oos['regime'].unique():
            regime_data = predictions_oos[predictions_oos['regime'] == regime]
            if len(regime_data) > 10:
                try:
                    regime_metrics.append({
                        'regime': regime,
                        'auc': float(roc_auc_score(regime_data['y_true'], regime_data['y_pred_proba'])),
                        'samples': len(regime_data),
                        'base_rate': float(regime_data['y_true'].mean())
                    })
                except:
                    pass
        
        return {
            'overall': {
                'auc': auc,
                'brier_score': brier,
                'base_rate': base_rate,
                'total_samples': len(predictions_oos)
            },
            'by_year': yearly_metrics,
            'by_regime': regime_metrics
        }'''

# מצא את תחילת הפונקציה
start_idx = content.find(old_start)
if start_idx != -1:
    # מצא את סוף הפונקציה (הפונקציה הבאה)
    next_func_idx = content.find("\n    def ", start_idx + len(old_start))
    if next_func_idx != -1:
        # החלף את כל הפונקציה
        content = content[:start_idx] + new_function + content[next_func_idx:]
    
with open('agents/backtest_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ BacktestAgent פושט!")
print("הריצי: python run.py --ticker PLTR")