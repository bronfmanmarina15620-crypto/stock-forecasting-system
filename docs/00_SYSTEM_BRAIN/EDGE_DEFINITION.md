# EDGE_DEFINITION — MA150 + ATR (Hardening Contract)

Status: DRAFT → becomes NON-NEGOTIABLE once merged to main.
Scope: Statistical validation + gating rules only.
Strategy: Single strategy only — MA150 + ATR (no expansion).

## 0) Non-negotiable
- Deterministic runs only (same inputs → same outputs).
- No strategy expansion (no new indicators, no new filters).
- No silent fallbacks (any missing/invalid artifact = FAIL).
- No architecture changes unless explicitly required by edge measurement plumbing.
- All thresholds in this file must be testable from existing artifacts.

## 1) Definitions (canonical)
Let each trade i have:
- R_i = realized R-multiple (PnL divided by initial risk per trade).
- Win_i = 1 if R_i > 0 else 0.

Core metrics:
- Win rate (WR) = mean(Win_i)
- Avg win (AW) = mean(R_i | R_i > 0)
- Avg loss (AL) = abs(mean(R_i | R_i < 0))
- Expectancy (E[R]) = mean(R_i) = WR*AW - (1-WR)*AL
- Profit Factor (PF) = sum(max(R_i,0)) / abs(sum(min(R_i,0)))
- Max Drawdown in R (MDD_R) = max peak-to-trough drawdown over cumulative R curve
- Trade count (N) = number of trades used in sample

Robustness metrics:
- Rolling expectancy E_roll(k) over rolling window of k trades (or k days if trade count too sparse)
- Walk-forward stability: E_train, E_test per fold
- Sensitivity stability: small parameter perturbations should not flip sign of E[R] except near boundary

## 2) Artifact sources (must already exist)
All edge calculations MUST be derived from existing run artifacts.
Primary sources (expected locations):
- BacktestAgent/trades.parquet — per-trade R-multiples (r_multiple column)
- BacktestAgent/metrics.json — aggregate metrics
- RobustnessAgent/walk_forward.json — per-window expectancy
- RobustnessAgent/monte_carlo.json — drawdown distribution (DD_SHOCK reference)
- RobustnessAgent/regime_contribution.json — per-regime mean_return

If per-trade R list is not present, derive it only from existing backtest outputs (no new model logic).
If impossible, the only allowed "code change" is **exporting already-computed trade outcomes** (not changing strategy).

## 3) Edge claim (what "edge exists" means)
Edge is considered PRESENT if all conditions below hold on the selected evaluation sample:

### 3.1 Minimum sample size gate
- N >= N_MIN

### 3.2 Core profitability gate
- E[R] >= E_MIN
- PF >= PF_MIN

### 3.3 Drawdown gate
- MDD_R <= MDD_MAX

### 3.4 Stability gate (no decay)
- Rolling expectancy: proportion of rolling windows with E_roll > 0 >= POS_ROLL_RATIO_MIN
- Walk-forward: median(E_test) >= WF_E_MIN and %folds(E_test > 0) >= WF_POS_FOLDS_MIN

### 3.5 Regime localization (where edge exists)
- RegimeContribution must show E[R] >= E_MIN in "allowed regimes"
- Any regime with persistent negative E[R] is labeled "NO-TRADE regime"

## 4) ENTER vs ABSTAIN decision contract
DecisionRiskAgent must output:

ENTER iff ALL are true:
1) Technical conditions for the single strategy are satisfied (existing definition).
2) Regime is allowed (not in NO-TRADE list).
3) Edge gates pass (Sections 3.1–3.4) on the *current validated edge snapshot*.
4) Kill-switch is NOT active (Section 5).

Otherwise: ABSTAIN.

No partial ENTER, no heuristic overrides.

## 5) Kill-switch contract (must force ABSTAIN)
Kill-switch triggers ABSTAIN for all signals until reset if any condition holds:

### 5.1 Rolling edge breakdown
- Last ROLL_K windows: E_roll <= 0 for >= ROLL_FAIL_STREAK windows

### 5.2 Drawdown shock
- Current drawdown in R exceeds DD_SHOCK (e.g., exceeds historical 95th percentile from Monte Carlo)

### 5.3 Data integrity / artifact integrity failure
- Any required artifact missing, hash mismatch, or validation fails → ABSTAIN + FAIL run

