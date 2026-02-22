# Context Handoff (Paste into new Claude Code chat)

PROJECT: stock-forecasting-system

SOURCE OF TRUTH DOCS (read first)

* docs/00_SYSTEM_BRAIN/SYSTEM_INVARIANTS.md
* docs/00_SYSTEM_BRAIN/AGENT_CONTRACTS.md
* docs/00_SYSTEM_BRAIN/ARCHITECTURE_SNAPSHOT.md
* docs/OPERATOR_MAP.md
* docs/ARCHITECTURE.md

CURRENT PRINCIPLES

* Deterministic runs only.
* Single strategy: MA150 + ATR.
* No implicit fallbacks; fail fast on missing required inputs/artifacts.
* Validation and artifact integrity are required before reporting SUCCESS.

WORK STYLE

* One goal per chat.
* Minimal diffs.
* Update docs when contracts change.
* Provide exact commands for verification.

## Minimal Handoffs (Copy/Paste)

### STRUCTURAL (pipeline, contracts, strategy, artifacts, validation)

```
PROJECT: stock-forecasting-system
Read docs/00_SYSTEM_BRAIN/ first (SYSTEM_INVARIANTS, AGENT_CONTRACTS, ARCHITECTURE_SNAPSHOT, STRATEGY_CONTRACT_MA150_ATR).
This task changes pipeline behavior, agent contracts, or validated artifacts.
Classify changes as contractual vs optional per AGENT_CONTRACTS.md.
Update System Brain docs in the same PR if any contract changes.
Run: python -m pytest tests/ -q && python validate_run.py --run <RUN_DIR>
```

### NON-STRUCTURAL (docs-only, refactors, no behavior change)

```
PROJECT: stock-forecasting-system
Read docs/00_SYSTEM_BRAIN/SYSTEM_INVARIANTS.md first.
This task must NOT change runtime behavior, pipeline order, or validated artifacts.
Keep diffs minimal. No code/config/workflow changes unless explicitly scoped.
```
