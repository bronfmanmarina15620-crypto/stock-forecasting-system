#!/usr/bin/env bash
# ============================================================
# determinism_check.sh
#
# Run the pipeline twice with identical config and verify that
# key output files are bit-for-bit identical (after normalising
# volatile metadata such as timestamps and run IDs).
#
# Compares BOTH raw and normalised SHA-256 hashes:
#   - raw match    → files are byte-identical (ideal)
#   - norm match   → deterministic content, volatile metadata differs
#   - norm differs → REAL non-determinism → FAIL
#
# Usage:
#   bash scripts/determinism_check.sh          # default ticker PLTR
#   bash scripts/determinism_check.sh TSLA     # custom ticker
#
# Exit codes:
#   0  All target files match  → DETERMINISM PASS
#   1  At least one mismatch   → DETERMINISM FAIL
# ============================================================
set -euo pipefail

TICKER="${1:-PLTR}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Determinism-critical env vars
export PYTHONHASHSEED=0

# Pin numeric library thread counts to 1 so BLAS/LAPACK operations
# are deterministic (multi-threaded reductions can reorder floats).
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

# Target files to compare (relative to run dir)
TARGET_FILES=(
  "BacktestAgent/metrics.json"
  "final_report.json"
  "DecisionRiskAgent/decision_action.json"
  "RobustnessAgent/summary.json"
  "RobustnessAgent/monte_carlo.json"
  "RobustnessAgent/walk_forward.json"
  "RobustnessAgent/sensitivity_map.json"
  "RobustnessAgent/exposure_decomposition.json"
  "RobustnessAgent/regime_contribution.json"
  "RobustnessAgent/capacity_test.json"
)

# Shadow-mode artifacts — included only when BOTH runs have them.
SHADOW_FILES=(
  "ShadowMonitorAgent/shadow_metrics.json"
  "ShadowMonitorAgent/shadow_summary.json"
)

TMPDIR_BASE=$(mktemp -d "${TMPDIR:-/tmp}/determinism_XXXXXX")
trap 'rm -rf "$TMPDIR_BASE"' EXIT

# ── helpers ──────────────────────────────────────────────────

log()  { echo "[determinism] $*"; }
fail() { echo "[determinism] FAIL: $*" >&2; }

