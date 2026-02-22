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
