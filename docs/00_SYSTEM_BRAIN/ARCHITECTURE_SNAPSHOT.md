# Architecture Snapshot

This is a snapshot of the current system shape. Keep it updated after major merges.

## Pipeline Order (Current)

1. DataAgent
2. FeatureAgent
3. RegimeAgent
4. VolatilityRegimeAgent (if present)
5. EventModelAgent (if present)
6. StrategyAgent
7. BacktestAgent
8. RobustnessAgent
9. DecisionRiskAgent
10. DashboardAgent
11. MemoryLearningAgent (if present)

## Run Directory Shape (High Level)

* runs/<TICKER>/<RUN_ID>/

  * agent output folders
  * summary.json / status.txt (as implemented)
  * final_report.html (as implemented)

## Validation

* validate_run.py must pass for any "SUCCESS" run.
* Parity/replay checks (if present) compare canonical artifacts across runs.
