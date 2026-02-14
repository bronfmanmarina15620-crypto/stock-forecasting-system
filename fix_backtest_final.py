# fix_backtest_final.py - תיקון סופי של BacktestAgent
print("🔧 מתקן את BacktestAgent - שמירה נכונה...")

with open('agents/backtest_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא והוסף debug בפונקציית run
old_run = '''        # Create predictions DataFrame
        predictions_oos = pd.DataFrame(predictions)'''

new_run = '''        # Create predictions DataFrame
        print(f"DEBUG BacktestAgent: Number of prediction dictionaries: {len(predictions)}")
        if len(predictions) > 0:
            print(f"DEBUG BacktestAgent: First prediction: {predictions[0]}")
        
        predictions_oos = pd.DataFrame(predictions)
        print(f"DEBUG BacktestAgent: DataFrame shape after creation: {predictions_oos.shape}")
        print(f"DEBUG BacktestAgent: DataFrame columns: {predictions_oos.columns.tolist()}")'''

content = content.replace(old_run, new_run)

# ודא שהשמירה נעשית עם DataFrame שאינו ריק
old_save = '''        # Save artifacts
        if len(predictions_oos) > 0:
            # Make sure DataFrame is not empty and has the right structure
            print(f"DEBUG BacktestAgent: Saving predictions with columns: {predictions_oos.columns.tolist()}")
            print(f"DEBUG BacktestAgent: Shape: {predictions_oos.shape}")
            self.save_artifact('predictions_oos.parquet', predictions_oos)'''

new_save = '''        # Save artifacts
        print(f"DEBUG BacktestAgent: About to save. DataFrame shape: {predictions_oos.shape}")
        if len(predictions_oos) > 0 and len(predictions_oos.columns) > 0:
            print(f"DEBUG BacktestAgent: Saving predictions with columns: {predictions_oos.columns.tolist()}")
            print(f"DEBUG BacktestAgent: First few rows:")
            print(predictions_oos.head())
            self.save_artifact('predictions_oos.parquet', predictions_oos)
            
            # Verify it was saved
            import os
            saved_path = self.get_artifact_path('predictions_oos.parquet')
            if os.path.exists(saved_path):
                verify_df = pd.read_parquet(saved_path)
                print(f"DEBUG BacktestAgent: Verified saved file. Shape: {verify_df.shape}")
            else:
                print(f"ERROR: File not saved at {saved_path}")'''

content = content.replace(old_save, new_save)

with open('agents/backtest_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ BacktestAgent תוקן עם debug מפורט!")
print("\nהריצי:")
print("python run.py --ticker PLTR")
print("\nעכשיו נראה בדיוק מה קורה בשמירה!")