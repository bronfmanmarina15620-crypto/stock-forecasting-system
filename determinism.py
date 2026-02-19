"""
Determinism utilities — single source of truth for canonical JSON
normalisation, content hashing, and volatile-key management.

Imported by:
  - agents (to embed content_hash_sha256 in outputs)
  - scripts/normalize_json.py (for the determinism-check comparison)
  - tests/test_normalize_json.py

Numeric policy
--------------
Floats are preserved exactly as Python produces them — NO rounding is applied.
If the pipeline is truly deterministic (seeded RNG, pinned thread counts),
floats will be bit-identical between runs.  If they differ even by 1e-15,
that is a REAL non-determinism bug and the check will catch it.

If a future field is known to have acceptable noise (e.g., from an external
API), add it to VOLATILE_KEYS rather than introducing global rounding.
"""

import hashlib
import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Configuration (authoritative denylist — keep alphabetically sorted)
# ---------------------------------------------------------------------------

#: The content-hash field is a *structural* exclusion: it is always stripped
#: because it is self-referential (computed FROM the normalised content).
#: This is a dedicated rule, not part of the volatile-metadata denylist.
CONTENT_HASH_KEY = "content_hash_sha256"

#: Keys stripped during normalisation.  Every entry MUST have a comment
#: explaining *why* it is volatile.  To add a new entry you MUST also update
#: docs/REPRODUCIBILITY.md — the determinism check will catch un-listed
#: volatile keys via the suspicious-pattern detector below.
VOLATILE_KEYS: frozenset[str] = frozenset({
    "finished",             # OrchestratorAgent per-stage wall-clock end time
    "run_id",               # contains wall-clock timestamp + random suffix
    "run_timestamp",        # DashboardAgent injects datetime.now().isoformat()
    "started",              # OrchestratorAgent per-stage wall-clock start time
    "timestamp",            # BaseAgent.save_output() injects pd.Timestamp.now()
})

#: Suffix for keys whose *values* are filesystem paths containing the run ID.
PATH_KEY_SUFFIX = "_path"

#: Regex matching run-ID-bearing path segments in string values.
RUN_ID_PATH_RE = re.compile(
    r"runs/[A-Z]+/\d{8}_\d{6}_[a-z0-9]{6}"
)

#: Patterns that look like volatile keys.  If a key matches one of these
#: patterns AND is not in VOLATILE_KEYS, strict mode raises an error so
#: the developer is forced to either add it to the denylist or confirm it
#: is genuinely deterministic.
_SUSPICIOUS_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?:^|_)timestamp(?:$|_)", re.IGNORECASE),
    re.compile(r"(?:^|_)generated_at(?:$|_)", re.IGNORECASE),
    re.compile(r"(?:^|_)created_at(?:$|_)", re.IGNORECASE),
    re.compile(r"^run_id$", re.IGNORECASE),
)

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def normalize(obj: Any, *, strict: bool = False, _path: str = "$") -> Any:
    """Recursively normalise a JSON-compatible object.

    Parameters
    ----------
    obj : Any
        JSON-compatible Python object (dict, list, str, int, float, bool, None).
    strict : bool
        When True, raise ``ValueError`` if a key looks volatile (matches a
        suspicious pattern) but is not in the explicit denylist.  This
        prevents new timestamps from silently slipping through.
    _path : str
        Internal — JSON-pointer breadcrumb for error messages.

    Returns
    -------
    Normalised copy with volatile keys removed and run-ID path strings
    replaced.  Floats are preserved exactly (no rounding).
    """
    if isinstance(obj, dict):
        result: dict = {}
        for key in sorted(obj.keys()):
            # 1. Content hash → always strip (structural, self-referential)
            if key == CONTENT_HASH_KEY:
                continue
            # 2. Exact denylist match → strip volatile metadata
            if key in VOLATILE_KEYS:
                continue
            # 3. Path-valued keys (suffix rule: *_path) → strip
            if key.endswith(PATH_KEY_SUFFIX):
                continue
            # 4. Strict: detect suspicious but unlisted keys
            if strict:
                for pat in _SUSPICIOUS_PATTERNS:
                    if pat.search(key) and key not in VOLATILE_KEYS:
                        raise ValueError(
                            f"New volatile key encountered: '{key}' "
                            f"at {_path}.{key}  — add it to VOLATILE_KEYS "
                            f"in determinism.py or confirm it is deterministic"
                        )
            result[key] = normalize(obj[key], strict=strict, _path=f"{_path}.{key}")
        return result

    if isinstance(obj, list):
        return [
            normalize(item, strict=strict, _path=f"{_path}[{i}]")
            for i, item in enumerate(obj)
        ]

    if isinstance(obj, str):
        # Replace strings containing run-ID paths with a stable placeholder
        if RUN_ID_PATH_RE.search(obj):
            return "__PATH_REMOVED__"
        return obj

    # int, float, bool, None pass through unchanged
    return obj


def canonical_json(obj: Any, *, strict: bool = False) -> str:
    """Return a deterministic JSON string of *obj* after normalisation."""
    normalised = normalize(obj, strict=strict)
    return json.dumps(normalised, indent=2, sort_keys=True, ensure_ascii=False)


def content_hash_sha256(obj: Any) -> str:
    """Compute a SHA-256 hex digest of the canonical (normalised) JSON form.

    The hash is stable across runs when the deterministic content is the
    same, even if volatile metadata (timestamps, paths) differs.

    The ``content_hash_sha256`` key is stripped by a dedicated structural
    rule (``CONTENT_HASH_KEY``) — not via the volatile denylist — so it
    is always excluded from its own computation (no circularity).
    """
    canon = canonical_json(obj)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
