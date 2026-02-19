#!/usr/bin/env bash
# ============================================================
# determinism_baseline.sh
#
# Generate normalised baselines for a single run's target files.
# Useful for debugging CI failures: baseline a known-good run,
# then diff against the failing run.
#
# Usage:
#   bash scripts/determinism_baseline.sh runs/PLTR/<RUN_ID>
#
# Output:
#   <RUN_DIR>/determinism_baseline/BacktestAgent_metrics.norm.json
#   <RUN_DIR>/determinism_baseline/final_report.norm.json
#   <RUN_DIR>/determinism_baseline/DecisionRiskAgent_decision_action.norm.json
# ============================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <run_dir>" >&2
  echo "Example: $0 runs/PLTR/20260219_215230_xaji0y" >&2
  exit 1
fi

RUN_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$RUN_DIR" ]]; then
  echo "Error: Run directory not found: $RUN_DIR" >&2
  exit 1
fi

BASELINE_DIR="$RUN_DIR/determinism_baseline"
mkdir -p "$BASELINE_DIR"

TARGET_FILES=(
  "BacktestAgent/metrics.json"
  "final_report.json"
  "DecisionRiskAgent/decision_action.json"
)

echo "=========================================="
echo "Determinism Baseline"
echo "Run: $(basename "$RUN_DIR")"
echo "=========================================="
echo ""

for relpath in "${TARGET_FILES[@]}"; do
  src="$RUN_DIR/$relpath"

  # Convert path to flat filename: BacktestAgent/metrics.json → BacktestAgent_metrics.norm.json
  norm_name="$(echo "$relpath" | tr '/' '_' | sed 's/\.json$/.norm.json/')"
  dest="$BASELINE_DIR/$norm_name"

  if [[ ! -f "$src" ]]; then
    echo "  SKIP: $relpath (not found)"
    echo ""
    continue
  fi

  python "$SCRIPT_DIR/normalize_json.py" "$src" "$dest"

  sha=$(sha256sum "$dest" | awk '{print $1}')
  content_hash=$(python -c "import json; print(json.load(open('$src')).get('content_hash_sha256','(missing)'))")

  echo "--- $relpath ---"
  echo "  normalised  → $norm_name"
  echo "  sha256:       $sha"
  echo "  content_hash: $content_hash"
  echo ""
done

echo "Baselines written to: $BASELINE_DIR/"
echo "=========================================="
