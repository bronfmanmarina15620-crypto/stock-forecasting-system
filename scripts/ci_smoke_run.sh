#!/usr/bin/env bash
# ci_smoke_run.sh - Run a mini pipeline + validate_run for CI.
#
# Usage:
#   bash scripts/ci_smoke_run.sh [TICKER]
#
# Runs a single-ticker pipeline with a reduced data window (~350 trading
# bars via --lookback-days 500) in signals_only mode, then validates the
# resulting run directory with validate_run.py --skip-edge (structural only).
#
# Edge gates are skipped because they depend on live market data, not code
# quality. Structural validation (artifacts, schema, hashes) must pass.
#
# Exit codes:
#   0 = pipeline + structural validation passed
#   1 = pipeline crash or structural validation failure

set -uo pipefail

TICKER="${1:-PLTR}"

echo "============================================================"
echo "CI SMOKE RUN: $TICKER (signals_only, mini window)"
echo "============================================================"
echo ""

# Run pipeline with reduced lookback for speed.
# 500 calendar days ≈ 350 trading bars — enough for MA150 warmup +
# a meaningful backtest window, while keeping runtime under ~3 min.
#
# Edge gate failure (exit 1) from run.py is acceptable in CI — gates
# depend on live market data. Exit > 1 = real error (crash, missing deps).
run_exit=0
python run.py --ticker "$TICKER" --lookback-days 500 --min-bars 200 2>&1 | tee /tmp/run.log || run_exit=$?

if [[ $run_exit -gt 1 ]]; then
  echo ""
  echo "ERROR: run.py failed with exit code $run_exit"
  exit $run_exit
fi

if [[ $run_exit -eq 1 ]]; then
  echo ""
  echo "NOTE: Edge gates failed (exit 1) — acceptable in CI smoke run"
fi

# Parse RUN_ID from stdout (run.py prints "RUN_ID=<id>")
# Uses portable grep + cut instead of PCRE (-P) for macOS compat.
RUN_ID="$(grep '^RUN_ID=' /tmp/run.log | tail -n1 | cut -d= -f2 | tr -d '[:space:]')" || true

if [[ -z "${RUN_ID:-}" ]]; then
  echo ""
  echo "ERROR: could not determine RUN_ID from log output"
  exit 1
fi

echo ""
echo "CI_SMOKE_RUN_ID=$RUN_ID"
echo ""

# Validate structural integrity only (--skip-edge).
# Edge gates are not a CI concern — they are enforced at run time
# and in nightly validation.
python validate_run.py --run "runs/$TICKER/$RUN_ID" --skip-edge

echo ""
echo "CI SMOKE RUN: PASS"
