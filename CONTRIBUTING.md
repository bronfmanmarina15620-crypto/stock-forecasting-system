# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
```

## Run Tests

```bash
python -m pytest tests/ -q
```

## Run Smoke Test

```bash
bash scripts/ci_smoke_run.sh PLTR
```

## Workflow

1. Create a feature branch from `main`
2. Make your changes
3. Open a PR against `main`
4. Wait for CI checks (`test` + `smoke-run`) to pass

## PR Checklist

- [ ] `python -m pytest tests/ -q` passes
- [ ] `bash scripts/ci_smoke_run.sh PLTR` passes
- [ ] No secrets or credentials committed
- [ ] Deterministic pipeline outputs preserved (content hashes must match)
- [ ] Documentation updated if behavior changed
