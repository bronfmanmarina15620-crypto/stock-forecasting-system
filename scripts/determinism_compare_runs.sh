#!/usr/bin/env bash
# ============================================================
# determinism_compare_runs.sh
#
# Compare determinism baselines between two existing runs
# WITHOUT re-running the pipeline.  If a run's baseline
# directory doesn't exist yet, it is generated on the fly.
#
# Usage:
#   bash scripts/determinism_compare_runs.sh <run_a> <run_b>
#
# Example:
#   bash scripts/determinism_compare_runs.sh \
#     runs/PLTR/20260219_215849_xaji0y \
#     runs/PLTR/20260219_215853_xaji0y
#
# Exit codes:
#   0  All target files match
#   1  At least one mismatch or missing file
# ============================================================
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <run_dir_a> <run_dir_b>" >&2
  echo "Example: $0 runs/PLTR/20260219_120000_abc123 runs/PLTR/20260219_130000_def456" >&2
  exit 1
fi

RUN_A="$1"
RUN_B="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for dir in "$RUN_A" "$RUN_B"; do
  if [[ ! -d "$dir" ]]; then
    echo "Error: Run directory not found: $dir" >&2
    exit 1
  fi
done

# ── ensure baselines exist ────────────────────────────────────

ensure_baseline() {
  local run_dir="$1"
  if [[ ! -d "$run_dir/determinism_baseline" ]]; then
    echo "[compare] Generating baseline for $(basename "$run_dir") ..."
    bash "$SCRIPT_DIR/determinism_baseline.sh" "$run_dir"
    echo ""
  fi
}

ensure_baseline "$RUN_A"
ensure_baseline "$RUN_B"

# ── compare ───────────────────────────────────────────────────

NORM_FILES=(
  "BacktestAgent_metrics.norm.json"
  "final_report.norm.json"
  "DecisionRiskAgent_decision_action.norm.json"
)

# Map norm filenames back to original relpaths for content_hash lookup
declare -A ORIG_FILES=(
  ["BacktestAgent_metrics.norm.json"]="BacktestAgent/metrics.json"
  ["final_report.norm.json"]="final_report.json"
  ["DecisionRiskAgent_decision_action.norm.json"]="DecisionRiskAgent/decision_action.json"
)

PASS=true
MISMATCH_COUNT=0

echo "=========================================="
echo "Determinism Run Comparison"
echo "Run A: $(basename "$RUN_A")"
echo "Run B: $(basename "$RUN_B")"
echo "=========================================="

for norm_name in "${NORM_FILES[@]}"; do
  file_a="$RUN_A/determinism_baseline/$norm_name"
  file_b="$RUN_B/determinism_baseline/$norm_name"
  orig_relpath="${ORIG_FILES[$norm_name]}"

  echo ""
  echo "--- ${orig_relpath} ---"

  # Check existence
  if [[ ! -f "$file_a" ]]; then
    echo "  MISSING in run A: $norm_name"
    PASS=false
    MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    continue
  fi
  if [[ ! -f "$file_b" ]]; then
    echo "  MISSING in run B: $norm_name"
    PASS=false
    MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    continue
  fi

  # Normalised sha256
  sha_a=$(sha256sum "$file_a" | awk '{print $1}')
  sha_b=$(sha256sum "$file_b" | awk '{print $1}')
  echo "  baseline sha256 A: $sha_a"
  echo "  baseline sha256 B: $sha_b"

  # Embedded content_hash from original files
  orig_a="$RUN_A/$orig_relpath"
  orig_b="$RUN_B/$orig_relpath"
  ch_a="(n/a)"; ch_b="(n/a)"
  [[ -f "$orig_a" ]] && ch_a=$(python -c "import json; print(json.load(open('$orig_a')).get('content_hash_sha256','(missing)'))")
  [[ -f "$orig_b" ]] && ch_b=$(python -c "import json; print(json.load(open('$orig_b')).get('content_hash_sha256','(missing)'))")
  echo "  content_hash   A: $ch_a"
  echo "  content_hash   B: $ch_b"

  if [[ "$sha_a" != "$sha_b" ]]; then
    echo "  Result: MISMATCH"
    PASS=false
    MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    echo ""
    echo "  Diff (first 100 lines):"
    diff -u "$file_a" "$file_b" | head -n 100 | sed 's/^/    /' || true
  else
    echo "  Result: MATCH"
  fi
done

# ── verdict ───────────────────────────────────────────────────

echo ""
echo "=========================================="
if $PASS; then
  echo "COMPARE PASS  (all ${#NORM_FILES[@]} files match)"
  echo "=========================================="
  exit 0
else
  echo "COMPARE FAIL  ($MISMATCH_COUNT of ${#NORM_FILES[@]} files differ)"
  echo "=========================================="
  exit 1
fi