latest_run_dir() {
  ls -dt "$ROOT_DIR/runs/$TICKER"/* 2>/dev/null | head -n 1
}

sha256_of() {
  sha256sum "$1" | awk '{print $1}'
}

normalize_json() {
  local input="$1" output="$2"
  python "$SCRIPT_DIR/normalize_json.py" "$input" "$output"
}

# ── main ─────────────────────────────────────────────────────

log "=========================================="
log "Determinism Check"
log "Ticker: $TICKER"
log "PYTHONHASHSEED=$PYTHONHASHSEED"
log "OMP_NUM_THREADS=$OMP_NUM_THREADS"
log "MKL_NUM_THREADS=$MKL_NUM_THREADS"
log "OPENBLAS_NUM_THREADS=$OPENBLAS_NUM_THREADS"
log "NUMEXPR_NUM_THREADS=$NUMEXPR_NUM_THREADS"
log "=========================================="

# ── Run A ────────────────────────────────────────────────────

log "Starting run A ..."
python "$ROOT_DIR/run.py" --ticker "$TICKER"
RUN1_DIR=$(latest_run_dir)
if [[ -z "$RUN1_DIR" ]]; then
  fail "No run directory found after run A"
  exit 1
fi
RUN1_ID=$(basename "$RUN1_DIR")
log "Run A completed: $RUN1_ID"

# ── Run B ────────────────────────────────────────────────────

log "Starting run B ..."
python "$ROOT_DIR/run.py" --ticker "$TICKER"
RUN2_DIR=$(latest_run_dir)
RUN2_ID=$(basename "$RUN2_DIR")
if [[ -z "$RUN2_DIR" || "$RUN2_DIR" == "$RUN1_DIR" ]]; then
  fail "Run B did not produce a new run directory"
  exit 1
fi
log "Run B completed: $RUN2_ID"

log ""
log "Run A: $RUN1_ID"
log "Run B: $RUN2_ID"
log ""

# ── Validate both runs ──────────────────────────────────────

log "Validating run A ..."
if ! python "$ROOT_DIR/validate_run.py" --run "$RUN1_DIR"; then
  fail "Validation failed for run A ($RUN1_DIR)"
  exit 1
fi
log "Validation passed for run A"

log "Validating run B ..."
if ! python "$ROOT_DIR/validate_run.py" --run "$RUN2_DIR"; then
  fail "Validation failed for run B ($RUN2_DIR)"
  exit 1
fi
log "Validation passed for run B"

# ── Conditionally include shadow artifacts ─────────────────

for sf in "${SHADOW_FILES[@]}"; do
  if [[ -f "$RUN1_DIR/$sf" && -f "$RUN2_DIR/$sf" ]]; then
    TARGET_FILES+=("$sf")
    log "Including shadow artifact: $sf"
  elif [[ -f "$RUN1_DIR/$sf" || -f "$RUN2_DIR/$sf" ]]; then
    log "WARNING: shadow artifact $sf exists in only one run — skipping"
  fi
done

# ── Compare target files ────────────────────────────────────

PASS=true
MISMATCH_COUNT=0

log ""
log "=========================================="
log "Comparing target files"
log "=========================================="

for relpath in "${TARGET_FILES[@]}"; do
  file_a="$RUN1_DIR/$relpath"
  file_b="$RUN2_DIR/$relpath"

  if [[ ! -f "$file_a" ]]; then
    fail "Missing in run A: $relpath"
    PASS=false
    MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    continue
  fi
  if [[ ! -f "$file_b" ]]; then
    fail "Missing in run B: $relpath"
    PASS=false
    MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    continue
  fi

  # ── raw comparison ──
  raw_hash_a=$(sha256_of "$file_a")
  raw_hash_b=$(sha256_of "$file_b")

  # ── normalised comparison (JSON only) ──
  ext="${relpath##*.}"
  if [[ "$ext" == "json" ]]; then
    norm_a="$TMPDIR_BASE/a_$(echo "$relpath" | tr '/' '_')"
    norm_b="$TMPDIR_BASE/b_$(echo "$relpath" | tr '/' '_')"
    normalize_json "$file_a" "$norm_a"
    normalize_json "$file_b" "$norm_b"
    norm_hash_a=$(sha256_of "$norm_a")
    norm_hash_b=$(sha256_of "$norm_b")
  else
    norm_hash_a="$raw_hash_a"
    norm_hash_b="$raw_hash_b"
    norm_a="$file_a"
    norm_b="$file_b"
  fi

  echo ""
  echo "--- $relpath ---"
  echo "  raw  A: $raw_hash_a"
  echo "  raw  B: $raw_hash_b"
  echo "  norm A: $norm_hash_a"
  echo "  norm B: $norm_hash_b"

  if [[ "$norm_hash_a" != "$norm_hash_b" ]]; then
    echo "  Result: MISMATCH (normalised content differs — real non-determinism)"
    PASS=false
    MISMATCH_COUNT=$((MISMATCH_COUNT + 1))

    echo ""
    echo "  Diff (first 100 lines of normalised output):"
    diff -u "$norm_a" "$norm_b" | head -n 100 | sed 's/^/    /' || true
  elif [[ "$raw_hash_a" != "$raw_hash_b" ]]; then
    echo "  Result: MATCH (raw mismatch due to volatile metadata only)"
  else
    echo "  Result: MATCH (byte-identical)"
  fi
done

# ── content_hash_sha256 cross-check ─────────────────────────

log ""
log "=========================================="
log "Content hash cross-check"
log "=========================================="

for relpath in "${TARGET_FILES[@]}"; do
  ext="${relpath##*.}"
  [[ "$ext" != "json" ]] && continue

  file_a="$RUN1_DIR/$relpath"
  file_b="$RUN2_DIR/$relpath"
  [[ ! -f "$file_a" || ! -f "$file_b" ]] && continue

  hash_a=$(python -c "import json; d=json.load(open('$file_a')); print(d.get('content_hash_sha256','(missing)'))")
  hash_b=$(python -c "import json; d=json.load(open('$file_b')); print(d.get('content_hash_sha256','(missing)'))")

  echo "  $relpath"
  echo "    A content_hash: $hash_a"
  echo "    B content_hash: $hash_b"
  if [[ "$hash_a" == "$hash_b" ]]; then
    echo "    Result: MATCH"
  else
    echo "    Result: MISMATCH"
    # Don't fail here — the normalised comparison is authoritative
  fi
done

# ── verdict ──────────────────────────────────────────────────

echo ""
echo "=========================================="
if $PASS; then
  echo "DETERMINISM PASS  (all ${#TARGET_FILES[@]} files match)"
  echo "=========================================="
  exit 0
else
  echo "DETERMINISM FAIL  ($MISMATCH_COUNT of ${#TARGET_FILES[@]} files differ)"
  echo "=========================================="
  exit 1
fi
