#!/usr/bin/env bash
# smoke_test_10_runs.sh - Run the pipeline 10 times and validate each run.
# Fails fast if any run fails or validation fails.
#
# Usage:
#   bash scripts/smoke_test_10_runs.sh
#
# Exit codes:
#   0 = All 10 runs passed
#   1 = At least one run failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

TICKER="${1:-PLTR}"
NUM_RUNS=10
PASSED=0
FAILED=0

echo "============================================================"
echo "SMOKE TEST: $NUM_RUNS consecutive runs for $TICKER"
echo "============================================================"
echo "Repository: $REPO_DIR"
echo "Started:    $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

for i in $(seq 1 $NUM_RUNS); do
    echo "------------------------------------------------------------"
    echo "RUN $i / $NUM_RUNS"
    echo "------------------------------------------------------------"

    # Run the pipeline
    if ! python run.py --ticker "$TICKER" 2>&1; then
        echo "[FAIL] Run $i: pipeline exited with error"
        FAILED=$((FAILED + 1))
        echo ""
        echo "============================================================"
        echo "SMOKE TEST FAILED at run $i"
        echo "Passed: $PASSED / $NUM_RUNS"
        echo "============================================================"
        exit 1
    fi

    # Find latest run directory
    LATEST_DIR=$(ls -dt runs/"$TICKER"/* 2>/dev/null | head -n 1)
    if [ -z "$LATEST_DIR" ]; then
        echo "[FAIL] Run $i: no run directory found"
        FAILED=$((FAILED + 1))
        exit 1
    fi

    echo "Run directory: $LATEST_DIR"

    # Validate the run
    if ! python validate_run.py --run "$LATEST_DIR" 2>&1; then
        echo "[FAIL] Run $i: validation failed"
        FAILED=$((FAILED + 1))
        echo ""
        echo "============================================================"
        echo "SMOKE TEST FAILED at run $i (validation)"
        echo "Passed: $PASSED / $NUM_RUNS"
        echo "============================================================"
        exit 1
    fi

    PASSED=$((PASSED + 1))
    echo "[OK] Run $i PASSED"
    echo ""
done

echo "============================================================"
echo "SMOKE TEST PASSED: $PASSED / $NUM_RUNS runs successful"
echo "Finished: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
exit 0
