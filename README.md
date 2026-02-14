# Multi-Agent Stock Forecasting System

A production-grade, explainable stock forecasting and portfolio management system that predicts market **EVENTS** (not prices) and converts them into **ENTER/ABSTAIN** decisions with strict safety gates.

## 🎯 Key Features

- **Event-Based Forecasting**: Predicts probabilities of defined market events (e.g., "5-day return ≥ +2%")
- **10 Specialized Agents**: Strict separation of concerns, coordinated by OrchestratorAgent
- **Data Leakage Prevention**: Built-in unit tests, strictly "as-of" features, forward-only labels
- **Walk-Forward Backtesting**: Realistic evaluation with trading frictions (commissions, spread, slippage)
- **Conservative Decision Making**: Default = ABSTAIN, enter only with high probability + regime confirmation
- **Portfolio Planning**: Passive mode for capital allocation (planning only, no execution)
- **Memory & Learning**: Tracks historical runs, suggests improvements (manual review required)
- **Reproducibility**: Deterministic seeds, immutable run configs, complete artifact preservation

## 🚀 Quick Start

### Installation

```bash
# Clone or download the project
cd stock-forecasting-system

# Install dependencies
pip install -r requirements.txt
```

### Run Analysis (Single Ticker - PLTR)

```bash
# Run with default configuration
python run.py --ticker PLTR

# Run with custom configuration
python run.py --ticker PLTR --config my_config.json
```

### Validate Run

```bash
# Validate a completed run
python validate_run.py --run runs/PLTR/20240214_120000_abc123
```

## 📁 Project Structure

```
stock-forecasting-system/
│
├── run.py                      # CLI entrypoint
├── validate_run.py             # Run validator
├── config.py                   # System configuration
├── utils.py                    # Utility functions
├── requirements.txt            # Dependencies
│
├── agents/                     # All 10 agents
│   ├── __init__.py
│   ├── base_agent.py           # Base agent class
│   ├── orchestrator_agent.py   # Agent 1: Coordinator
│   ├── data_agent.py           # Agent 2: Data fetching
│   ├── feature_agent.py        # Agent 3: Feature engineering
│   ├── regime_agent.py         # Agent 4: Regime detection
│   ├── event_model_agent.py    # Agent 5: Event model training
│   ├── backtest_agent.py       # Agent 6: Walk-forward backtest
│   ├── decision_risk_agent.py  # Agent 7: Decision making
│   ├── portfolio_agent.py      # Agent 8: Portfolio planning
│   ├── dashboard_agent.py      # Agent 9: Dashboard generation
│   └── memory_learning_agent.py # Agent 10: Memory & learning
│
├── datasources/                # Data source adapters
│   ├── __init__.py
│   ├── base.py                 # Base adapter interface
│   ├── yahoo_finance.py        # Yahoo Finance adapter
│   └── stooq.py                # Stooq adapter (stub)
│
├── runs/                       # Run outputs (created automatically)
│   └── PLTR/
│       └── 20240214_120000_abc123/
│           ├── config.json             # Configuration snapshot
│           ├── status.txt              # Run status
│           ├── final_report.html       # Final HTML report
│           ├── final_report.json       # Final JSON report
│           │
│           ├── DataAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── bars_raw.parquet
│           │   ├── bars_adj.parquet
│           │   └── quality_report.json
│           │
│           ├── FeatureAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── features_v1.parquet
│           │   └── feature_manifest.json
│           │
│           ├── RegimeAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── regime_series.parquet
│           │   └── regime_definition.json
│           │
│           ├── EventModelAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── event_model.pkl
│           │   ├── calibration.json
│           │   └── model_card.md
│           │
│           ├── BacktestAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── predictions_oos.parquet
│           │   ├── metrics.json
│           │   ├── backtest_report.html
│           │   └── sanity_tests.json
│           │
│           ├── DecisionRiskAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── signals.csv
│           │   ├── decision_explain.json
│           │   ├── strategy_pnl.parquet
│           │   └── decision_action.json
│           │
│           ├── PortfolioAgent/
│           │   ├── output.json
│           │   ├── agent.log
│           │   ├── portfolio_plan.json
│           │   ├── portfolio_report.html
│           │   └── risk_summary.json
│           │
│           ├── DashboardAgent/
│           │   ├── output.json
│           │   └── agent.log
│           │
│           └── MemoryLearningAgent/
│               ├── output.json
│               ├── agent.log
│               ├── lessons_learned.md
│               └── suggestions.json
│
├── memory/                     # Memory database
│   └── memory_db.sqlite
│
└── data_cache/                 # Cached market data
    └── PLTR_YahooFinanceAdapter.parquet
```

## 🤖 The 10 Agents

### 1. OrchestratorAgent
- **Role**: Coordinates all agents
- **Responsibilities**: Creates run structure, executes agents in order, validates outputs
- **Critical Rule**: No agent may directly call another

### 2. DataAgent
- **Role**: Fetches and validates market data
- **Outputs**: OHLCV bars (raw & adjusted), data quality report
- **Failure Mode**: If data quality fails → entire run fails

### 3. FeatureAgent
- **Role**: Engineers features strictly "as-of" time
- **Outputs**: Feature set with manifest
- **Critical Rule**: All features must use only past data (shifted by 1 day minimum)

### 4. RegimeAgent
- **Role**: Labels market regimes (trend/range, high/low volatility)
- **Outputs**: Daily regime labels with transparent rules
- **Regimes**: TREND_LOW_VOL, TREND_HIGH_VOL, RANGE_LOW_VOL, RANGE_HIGH_VOL

