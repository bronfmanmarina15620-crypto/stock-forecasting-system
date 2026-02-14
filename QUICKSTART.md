# Quick Start Guide

## 5-Minute Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- pandas, numpy (data processing)
- scikit-learn (ML models)
- yfinance (market data)
- matplotlib, plotly (visualization)
- And others...

### 2. Run Your First Analysis

```bash
python run.py --ticker PLTR
```

This will:
1. ✅ Create a unique run ID
2. ✅ Fetch PLTR historical data
3. ✅ Generate features
4. ✅ Detect market regimes
5. ✅ Train event model
6. ✅ Run walk-forward backtest
7. ✅ Generate trading decisions
8. ✅ Create portfolio plan
9. ✅ Generate final HTML report
10. ✅ Learn from the run

### 3. View Results

The system creates a folder like:
```
runs/PLTR/20240214_120000_abc123/
```

Open the final report:
```
runs/PLTR/20240214_120000_abc123/final_report.html
```

### 4. Validate the Run

```bash
python validate_run.py --run runs/PLTR/20240214_120000_abc123
```

This checks:
- ✅ All agent directories exist
- ✅ All output.json files present
- ✅ Final reports generated
- ✅ Status file exists

## Understanding the Output

### Key Files

1. **final_report.html** - Main dashboard with:
   - Current decision (ENTER or ABSTAIN)
   - Backtest performance metrics
   - Strategy statistics
   - Portfolio plan
   - System status

2. **final_report.json** - Machine-readable version

3. **status.txt** - Run status (SUCCESS/WARNING/FAILED)

4. **config.json** - Configuration snapshot for reproducibility

### Agent Outputs

Each agent creates its own folder with:
- `output.json` - Agent results
- `agent.log` - Detailed logging
- Artifacts (data files, models, reports)

## Common Tasks

### Change the Event Definition

Edit `config.py` or create custom config:

```json
{
  "event": {
    "forward_window": 10,      // Look 10 days ahead
    "threshold_pct": 3.0       // Predict +3% moves
  }
}
```

Then run:
```bash
python run.py --ticker PLTR --config my_config.json
```

### Make Decisions More Conservative

Edit probability threshold:

```json
{
  "decision": {
    "probability_threshold": 0.70,  // Raise from 0.60 to 0.70
    "allowed_regimes": ["TREND_LOW_VOL"]  // Only trade in calm trends
  }
}
```

### Include Trading Costs

Already included by default! Edit in config:

```json
{
  "backtest": {
    "commission_pct": 0.001,   // 0.1% commission
    "spread_bps": 2.0,         // 2 basis points spread
    "slippage_bps": 3.0        // 3 basis points slippage
  }
}
```

## What the System Does

### Event-Based Approach
Instead of predicting prices, the system predicts:
> "What's the probability that PLTR will gain ≥2% in the next 5 days?"

This is more reliable and actionable than price predictions.

### Conservative by Default
- Default decision: **ABSTAIN** (stay in cash)
- Only enters when:
  - Probability > threshold (60% by default)
  - Market regime is favorable
  - Model calibration is confident

### Realistic Backtesting
- Walk-forward validation (no peeking at future)
- Includes commissions, spreads, slippage
- Tests for data leakage
- Evaluates stability over time

### Safe Learning
- System learns from every run
- Suggests improvements
- **But never auto-applies them**
- All changes require manual review + validation

## Troubleshooting

### "Failed to fetch data from Yahoo Finance"

**Solution**: Check internet connection. System will try backup sources automatically.

### "Data quality validation failed"

**Solution**: 
- Ticker might be delisted or have insufficient history
- Try a different ticker
- Check `DataAgent/quality_report.json` for details

### "Sanity tests failed"

**Solution**:
- This means potential data leakage detected
- Review `BacktestAgent/sanity_tests.json`
- Check that features don't use future information

### Run takes a long time

**Normal**: First run fetches data and trains model. Typical runtime:
- Small ticker (PLTR): 2-5 minutes
- Large history: 5-10 minutes

Subsequent runs use cached data and are faster.

## Next Steps

1. **Read the full README**: `README.md`
2. **Explore agent outputs**: Check each agent's folder
3. **Review the code**: All agents in `agents/` directory
4. **Customize configuration**: Edit `config.py` or create JSON
5. **Run validation**: Always validate your runs

## Safety Reminders

⚠️ **This is for educational purposes**
⚠️ **Past performance ≠ future results**
⚠️ **Always do your own research**
⚠️ **Consult professionals before investing**

---

**Happy Forecasting!** 🚀
