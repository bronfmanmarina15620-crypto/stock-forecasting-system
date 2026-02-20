## What changed

-

## Why

-

## How to test

```bash
python -m pytest tests/ -q
bash scripts/ci_smoke_run.sh PLTR
```

## Checklist

- [ ] `test` CI job passes
- [ ] `smoke-run` CI job passes
- [ ] No secrets or credentials committed
- [ ] Deterministic outputs preserved (content hashes match)
- [ ] Docs updated if behavior changed
