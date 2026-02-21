# Phase 7: Shadow Mode — Merge Note

## What shipped

- `ShadowMonitorAgent` — monitoring-only agent producing `shadow_metrics.json` and `shadow_summary.json` with `content_hash_sha256` integrity
- `--mode shadow` CLI flag on `run.py`; default remains `backtest` (zero regression)
- Append-only JSONL history per ticker for rolling ENTER frequency (`enter_rolling_20`)
- Nightly GitHub Action (`.github/workflows/nightly_pltr_shadow.yml`) with Telegram notifications
- Conditional integration: `validate_run.py` and `determinism_check.sh` include shadow artifacts only when present
- Dashboard `final_report.json` gains optional `shadow` section in shadow mode

## Safety guarantees

- No trading, no execution, no broker calls — ShadowMonitorAgent is read-only
- `timestamp_utc` is deterministic (derived from `asof_date`, not wall-clock)
- `content_hash_sha256` covers all non-structural fields; validated by `validate_run.py` step 8
- Orchestrator uses a local copy of the agent list — no mutation across calls
- Backtest mode produces zero shadow artifacts; validation does not require them
- 210 tests pass, including 4 dedicated shadow determinism invariant tests

## How to run

```bash
python run.py --ticker PLTR --mode shadow
python validate_run.py --run runs/PLTR/<RUN_ID>
```

## Nightly workflow

- Cron: `0 21 * * *` (21:00 UTC = 23:00 Israel winter / 00:00 Israel summer)
- Success: `✅ SHADOW OK | PLTR | RUN_ID=... | DECISION=... | REGIME=...`
- Failure: `❌ SHADOW FAIL | PLTR | RUN_ID=... | STEP=RUN|VALIDATE|UNKNOWN`
- RUN_ID is always captured via `PIPESTATUS`, even on pipeline failure

## Known limitations

- Shadow history JSONL is stateful (append-only); `enter_rolling_20` is excluded from determinism comparison targets
- Cron fires at a fixed UTC hour; Israel local time shifts by 1 hour across DST transitions
- `--strict` normalization will flag `timestamp_utc` as suspicious (expected; field is deterministic, not in `VOLATILE_KEYS`)
- Shadow mode does not produce `predictions_oos.parquet` or `sanity_tests.json` (ML artifacts are backtest-only)
