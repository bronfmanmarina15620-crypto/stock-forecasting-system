# fix_decision_load.py - תיקון קריאת הנתונים
print("🔧 מתקן את DecisionRiskAgent - קריאת parquet...")

with open('agents/decision_risk_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא את תחילת פונקציית run
old_run_start = '''        try:
            # Load dependencies
            backtest_output = self.load_agent_output('BacktestAgent')'''

new_run_start = '''        try:
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
            print(f"DEBUG: Columns: {predictions.columns.tolist()}")'''

content = content.replace(old_run_start, new_run_start)

# עכשיו תקן את השורה שקוראת מה-backtest_output
old_load = '''            # Load predictions
            predictions = pd.read_parquet(backtest_output['predictions_path'])'''

new_load = '''            # predictions already loaded above from parquet file'''

content = content.replace(old_load, new_load)

with open('agents/decision_risk_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ DecisionRiskAgent תוקן לקרוא מ-parquet!")
print("\nהריצי:")
print("python run.py --ticker PLTR")