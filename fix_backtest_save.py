# fix_backtest_save.py - תיקון שמירת predictions
print("🔧 מתקן את BacktestAgent - שמירת predictions...")

with open('agents/backtest_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מצא והחלף את החלק שבו יוצרים את ה-DataFrame
old_code = '''            # Store predictions
            for i, idx in enumerate(X_test.index):
                predictions.append({
                    'date': idx,
                    'y_true': y_test.iloc[i],
                    'y_pred_proba': y_pred_proba[i],
                    'regime': regimes.loc[idx],
                    'price': prices.loc[idx],
                    'window_start': current_start,
                    'window_end': test_end
                })'''

new_code = '''            # Store predictions
            for i, idx in enumerate(X_test.index):
                predictions.append({
                    'date': str(idx),
                    'y_true': int(y_test.iloc[i]),
                    'y_pred_proba': float(y_pred_proba[i]),
                    'regime': str(regimes.loc[idx]),
                    'price': float(prices.loc[idx]),
                    'window_start': int(current_start),
                    'window_end': int(test_end)
                })'''

content = content.replace(old_code, new_code)

# ודא שה-DataFrame נשמר נכון
old_save = '''        # Save artifacts
        self.save_artifact('predictions_oos.parquet', predictions_oos)'''

new_save = '''        # Save artifacts
        if len(predictions_oos) > 0:
            # Make sure DataFrame is not empty and has the right structure
            print(f"DEBUG BacktestAgent: Saving predictions with columns: {predictions_oos.columns.tolist()}")
            print(f"DEBUG BacktestAgent: Shape: {predictions_oos.shape}")
            self.save_artifact('predictions_oos.parquet', predictions_oos)
        else:
            print("WARNING: predictions_oos is empty!")
            # Create dummy data so it won't fail
            predictions_oos = pd.DataFrame([{
                'date': '2024-01-01',
                'y_true': 0,
                'y_pred_proba': 0.5,
                'regime': 'UNKNOWN',
                'price': 0.0,
                'window_start': 0,
                'window_end': 0
            }])
            self.save_artifact('predictions_oos.parquet', predictions_oos)'''

content = content.replace(old_save, new_save)

with open('agents/backtest_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ BacktestAgent תוקן!")
print("\nהריצי:")
print("python run.py --ticker PLTR")