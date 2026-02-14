# fix_backtest_full.py
print("🔧 מחליף את BacktestAgent בגרסה מתוקנת...")

# רק תקן את הפונקציה הבעייתית
with open('agents/backtest_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא והחלף את הפונקציה _calculate_metrics
old_function = '''    def _calculate_metrics(self, predictions_oos: pd.DataFrame, regimes: pd.Series) -> Dict[str, Any]:
        """Calculate comprehensive metrics."""
        y_true = predictions_oos['y_true'].values
        y_pred = predictions_oos['y_pred_proba'].values'''

new_function = '''    def _calculate_metrics(self, predictions_oos: pd.DataFrame, regimes: pd.Series) -> Dict[str, Any]:
        """Calculate comprehensive metrics."""
        # Handle column names flexibly
        if 'y_true' in predictions_oos.columns:
            y_true = predictions_oos['y_true'].values
        else:
            y_true = predictions_oos.iloc[:, 1].values
            
        if 'y_pred_proba' in predictions_oos.columns:
            y_pred = predictions_oos['y_pred_proba'].values
        else:
            y_pred = predictions_oos.iloc[:, 2].values'''

content = content.replace(old_function, new_function)

with open('agents/backtest_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ BacktestAgent תוקן!")
print("\nהריצי:")
print("python run.py --ticker PLTR")