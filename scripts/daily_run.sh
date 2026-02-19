#!/usr/bin/env bash
# daily_run.sh - Daily pipeline: run, validate, report.
#
# Usage:
#   bash scripts/daily_run.sh [TICKER]
#
# Exit codes:
#   0 = Run + validation passed
#   1 = Run or validation failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

TICKER="${1:-PLTR}"

echo "============================================================"
echo "DAILY RUN: $TICKER"
echo "Started: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"

# Step 1: Run pipeline
echo ""
echo "[1/3] Running pipeline..."
if ! python run.py --ticker "$TICKER"; then
    echo "[FAIL] Pipeline exited with error"
    exit 1
fi

# Step 2: Find latest run
LATEST_DIR=$(ls -dt runs/"$TICKER"/* 2>/dev/null | head -n 1)
if [ -z "$LATEST_DIR" ]; then
    echo "[FAIL] No run directory found"
    exit 1
fi
echo ""
echo "Run directory: $LATEST_DIR"

# Step 3: Validate
echo ""
echo "[2/3] Validating run..."
if ! python validate_run.py --run "$LATEST_DIR"; then
    echo "[FAIL] Validation failed"
    exit 1
fi

# Step 4: Summary
echo ""
echo "[3/3] Summary"
echo "============================================================"
echo "DAILY RUN COMPLETE: $TICKER"
echo "Run:    $LATEST_DIR"
echo "Report: $LATEST_DIR/final_report.html"
echo "JSON:   $LATEST_DIR/final_report.json"
echo "Status: $LATEST_DIR/status.json"
echo "Finished: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
exit 0
