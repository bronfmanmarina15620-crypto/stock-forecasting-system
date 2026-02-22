# Reproducibility & Determinism

> **SNAPSHOT NOTICE**
> This document reflects the repo state at the time of writing.
> Authoritative sources: `determinism.py` (normaliser/volatile keys), `validate_run.py` (content hash checks), `scripts/determinism_check.sh` (check script).
> If discrepancies exist, treat code as source of truth.

## What "determinism" means in this project

Given **identical configuration** and **identical market data**, two consecutive
pipeline runs must produce **identical deterministic content** in the key output
files, even though volatile metadata (timestamps, run IDs, file paths) will
naturally differ.

The three files under the determinism contract are:

| File | Producer | Contains |
|------|----------|----------|
| `BacktestAgent/metrics.json` | BacktestAgent | AUC, EV, drawdown, win rate |
| `DecisionRiskAgent/decision_action.json` | DecisionRiskAgent | ENTER/ABSTAIN decision |
| `final_report.json` | DashboardAgent | Aggregated report |

Other files (HTML reports, logs, status files) may contain volatile metadata
and are **not** covered by the determinism check.

---

## Content hash vs volatile metadata

Each of the 3 target files includes a `content_hash_sha256` field — a SHA-256
digest computed from the file's **normalised** content (volatile fields stripped,
keys sorted).  This lets you visually confirm determinism
without running the full check script:

```json
{
  "EV_per_trade": 0.0,
  "content_hash_sha256": "e44fc22ffdf5...",
  "overall": { "auc": 0.382, ... },
  ...
}
```

The hash is **stable** across runs when the true analytical content is the same.
Volatile metadata (timestamps, paths) is intentionally **kept** in production
outputs for audit and debugging.

---

## How determinism is enforced

### Random seeds (set once in `run.py` via `set_random_seeds()`)

| Source | Mechanism |
|--------|-----------|
| Python `random` | `random.seed(42)` |
| NumPy | `np.random.seed(42)` |
| scikit-learn | `random_state=42` on every estimator |
| `PYTHONHASHSEED` | Set to `0` in `set_random_seeds()` and in the determinism check shell |

### BLAS / OpenMP thread pinning (determinism check only)

The determinism check script pins these to `1` to prevent
multi-threaded numeric reductions from reordering floating-point operations:

| Variable | Library |
|----------|---------|
| `OMP_NUM_THREADS` | OpenMP |
| `MKL_NUM_THREADS` | Intel MKL |
| `OPENBLAS_NUM_THREADS` | OpenBLAS |
| `NUMEXPR_NUM_THREADS` | NumExpr |

These are set **only** inside `scripts/determinism_check.sh`, not globally
for production runs.

### JSON serialisation

All `json.dump()` calls use `sort_keys=True` to ensure key ordering is stable
regardless of dict construction order.

### DataFrame handling

- Parquet files preserve row order from the walk-forward loop.
- Feature and regime DataFrames use DatetimeIndex with a fixed sort.
- Predictions are built chronologically in the walk-forward loop.

---

## Running the determinism check

### Locally

```bash
bash scripts/determinism_check.sh        # default ticker (PLTR)
bash scripts/determinism_check.sh TSLA   # custom ticker
```

The script will:

1. Run the pipeline twice back-to-back with the same config.
2. Validate both runs with `validate_run.py`.
3. Compare **raw** SHA-256 hashes (byte-identical check).
4. Compare **normalised** SHA-256 hashes (volatile fields stripped).
5. Cross-check the embedded `content_hash_sha256` fields.
6. Exit 0 on match (`DETERMINISM PASS`) or 1 on mismatch with a diff.

Possible outcomes per file:

| Raw | Normalised | Meaning |
|-----|------------|---------|
| match | match | Byte-identical (ideal) |
| differ | match | Only volatile metadata differs (acceptable) |
| differ | differ | **Real non-determinism — FAIL** |

### Running unit tests

```bash
python -m pytest tests/ -v --rootdir=tests
```

### In CI

The determinism check runs as a **weekly** GitHub Actions workflow
(`.github/workflows/determinism.yml`) and can also be triggered manually via
`workflow_dispatch`.

---

## Volatile key denylist

The normaliser (`determinism.py`) strips these keys during comparison.
This is the **authoritative, exhaustive** list — adding a new volatile field
requires updating this list and this document.

| Key | Why it is volatile |
|-----|-------------------|
| `timestamp` | `BaseAgent.save_output()` injects `pd.Timestamp.now()` |
| `run_timestamp` | `DashboardAgent` injects `datetime.now().isoformat()` |
| `started` | `OrchestratorAgent` per-stage wall-clock start time |
| `finished` | `OrchestratorAgent` per-stage wall-clock end time |
| `run_id` | Contains wall-clock timestamp + random suffix |
| `content_hash_sha256` | Self-referential; computed from normalised content |
| `*_path` keys | File paths embed the run-specific directory name |

Additionally:

- Floats are **not** rounded — they are preserved exactly as Python produces
  them.  If a float differs even by 1e-15 between runs, the check will catch
  it as real non-determinism.  The BLAS thread pinning (above) ensures this
  is safe.
- String values containing run-ID path patterns are replaced with a placeholder.
- Keys are sorted recursively.

### Strict mode

Running the normaliser with `--strict` (or calling `normalize(data, strict=True)`)
enables suspicious-key detection.  If a key matches a pattern like `*_timestamp`,
`*_generated_at`, or `*_created_at` but is **not** in the denylist, the normaliser
raises:

```
ValueError: New volatile key encountered: 'creation_timestamp' at $.creation_timestamp
```

This prevents new volatile fields from silently slipping through the check.

---

## When the check fails: remediation checklist

1. **New `datetime.now()` call in a compared file**
   - Add the field name to `VOLATILE_KEYS` in `determinism.py` and update this doc, OR
   - Refactor to avoid injecting live timestamps into deterministic outputs.

2. **Non-deterministic dict iteration**
   - Ensure `json.dump(..., sort_keys=True)` is used.

3. **Unseeded RNG** (new model, new sampling)
   - Pass `random_state=config.random_seed` to every estimator/sampler.

4. **DataFrame row-order change**
   - Sort the DataFrame on a stable key before writing.

5. **Float precision drift**
   - Ensure BLAS/OpenMP threads are pinned to 1 (the check script does this).
   - If a specific external field has irreducible noise, add it to
     `VOLATILE_KEYS` rather than introducing global rounding.

6. **External data changed between runs**
   - Expected if market data updated between runs.  The check is designed for
     back-to-back runs where data is cached/identical.  Re-run both immediately.

7. **New field added to a target file**
   - If deterministic → no action needed (normaliser preserves it).
   - If volatile → add to `VOLATILE_KEYS` and update this doc.
   - If suspicious → strict mode will catch it automatically.

---

## Design decisions

- Volatile fields are **kept in production outputs** (timestamps are useful
  for debugging and audit trails).  They are only stripped during the
  determinism comparison.
- `content_hash_sha256` gives users an instant visual check without running
  the full script.  It is excluded from its own computation (no circularity).
- `PYTHONHASHSEED=0` is set in the check script.  Production runs do not
  require it since Python 3.7+ dicts use insertion order, and all JSON
  writing uses `sort_keys=True`.
- Floats are **not** rounded during normalisation.  This is intentional:
  with seeded RNG and single-threaded BLAS, floats must be bit-identical.
  Any drift is a real bug.  If a future field has irreducible external
  noise, add it to `VOLATILE_KEYS` rather than introducing rounding.
