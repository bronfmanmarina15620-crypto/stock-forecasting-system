# Operator Playbook

## Local Single Run

1. Run:

   * `python run.py --ticker PLTR`
2. Validate:

   * `python validate_run.py --run runs/PLTR/<RUN_ID>`

## Shadow Mode

* `python run.py --ticker PLTR --mode shadow`
* Inserts ShadowMonitorAgent before DashboardAgent for monitoring-only metrics.

## Edge Validation

Edge validation is a **hard gate** — a run cannot be SUCCESS if edge fails.

1. **run.py** runs edge validation *before* writing final status. If edge fails, `status.txt` = FAILED and the program exits non-zero.
2. **validate_run.py** edge gates step checks edge gates and propagates the edge exit code.

Exit code semantics (consistent across `run.py`, `validate_run.py`, `tools/edge_validate.py`):
* **0** = edge PASS — all gates satisfied, no kill-switch.
* **1** = edge computed but gates FAIL — metrics below thresholds or kill-switch triggered.
* **2** = missing or invalid artifacts — edge cannot be computed.

Standalone usage:
* `python tools/edge_validate.py --run runs/PLTR/<RUN_ID>`
* Checks: trade count, expectancy, profit factor, max drawdown in R, rolling stability, walk-forward stability, regime contribution, kill-switch conditions.
* Config: `config/edge.yaml` (thresholds). Contract: `EDGE_DEFINITION.md`.

### Diagnosing edge failures

On any edge failure, `run.py` still writes `edge_summary.json` and `edge_report.txt` for diagnostics:
* **exit_code 1:** Open `edge_report.txt` for the full gate-by-gate breakdown. Check which metric(s) failed and whether the kill-switch triggered.
* **exit_code 2:** Open `edge_summary.json` and inspect the `"error"` field. Common causes: missing `trades.parquet`, missing RobustnessAgent artifacts, or `trades.parquet` lacking the `r_multiple` column.

CI/Nightly: Telegram notifications include edge status (PASS/FAIL, N, E, PF, MDD_R).

## Definition of Success

* `run_summary.json` shows `status: SUCCESS`.
* `validate_run.py` exits with code 0.
* `final_report.html` and `final_report.json` exist in the run directory.
* All required artifacts exist per `validate_run.py` REQUIRED_ARTIFACTS.
* All `content_hash_sha256` integrity checks pass.
* `validate_run.py` is the authoritative gate for required artifacts. Extra artifacts may appear in the run directory; do not treat them as failures unless `validate_run.py` fails.
* Some validations are conditional (e.g., DriftAgent, ShadowMonitorAgent) and are only required when the corresponding agent folder exists for that run mode.

---

## Approved Commands

These commands are supported and exist in the repository:

| Command | Purpose | Success signal |
|---------|---------|----------------|
| `python run.py --ticker <TICKER>` | Run the pipeline (standard mode) | Exit 0; artifacts in `runs/<TICKER>/<RUN_ID>/` |
| `python run.py --ticker <TICKER> --mode shadow` | Run the pipeline (shadow/monitoring mode) | Exit 0; artifacts in `runs/<TICKER>/<RUN_ID>/` |
| `python validate_run.py --run <RUN_PATH>` | Validate a completed run | Exit 0 = PASS, 1 = FAIL, 2 = edge artifacts missing |
| `python tools/edge_validate.py --run <RUN_PATH>` | Standalone edge gate validation | Exit 0 = PASS, 1 = FAIL, 2 = missing artifacts |
| `python -m pytest tests/ -q` | Run unit tests | Exit 0; summary line shows all passed |
| `bash scripts/determinism_check.sh [TICKER]` | Determinism verification (two back-to-back runs) | Exit 0 = DETERMINISM PASS |
| `bash scripts/smoke_test_10_runs.sh` | 10-run stability gate | Exit 0 |
| `bash scripts/daily_run.sh` | Daily pipeline + validation | Exit 0 |

GitHub Actions workflows: `nightly_pltr.yml` (standard), `nightly_pltr_shadow.yml` (shadow mode).

## Optional Tooling (present in repo)

| Tool | Path | Purpose |
|------|------|---------|
| `scripts/determinism_compare_runs.sh` | Present in repo | Compare two existing runs for determinism |
| `tools/edge_calibrate.py` | Present in repo | Recalibrate edge thresholds from historical runs |
