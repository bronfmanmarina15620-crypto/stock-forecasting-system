# validate_run.py - Usage Guide

## Overview

`validate_run.py` is a strict validator that checks if a run produced all required artifacts and meets quality standards.

## Usage

```bash
# Basic usage
python validate_run.py --run runs/PLTR/20260214_151806_xaji0y

# Or with a variable
RUN_PATH="runs/PLTR/20260214_151806_xaji0y"
python validate_run.py --run $RUN_PATH
```

## Exit Codes

- **0** = PASS (all validations passed)
- **1** = FAIL (one or more validations failed)

## What It Checks

### 1. Required Artifacts
Ensures all required files exist as defined by `REQUIRED_ARTIFACTS` in `validate_run.py` (authoritative source). Mode-dependent artifacts (`ShadowMonitorAgent`, `DriftAgent`) are validated only when the corresponding folder exists.

> **Note**: The artifact list below is a snapshot for quick reference. If it diverges from `validate_run.py`, the code is authoritative.

**BacktestAgent:**
- trades.parquet
- pnl_series.parquet
- metrics.json
- costs_assumptions.json
- risk_explain.json

**DecisionRiskAgent:**
- signals.csv
- abstain_stats.json
- decision_action.json
- decision_explain.json

**RobustnessAgent:**
- summary.json
- monte_carlo.json

**Root:**
- status.txt
- status.json
- config.json
- config_snapshot.yaml
- final_report.html
- final_report.json

### 2. Sanity Tests
Validates that sanity tests passed:

- **shuffled_labels_auc** ≤ 0.55
  - Model shouldn't work with shuffled labels
  
- **future_shift_auc** ≤ 0.55
  - Model shouldn't work with future data

### 3. Metrics
Checks that metrics.json contains required fields as defined by `REQUIRED_METRICS_FIELDS` in `validate_run.py` (authoritative source).

### 4. Abstain Statistics
Checks that abstain_stats.json contains required fields as defined by `REQUIRED_ABSTAIN_FIELDS` in `validate_run.py` (authoritative source).

### 5. OOS Sample Size
Warns if predictions_oos.parquet has < 250 rows

⚠️ This is a WARNING, not a failure

## Example Output

### ✅ Successful Validation

```
============================================================
RUN VALIDATION
============================================================
Run path: C:\...\runs\PLTR\20260214_151806_xaji0y

============================================================
STEP 1: Checking Required Artifacts
============================================================

✓ Folder exists: BacktestAgent
  ✓ predictions_oos.parquet
  ✓ sanity_tests.json
  ✓ trades.parquet
  ✓ pnl_series.parquet
  ✓ metrics.json
  ✓ costs_assumptions.json

✓ Folder exists: DecisionRiskAgent
  ✓ signals.csv
  ✓ abstain_stats.json
  ✓ decision_action.json
  ✓ decision_explain.json

✓ Folder exists: DashboardAgent
  ✓ final_report.html
  ✓ final_report.json

✓ Folder exists: _ROOT_
  ✓ status.txt

============================================================
STEP 2: Validating Sanity Tests
============================================================
✓ Shuffled labels AUC: 0.512 (PASS)
✓ Future shift AUC: 0.498 (PASS)

============================================================
STEP 3: Validating Metrics
============================================================

Required fields:
  ✓ EV_per_trade: 0.0052
  ✓ max_drawdown: -0.083
  ✓ win_rate: 0.621
  ✓ avg_trades_per_month: 4.2

============================================================
STEP 4: Validating Abstain Statistics
============================================================

Required fields:
  ✓ abstain_ratio: 0.785
  ✓ enter_count: 42
  ✓ abstain_count: 154
  ✓ signals_per_month: 4.2

============================================================
STEP 5: Validating OOS Sample Size
============================================================

OOS rows: 384
✓ Sufficient OOS samples (≥ 250)

============================================================
VALIDATION SUMMARY
============================================================

✅ VALIDATION PASSED
All checks passed successfully!
============================================================
```

### ❌ Failed Validation

```
============================================================
STEP 2: Validating Sanity Tests
============================================================
❌ Shuffled labels AUC: 0.652 (FAIL - should be ≤ 0.55)
✓ Future shift AUC: 0.498 (PASS)

============================================================
VALIDATION SUMMARY
============================================================

❌ VALIDATION FAILED

Failure reasons:
  - Sanity FAIL: shuffled_labels_auc=0.652 > 0.55
============================================================
```

### ⚠️ Validation with Warnings

```
============================================================
STEP 5: Validating OOS Sample Size
============================================================

OOS rows: 84
⚠️  WARNING: Only 84 OOS samples (< 250 recommended)

============================================================
VALIDATION SUMMARY
============================================================

⚠️  WARNINGS:
  - INSUFFICIENT_OOS_SAMPLES: 84 rows (< 250 recommended)

✅ VALIDATION PASSED
All critical checks passed (warnings present).
============================================================
```

## Integration with Pipeline

### In Orchestrator

```python
import subprocess

# After all agents complete
result = subprocess.run(
    ["python", "validate_run.py", "--run", run_path],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print("Validation failed!")
    print(result.stdout)
    # Set status to FAILED
    # Force DecisionRiskAgent to ABSTAIN only
```

### In Batch Script

```batch
@echo off

REM Run the system
python run.py --ticker PLTR

REM Find latest run
for /f "delims=" %%i in ('dir /b /ad /o-d "runs\PLTR"') do (
    set LATEST=%%i
    goto :validate
)

:validate
REM Validate
python validate_run.py --run runs\PLTR\%LATEST%

if %ERRORLEVEL% NEQ 0 (
    echo ❌ Validation failed!
    exit /b 1
)

echo ✅ Validation passed!
```

## Troubleshooting

### "pyarrow not installed"

Install it:
```bash
pip install pyarrow
```

Or ignore the OOS count warning if you don't need it.

### "Missing file: ..."

The run didn't complete successfully. Check:
1. Run logs in `runs/.../status.txt`
2. Agent output in `runs/.../[Agent]/output.json`

### Sanity test failures

This is serious! It means:
- Data leakage
- Future information in features
- Model is seeing the labels somehow

**Do not use this run for trading!**

## Advanced Usage

### Check specific run

```bash
python validate_run.py --run runs/PLTR/20260214_151806_xaji0y
```

### Use in CI/CD

```bash
python validate_run.py --run $RUN_PATH || exit 1
```

### Batch validate multiple runs

```bash
for run in runs/PLTR/*; do
    echo "Validating $run..."
    python validate_run.py --run "$run"
done
```

## Notes

- This validator is **strict** - it fails on any missing artifact
- Warnings don't cause failure (exit code 0)
- Sanity test failures DO cause failure
- Missing required fields cause failure
- The validator does NOT parse HTML
- The validator does NOT modify any files
