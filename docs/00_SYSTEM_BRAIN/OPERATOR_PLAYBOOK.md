# Operator Playbook

## Local Single Run

1. Run:

   * `python run.py --ticker PLTR`
2. Validate:

   * `python validate_run.py --run runs/PLTR/<RUN_ID>`

## Replay / Parity (if implemented)

* Compare two runs:

  * `python tools/compare_runs.py --run-a <A> --run-b <B>`
* Or:

  * `python validate_run.py --run <REPLAY> --compare-to <ORIGINAL>`

## Definition of Success

* Run completes with SUCCESS status output (as implemented).
* validate_run.py passes.
* final_report.html exists.
* Required artifacts exist.
