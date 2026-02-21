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

### Shadow Mode (Paper-Run, No Trading)

```bash
# Run in monitoring-only mode — no orders, no broker calls
python run.py --ticker PLTR --mode shadow

# Validate (same command, works for both modes)
python validate_run.py --run runs/PLTR/<RUN_ID>
```

Shadow artifacts: `runs/PLTR/<RUN_ID>/ShadowMonitorAgent/shadow_metrics.json`
and `shadow_summary.json`. See [Phase 7](#phase-7-shadow-mode-live-paper-run-monitoring-only) for details.

### Release Tags

- `v0.4.0-phase4-risk` — Phase 4 risk sizing integration (risk_explain.json + Phase 4 metrics + dashboard + validate_run)
- `v0.4.1-phase4-hardening` — post-release hardening (README docs + schema guard tests + changelog)
- `v0.4.2-phase5-volatility-regime` — Phase 5 volatility regime filter
  - Adds VolatilityRegimeAgent (ATR ratio + slope) with regimes QUIET/NORMAL/EXPANDING/EXTREME
  - EXTREME blocks ENTER and applies regime multiplier to position sizing; adds regime breakdown in backtest + dashboard
- `v0.5.0-phase6-robustness` — Phase 6 robustness & statistical validation
  - Adds RobustnessAgent with walk-forward validation, parameter sensitivity, Monte Carlo reshuffle, exposure decomposition, regime contribution, capacity test
  - Integrated into dashboard (HTML + JSON) and validate_run.py
- `v0.6.0-phase7-shadow` — Phase 7 shadow mode (monitoring-only paper-run)
  - Adds ShadowMonitorAgent with drift metrics, rolling ENTER frequency, degraded mode
  - New `--mode shadow` CLI flag; nightly GitHub Action + Telegram notifications

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
├── agents/                     # All 12 agents
│   ├── __init__.py
│   ├── base_agent.py           # Base agent class
│   ├── orchestrator_agent.py   # Agent 1: Coordinator
│   ├── data_agent.py           # Agent 2: Data fetching
│   ├── feature_agent.py        # Agent 3: Feature engineering
│   ├── regime_agent.py         # Agent 4: Regime detection
│   ├── volatility_regime_agent.py # Agent 4b: Volatility regime filter (Phase 5)
│   ├── event_model_agent.py    # Agent 5: Event model training
│   ├── backtest_agent.py       # Agent 6: Walk-forward backtest
│   ├── decision_risk_agent.py  # Agent 7: Decision making
│   ├── robustness_agent.py     # Agent 7b: Robustness validation (Phase 6)
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
│           │   ├── trades.parquet
│           │   ├── pnl_series.parquet
│           │   ├── metrics.json
│           │   ├── risk_explain.json
│           │   ├── backtest_report.html
│           │   └── legacy_ml/            # (only when backtest_mode: legacy_ml)
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
- **Mode**: `signals_only` (default) uses Phase 2 strategy signals; `legacy_ml` uses ML walk-forward
- **Outputs**: trades.parquet, pnl_series.parquet, metrics.json, risk_explain.json
- **Includes**: Phase 4 position sizing, trading costs (commissions + spread + slippage)

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

## Phase 4: Risk-Based Position Sizing

BacktestAgent (in `signals_only` mode) sizes every trade using an R-multiple model:

```
shares = floor(risk_per_trade * equity / stop_distance)
```

Guardrails cap exposure by `max_position_pct` and `max_leverage`, and skip trades whose stop percentage falls outside `[min_stop_pct, max_stop_pct]`.

### Configuration

All risk parameters live in `config/strategy.yaml`:

| Key | Default | Description |
|-----|---------|-------------|
| `risk_per_trade` | 0.005 | Fraction of equity risked per trade |
| `capital_base` | 100000 | Starting equity ($) |
| `max_leverage` | 1.0 | Maximum portfolio leverage |
| `max_position_pct` | 0.25 | Maximum single-position size (fraction of equity) |
| `min_stop_pct` | 0.01 | Minimum stop distance (% from entry) |
| `max_stop_pct` | 0.20 | Maximum stop distance (% from entry) |

### Artifacts

| Path | Description |
|------|-------------|
| `BacktestAgent/risk_explain.json` | Audit trail: sizing decision for every trade |
| `BacktestAgent/trades.parquet` | 7 added columns: `shares`, `notional`, `exposure_pct`, `stop_distance`, `stop_pct`, `risk_budget`, `r_multiple` |
| `BacktestAgent/metrics.json` | 9 added keys: `avg_exposure_pct`, `max_exposure_pct`, `avg_r_multiple`, `median_r_multiple`, `worst_r_multiple`, `best_r_multiple`, `pct_trades_skipped_due_to_stop_bounds`, `pct_trades_capped_by_max_position`, `realized_risk_per_trade_avg` |

### How to run and validate

```bash
python run.py --ticker PLTR
python validate_run.py --run runs/PLTR/<RUN_ID>
```

`validate_run.py` checks all 9 Phase 4 metric keys plus `risk_explain.json` existence.

When `backtest_mode: legacy_ml`, stub `risk_explain.json` and zeroed Phase 4 metrics are emitted so validation still passes.

## Phase 5: Volatility Regime Filter

VolatilityRegimeAgent classifies each day into QUIET / NORMAL / EXPANDING / EXTREME based on the ratio of ATR(14) to ATR(100) and the slope of ATR(14):

- **EXTREME** (ratio > 1.5): blocks all new entries (forced ABSTAIN), size multiplier 0.0
- **EXPANDING** (ratio > 1.2, slope > 0): size multiplier 0.5
- **QUIET** (ratio < 0.8): size multiplier 0.5
- **NORMAL**: size multiplier 1.0

DecisionRiskAgent applies the multiplier and blocks ENTER during EXTREME regimes. Dashboard and final report include the latest regime, thresholds, and a per-regime trade breakdown.

## Phase 6: Robustness & Statistical Validation

RobustnessAgent runs after BacktestAgent and produces evaluation/validation outputs without changing any trading logic.

### Analyses

| Analysis | Description |
|----------|-------------|
| Walk-Forward Validation | Rolling train/test windows (6 default) — same strategy params, segmented evaluation |
| Parameter Sensitivity Map | Grid around `atr_mult` (±20%) and `risk_pct` (±50%) — 25 grid points |
| Monte Carlo Trade Reshuffle | 1000 reshuffles of realized trade returns with fixed seed |
| Exposure Decomposition | Time-in-market, avg exposure, high-vol regime exposure, benchmark correlation |
| Regime Contribution | Performance split by volatility regime buckets (QUIET/NORMAL/EXPANDING/EXTREME) |
| Capacity Test | Max position vs ADV estimate — categorized tiny/small/moderate/large |

### Artifacts

All outputs saved under `runs/<TICKER>/<RUN_ID>/RobustnessAgent/`:

| File | Format | Description |
|------|--------|-------------|
| `summary.json` | JSON | Top-level summary with key risk stats |
| `walk_forward.json` | JSON | Per-window walk-forward results |
| `walk_forward.csv` | CSV | Same, tabular |
| `sensitivity_map.json` | JSON | Grid search results |
| `sensitivity_map.csv` | CSV | Same, tabular |
| `monte_carlo.json` | JSON | Reshuffle simulation (percentiles, distribution) |
| `monte_carlo.csv` | CSV | Distribution summary |
| `exposure_decomposition.json` | JSON | Exposure analysis |
| `regime_contribution.json` | JSON | Per-regime performance buckets |
| `capacity_test.json` | JSON | ADV ratio and categorization |

### How to run

```bash
python run.py --ticker PLTR
python validate_run.py --run runs/PLTR/<RUN_ID>
```

Phase 6 artifacts are included in `final_report.json` under the `robustness` key and displayed in `final_report.html`.

## Phase 7: Shadow Mode (Live Paper-Run, Monitoring Only)

Shadow mode runs the full pipeline end-to-end and produces a monitoring snapshot — **without ever placing orders or calling any broker API**.

### How to run

```bash
# Shadow mode (monitoring-only)
python run.py --ticker PLTR --mode shadow

# Validate the run
python validate_run.py --run runs/PLTR/<RUN_ID>
```

### What it outputs

The `ShadowMonitorAgent` produces two artifacts under `ShadowMonitorAgent/`:

| File | Description |
|------|-------------|
| `shadow_metrics.json` | Full monitoring payload (decision, regime, drift flags, rolling ENTER frequency) |
| `shadow_summary.json` | Compact single-line oriented summary |

Both include `content_hash_sha256` for determinism validation.

A per-ticker append-only history is maintained at `runs/<TICKER>/_shadow_history/shadow_history.jsonl` for computing rolling metrics (e.g., ENTER frequency over the last 20 runs). This file is stateful and excluded from determinism checks.

When present, the shadow summary is also included in `final_report.json` under the `shadow` key.

### What it does NOT do

- **No trading / no execution**: Shadow mode never places orders
- **No broker API calls**: There is no broker code at all
- **No new strategy**: Uses the existing MA150-ATR pipeline as-is
- **No intraday data**: EOD-only, same data retrieval as backtest mode

### Nightly automation

A GitHub Actions workflow (`.github/workflows/nightly_pltr_shadow.yml`) runs shadow mode daily at 23:00 Israel time and sends a Telegram notification on success/failure.

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

## How to Commit & Push

### Method 1: VS Code Source Control UI (recommended)

1. Open the **Source Control** panel (Ctrl+Shift+G)
2. Stage files by clicking **+** next to each file (or **+** on "Changes" to stage all)
3. Type a commit message in the input box
4. Click the checkmark (or press Ctrl+Enter) to commit
5. Push happens automatically (configured via `.vscode/settings.json`)

### Method 2: CLI helper

```bash
# Stage your files first
git add <files>

# Commit + push with inline message
bash scripts/commit_helper.sh "Your commit message here"

# Or run interactively (will prompt for message)
bash scripts/commit_helper.sh

# Commit only, skip push
bash scripts/commit_helper.sh --no-push "Your message"

# Skip the unstaged-changes warning
bash scripts/commit_helper.sh --allow-unstaged "Your message"
```

The helper overrides the Codespaces `GIT_EDITOR=true` env var internally so commits never open a stale editor.

### Method 3: Raw git with safe wrapper

If you prefer raw git commands but want the editor override:

```bash
bash scripts/git_safe.sh commit -m "Your message"
bash scripts/git_safe.sh push
```

### Troubleshooting: COMMIT_EDITMSG opens in the editor

GitHub Codespaces sets `GIT_EDITOR=true` globally. When VS Code's Source Control tries to commit without `-m`, git launches the `true` binary as the editor — it exits immediately, produces an empty message, and leaves a stale `.git/COMMIT_EDITMSG` that VS Code then opens as a tab.

**Fix already applied in this repo:**
- `.git/config` sets `core.editor = "code --wait"` (overrides the env var for this repo)
- `.vscode/settings.json` sets `git.useEditorAsCommitInput: false` (uses the input box, not an editor)
- `scripts/commit_helper.sh` and `scripts/git_safe.sh` export safe `GIT_EDITOR`/`EDITOR`/`VISUAL` values

**Quick fix:** run the regression verifier and follow its output:
```bash
bash scripts/verify_commit_flow.sh
```
If a specific check fails, the script tells you the exact fix. For a manual override:
```bash
git config --local core.editor "code --wait"
```

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

**Version**: 0.6.0 (`v0.6.0-phase7-shadow`)
**Last Updated**: 2026-02-21
**Status**: Production-Ready MVP (Single-Ticker Mode, Phase 7 Shadow Monitoring)