### 5. EventModelAgent
- **Role**: Trains probabilistic event model
- **Outputs**: Calibrated model, model card
- **Event**: "5-day forward return ≥ +2%" (configurable)

### 6. BacktestAgent
- **Role**: Walk-forward validation with realistic frictions
- **Outputs**: Out-of-sample predictions, metrics by year/regime, sanity tests
- **Includes**: Data leakage tests, trading costs (commissions + spread + slippage)

### 7. DecisionRiskAgent
- **Role**: Converts probabilities into ENTER/ABSTAIN decisions
- **Outputs**: Trading signals, strategy P&L, current decision
- **Default**: ABSTAIN (conservative approach)
- **Enter Conditions**: Probability > threshold AND regime allowed

### 8. PortfolioAgent (PASSIVE MODE)
- **Role**: Portfolio planning (no execution)
- **Outputs**: Position plan, risk summary
- **Note**: Currently in planning-only mode for PLTR

### 9. DashboardAgent
- **Role**: Generates final HTML + JSON reports
- **Outputs**: Comprehensive dashboard with all metrics
- **Features**: Today card, backtest history, drawdown, calibration, regime breakdown

### 10. MemoryLearningAgent
- **Role**: Learns from historical runs, suggests improvements
- **Outputs**: Lessons learned, suggestions (manual review required)
- **Critical Rule**: NO automatic changes, suggestions only

## ⚙️ Configuration

Edit `config.py` or provide a custom JSON configuration:

```python
# Key configuration parameters
ticker = "PLTR"                          # Currently active ticker
random_seed = 42                         # Reproducibility
lookback_days = 730                      # 2 years historical data
event_threshold_pct = 2.0                # Event: +2% in 5 days
probability_threshold = 0.60             # Enter if P(event) > 60%
allowed_regimes = ["TREND_LOW_VOL", "TREND_HIGH_VOL"]
max_position_size_pct = 0.20             # 20% max position
commission_pct = 0.001                   # 0.1% per trade
spread_bps = 2.0                         # 2 bps
slippage_bps = 3.0                       # 3 bps
```

## 🛡️ Safety Features

### Data Leakage Prevention
- ✅ Features shifted by minimum 1 day
- ✅ Labels strictly forward-looking
- ✅ Shuffled label test (performance should collapse)
- ✅ Future shift test (correlation should disappear)

### Fail-Safe Mechanisms
- ✅ Data quality validation (fails entire run if critical issues)
- ✅ Agent output validation
- ✅ Sanity tests in backtesting
- ✅ Default decision = ABSTAIN

### Realistic Backtesting
- ✅ Walk-forward validation (no peeking)
- ✅ Trading frictions included
- ✅ Regime-aware metrics
- ✅ Year-over-year stability checks

### Memory Safety
- ✅ Suggestions require manual review
- ✅ No automatic config changes
- ✅ Walk-forward validation required before applying changes

## 📊 Key Performance Indicators

The system prominently reports:

1. **Expected Value per Signal**: Average return per ENTER decision
2. **Max Drawdown**: Worst cumulative loss in signal strategy
3. **Abstain Percentage**: % of days system stays in cash
4. **Signals per Month**: Trading frequency
5. **Win Rate**: % of profitable signals
6. **AUC**: Model discrimination power
7. **Regime Breakdown**: Performance by market regime
8. **Calibration**: How well probabilities match actual frequencies

## 🔧 Extending the System

### Add a New Data Source
1. Create adapter in `datasources/`
2. Inherit from `DataSourceAdapter`
3. Implement `fetch_ohlcv()` and `is_available()`
4. Add to `config.py` backup sources

### Modify Event Definition
Edit `config.py`:
```python
event_name = "UP_EVENT"
forward_window = 5           # Days to look forward
threshold_pct = 2.0          # % threshold
```

### Adjust Decision Rules
Edit `config.py`:
```python
probability_threshold = 0.60              # Higher = more conservative
allowed_regimes = ["TREND_LOW_VOL"]      # Restrict to specific regimes
max_signals_per_month = 10               # Limit trading frequency
```

## 🚧 Current Limitations

- **Single Ticker Only**: Multi-ticker mode implemented but not activated
- **PortfolioAgent Passive**: Planning only, no actual trade execution
- **Backup Data Sources**: Stooq adapter is a stub (needs implementation)
- **Geo/Political Data**: Context only in MVP, not used in models

## 🔮 Future Enhancements

1. **Multi-Ticker Mode**: Enable concurrent analysis of multiple stocks
2. **Active Portfolio Management**: Execute actual trades based on decisions
3. **Advanced Models**: Random Forest, XGBoost, Neural Networks
4. **Real-Time Updates**: Intraday data and decision updates
5. **Geo-Political Features**: Integrate vetted external signals
6. **Options Strategies**: Expand beyond stock positions

## 📝 License

This is a reference implementation for educational purposes.

## 🤝 Contributing

This is a production-grade template. Key principles:

1. **No Agent Cross-Talk**: Only Orchestrator coordinates agents
2. **Data Leakage Tests**: Add tests for any new features
3. **Conservative Defaults**: ABSTAIN unless high confidence
4. **Manual Review**: No automatic changes without validation
5. **Complete Artifacts**: Every run must be fully reproducible

## ⚠️ Disclaimer

This system is for educational and research purposes. Past performance does not guarantee future results. Always do your own research and consult with financial professionals before making investment decisions.

---

**Version**: 1.0.0  
**Last Updated**: 2024-02-14  
**Status**: Production-Ready MVP (Single-Ticker Mode)
