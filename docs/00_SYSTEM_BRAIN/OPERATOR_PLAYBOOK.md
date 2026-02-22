# Operator Playbook

## Local Single Run

1. Run:

   * `python run.py --ticker PLTR`
2. Validate:

   * `python validate_run.py --run runs/PLTR/<RUN_ID>`

## Shadow Mode

* `python run.py --ticker PLTR --mode shadow`
* Inserts ShadowMonitorAgent before DashboardAgent for monitoring-only metrics.

## Definition of Success

* `run_summary.json` shows `status: SUCCESS`.
* `validate_run.py` exits with code 0.
* `final_report.html` and `final_report.json` exist in the run directory.
* All required artifacts exist per `validate_run.py` REQUIRED_ARTIFACTS.
* All `content_hash_sha256` integrity checks pass.
