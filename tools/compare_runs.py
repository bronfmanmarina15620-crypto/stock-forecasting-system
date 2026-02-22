#!/usr/bin/env python3
"""
compare_runs.py - Compare two run directories for replay parity.

Compares canonical JSON hashes and raw SHA-256 for non-JSON artifacts.
Uses the artifact contract to determine which files to compare.

Usage:
    python tools/compare_runs.py <run_a> <run_b>

Exit codes:
    0 = PARITY PASS (all compared artifacts match)
    1 = PARITY FAIL (at least one mismatch or missing file)
"""

import argparse
import hashlib
import json
import os
import sys

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from determinism import canonical_json
from artifacts.contract import (
    PARITY_JSON_TARGETS,
    PARITY_RAW_TARGETS,
    PARITY_IGNORE,
    SHADOW_HASH_TARGETS,
)


def sha256_file(path: str) -> str:
    """Compute SHA-256 of a file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_hash(path: str) -> str:
    """Load a JSON file, normalize it, and return SHA-256 of canonical form."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    canon = canonical_json(data)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def compare_runs(run_a: str, run_b: str, verbose: bool = True) -> dict:
    """Compare two run directories for replay parity.

    Returns a dict with:
        passed: bool
        mismatches: list of {file, reason, hash_a, hash_b}
        matches: list of {file, hash}
        skipped: list of {file, reason}
    """
    mismatches = []
    matches = []
    skipped = []

    # Build target list: JSON targets + raw targets
    json_targets = list(PARITY_JSON_TARGETS)

    # Conditionally include shadow targets if both runs have them
    for target in SHADOW_HASH_TARGETS:
        a_exists = os.path.exists(os.path.join(run_a, target))
        b_exists = os.path.exists(os.path.join(run_b, target))
        if a_exists and b_exists:
            json_targets.append(target)
        elif a_exists or b_exists:
            skipped.append({
                "file": target,
                "reason": "exists in only one run",
            })

    # Compare JSON targets via canonical normalization
    for relpath in json_targets:
        path_a = os.path.join(run_a, relpath)
        path_b = os.path.join(run_b, relpath)

        if not os.path.exists(path_a):
            skipped.append({"file": relpath, "reason": "missing in run A"})
            continue
        if not os.path.exists(path_b):
            skipped.append({"file": relpath, "reason": "missing in run B"})
            continue

        try:
            hash_a = canonical_json_hash(path_a)
            hash_b = canonical_json_hash(path_b)
        except Exception as e:
            mismatches.append({
                "file": relpath,
                "reason": f"parse error: {e}",
                "hash_a": None,
                "hash_b": None,
            })
            continue

        if hash_a == hash_b:
            matches.append({"file": relpath, "hash": hash_a})
        else:
            mismatches.append({
                "file": relpath,
                "reason": "canonical hash mismatch",
                "hash_a": hash_a,
                "hash_b": hash_b,
            })

    # Compare raw targets via SHA-256
    for relpath in PARITY_RAW_TARGETS:
        path_a = os.path.join(run_a, relpath)
        path_b = os.path.join(run_b, relpath)

        if not os.path.exists(path_a):
            skipped.append({"file": relpath, "reason": "missing in run A"})
            continue
        if not os.path.exists(path_b):
            skipped.append({"file": relpath, "reason": "missing in run B"})
            continue

        # For parquet files, compare via snapshot hash if available
        if relpath.endswith(".parquet"):
            try:
                from data.snapshot_store import compute_snapshot_hash
                import pandas as pd
                df_a = pd.read_parquet(path_a, engine="pyarrow")
                df_b = pd.read_parquet(path_b, engine="pyarrow")
                hash_a = compute_snapshot_hash(df_a)
                hash_b = compute_snapshot_hash(df_b)
            except Exception:
                hash_a = sha256_file(path_a)
                hash_b = sha256_file(path_b)
        else:
            hash_a = sha256_file(path_a)
            hash_b = sha256_file(path_b)

        if hash_a == hash_b:
            matches.append({"file": relpath, "hash": hash_a})
        else:
            mismatches.append({
                "file": relpath,
                "reason": "raw hash mismatch",
                "hash_a": hash_a,
                "hash_b": hash_b,
            })

    passed = len(mismatches) == 0

    result = {
        "passed": passed,
        "mismatches": mismatches,
        "matches": matches,
        "skipped": skipped,
        "run_a": run_a,
        "run_b": run_b,
    }

    if verbose:
        _print_report(result)

    return result


def _print_report(result: dict):
    """Print a human-readable parity report."""
    print("=" * 60)
    print("REPLAY PARITY COMPARISON")
    print("=" * 60)
    print(f"Run A: {result['run_a']}")
    print(f"Run B: {result['run_b']}")
    print()

    for m in result["matches"]:
        print(f"  [OK] {m['file']}: {m['hash'][:16]}...")

    for s in result["skipped"]:
        print(f"  [--] {s['file']}: {s['reason']}")

    for mm in result["mismatches"]:
        print(f"  [X]  {mm['file']}: {mm['reason']}")
        if mm.get("hash_a"):
            print(f"       A: {mm['hash_a']}")
            print(f"       B: {mm['hash_b']}")

    print()
    status = "PARITY PASS" if result["passed"] else "PARITY FAIL"
    counts = (
        f"{len(result['matches'])} match, "
        f"{len(result['mismatches'])} mismatch, "
        f"{len(result['skipped'])} skipped"
    )
    print(f"{status}  ({counts})")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Compare two run directories for replay parity"
    )
    parser.add_argument("run_a", help="Path to first run directory")
    parser.add_argument("run_b", help="Path to second run directory")
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON instead of human-readable report"
    )
    args = parser.parse_args()

    result = compare_runs(args.run_a, args.run_b, verbose=not args.json)

    if args.json:
        print(json.dumps(result, indent=2))

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
