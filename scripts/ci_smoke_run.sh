#!/usr/bin/env bash
# ci_smoke_run.sh - Run a mini pipeline + validate_run for CI.
#
# Usage:
#   bash scripts/ci_smoke_run.sh [TICKER]
#
# Runs a single-ticker pipeline with a reduced data window (~350 trading
# bars via --lookback-days 500) in signals_only mode, then validates the
# resulting run directory with validate_run.py.
#
# Exit codes:
#   0 = pipeline + validation passed
#   1 = pipeline or validation failed

set -euo pipefail

TICKER="${1:-PLTR}"

echo "============================================================"
echo "CI SMOKE RUN: $TICKER (signals_only, mini window)"
echo "============================================================"
echo ""

# Run pipeline with reduced lookback for speed.
# 500 calendar days ≈ 350 trading bars — enough for MA150 warmup +
# a meaningful backtest window, while keeping runtime under ~3 min.
python run.py --ticker "$TICKER" --lookback-days 500 --min-bars 200 2>&1 | tee /tmp/run.log

# Parse RUN_ID from stdout (run.py prints "RUN_ID=<id>")
RUN_ID="$(grep -oP 'RUN_ID=\K[0-9]{8}_[0-9]{6}_[a-z0-9]+' /tmp/run.log | tail -n1)" || true

if [[ -z "${RUN_ID:-}" ]]; then
  echo ""
  echo "ERROR: could not determine RUN_ID from log output"
  exit 1
fi

echo ""
echo "CI_SMOKE_RUN_ID=$RUN_ID"
echo ""

# Validate the run artifacts and schema
python validate_run.py --run "runs/$TICKER/$RUN_ID"
