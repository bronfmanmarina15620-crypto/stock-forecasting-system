# System Invariants

These are non-negotiable. Any change that violates these requires an explicit PR, documentation update, and validation.

## Determinism

* Same input data + same config + same code version => same outputs and decisions.
* JSON artifacts must be canonical (sorted keys; stable ordering) where applicable.
* No hidden randomness. Any randomness must be seeded and documented.

## Strategy Scope

* Single trading strategy only: MA150 + ATR.
* No additional strategies, ensembles, or ML-driven entry/exit logic unless explicitly planned and documented.

## No Implicit Fallbacks

* No silent fallback for missing data, missing artifacts, or missing upstream outputs.
* Fail fast with explicit error when required inputs are absent.

## Artifact Integrity

* Required artifacts must be produced for every run, and validated by `validate_run.py`.
* Any artifact hashing/integrity checks must be stable and reproducible.

## Pipeline Contract

* Agent pipeline order must remain stable unless explicitly changed and documented.
* Each agent reads only its declared inputs and writes only its declared outputs.

## Nightly/Automation Safety

* Nightly runs must not mutate repo state.
* Notifications must reflect true run status (success/failure) based on validated artifacts.

## Change Control

* Any change to contracts/invariants must:

  1. update this file
  2. update relevant contract docs
  3. include validation steps and acceptance criteria

* Documentation must not hard-code implementation details that are likely to evolve (agent counts, artifact lists, parameter values) unless they are contractual. Reference source files (e.g., `agents/orchestrator_agent.py`, `config/strategy.yaml`) as the source of truth.
