#!/usr/bin/env python3
"""
normalize_json.py - Produce a canonical JSON form for determinism comparison.

Usage:
    python scripts/normalize_json.py input.json [output.json]
    python scripts/normalize_json.py --strict input.json [output.json]

If output.json is omitted, prints to stdout.
With --strict, raises an error if an unlisted suspicious key is encountered.

Normalisation logic lives in determinism.py (project root) — this script
is a thin CLI wrapper.
"""

import os
import sys

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from determinism import canonical_json


def normalize_file(input_path: str, output_path: str | None = None,
                   *, strict: bool = False) -> str:
    """Load, normalise, and write (or return) canonical JSON."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    canonical = canonical_json(data, strict=strict)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(canonical)
            f.write("\n")
    return canonical


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv

    if len(args) < 1:
        print(f"Usage: {sys.argv[0]} [--strict] input.json [output.json]",
              file=sys.stderr)
        sys.exit(1)

    input_path = args[0]
    output_path = args[1] if len(args) > 1 else None

    canonical = normalize_file(input_path, output_path, strict=strict)

    if output_path is None:
        print(canonical)


if __name__ == "__main__":
    main()