Reset rules (explicit):
- Reset only after: (a) validation passes and (b) rolling edge recovers above 0 for RESET_STREAK windows.

## 6) Thresholds (single source of truth)
Runtime source of truth: `config/edge.yaml`
Calibrated by `tools/edge_calibrate.py` from historical runs (rule-based, deterministic).
Do not change without updating this file and tests.

| Threshold | Value | Min Floor | Description |
|-----------|-------|-----------|-------------|
| N_MIN | 30 | 30 | Minimum trade count |
| E_MIN | 0.0 | 0.0 | Minimum expectancy E[R] |
| PF_MIN | 1.0 | 1.0 | Minimum profit factor |
| MDD_MAX | 5.0 | — | Max drawdown in R (cumulative R units) |
| POS_ROLL_RATIO_MIN | 0.5 | 0.5 | Fraction of rolling windows with E_roll > 0 |
| WF_E_MIN | 0.0 | — | Median walk-forward expectancy |
| WF_POS_FOLDS_MIN | 0.5 | 0.5 | Fraction of folds with positive expectancy |
| ROLL_K | 20 | — | Rolling window size (trades) |
| ROLL_FAIL_STREAK | 5 | — | Consecutive negative windows → kill-switch |
| DD_SHOCK | 10.0 | — | Drawdown in R → kill-switch |
| RESET_STREAK | 3 | — | Positive windows to reset kill-switch |

### Calibration method
Thresholds are calibrated by `tools/edge_calibrate.py` (authoritative implementation) using rule-based quantile extraction from eligible historical runs (runs with all 4 required artifacts present). The formulas below summarize the current approach; if discrepancies exist, `tools/edge_calibrate.py` is the source of truth.
- **n_min**: `max(floor=30, floor(p25 of N))` — p25 ensures 75%+ of historical runs pass.
- **e_min, pf_min, wf_e_min**: Theoretical floors (0.0, 1.0, 0.0) — non-negative expectancy and edge presence are economically meaningful regardless of data.
- **mdd_max**: `min(ceiling=15.0, max(p90 of MDD_R * 2, floor=5.0))` — 2x headroom over observed p90.
- **pos_roll_ratio_min, wf_pos_folds_min**: `max(floor=0.5, p20 among PASS-like runs)`. When metric diversity < 3 unique values, the floor dominates to avoid overfitting.
- **Structural parameters** (roll_k, roll_fail_streak, dd_shock, reset_streak): Kept at defaults, not calibrated from data.
- **Overfitting avoidance**: When metric diversity is low (< 3 unique values), floors/ceilings are used instead of percentiles. Kill-switch parameters are never tuned to data.
- **Recalibration**: Run `python tools/edge_calibrate.py --ticker PLTR --runs-root runs/PLTR --out config/edge.yaml` after accumulating more runs for tighter data-driven thresholds.

### Calibration safeguards
Calibration cannot reduce thresholds below minimum meaningful floors (`n_min >= 30`, `pos_roll_ratio_min >= 0.5`, `wf_pos_folds_min >= 0.5`, `e_min >= 0.0`, `pf_min >= 1.0`). When the distribution is degenerate (e.g., most runs have N < roll_k), the metric is marked `INSUFFICIENT_DATA` and the floor is kept. Additionally, calibration requires at least 10 eligible runs and 3 PASS-like runs; insufficient history results in exit code 2 and no overwrite of `config/edge.yaml` (a diagnostic report is still written).

## 7) Verification (must be runnable)
Commands:
- python -m pytest -q
- python run.py --ticker PLTR
- python validate_run.py --run runs/PLTR/<RUN_ID>

Edge validation:
- python tools/edge_validate.py --run runs/PLTR/<RUN_ID>
  - must print: N, E[R], PF, MDD_R, rolling stats, WF summary, regime table
  - exit code 0 if gates pass, 1 if gates fail, 2 if artifacts missing/invalid

## 8) Definition of Done (DoD)
- EDGE_DEFINITION.md merged with thresholds filled (non-empty).
- edge_validate tool exists OR existing validator emits the same fields deterministically.
- DecisionRiskAgent uses ONLY these gates to decide ENTER/ABSTAIN (no hidden rules).
- Tests cover:
  - deterministic edge computation
  - fail on missing artifact (no silent fallback)
  - boundary tests around thresholds
- At least one historical run demonstrates PASS and one demonstrates FAIL with clear reasons.
