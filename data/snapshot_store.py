"""
Snapshot store for frozen data snapshots.

Provides deterministic save/load/hash of DataFrames used as pipeline input.
Ensures replay runs use exactly the same data as the original run.

The canonical hash is computed from the DataFrame's logical content
(column names, dtypes, sorted index, values) rather than parquet bytes,
because parquet metadata and library versions can cause byte-level drift.
"""

import hashlib
import os
from typing import Optional

import numpy as np
import pandas as pd

# Fixed parquet compression — never change without bumping a schema version.
_PARQUET_COMPRESSION = "snappy"

# Columns expected in OHLCV data (canonical order for hashing).
_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def snapshot_path(run_dir: str) -> str:
    """Return the canonical path for the data snapshot parquet file."""
    return os.path.join(run_dir, "DataAgent", "data_snapshot.parquet")


def snapshot_hash_path(run_dir: str) -> str:
    """Return the canonical path for the snapshot hash file."""
    return os.path.join(run_dir, "DataAgent", "snapshot_hash.txt")


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a DataFrame for deterministic storage.

    - Sort by datetime index ascending
    - Remove timezone info (naive UTC assumption)
    - Enforce float64 for OHLCV price columns, int64 for Volume
    - Drop duplicate index entries
    - NaN normalization (unify None / NaT / NaN to np.nan for floats)
    - Reset column order to canonical OHLCV order (extra columns preserved after)
    """
    df = df.copy()

    # Sort by index
    df = df.sort_index()

    # Drop duplicate index entries
    df = df[~df.index.duplicated(keep="first")]

    # Strip timezone
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Enforce dtypes for known columns
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].astype(np.float64)
    if "Volume" in df.columns:
        # Fill NaN before int64 cast (NaN not representable in int64)
        df["Volume"] = df["Volume"].fillna(0).astype(np.int64)

    # NaN normalization: unify None/NaT/NaN to np.nan for float columns
    for col in df.columns:
        if df[col].dtype == np.float64:
            df[col] = df[col].where(df[col].notna(), np.nan)

    # Canonical column order: OHLCV first, then any extras sorted
    ohlcv_present = [c for c in _OHLCV_COLUMNS if c in df.columns]
    extras = sorted(set(df.columns) - set(_OHLCV_COLUMNS))
    df = df[ohlcv_present + extras]

    return df


def compute_snapshot_hash(df: pd.DataFrame) -> str:
    """Compute a deterministic SHA-256 hash of a DataFrame's logical content.

    Hash method: canonical_df_v1
    The hash is computed from a canonical string representation:
    column names + dtypes + sorted index values (ISO format) + cell values.
    This is stable across parquet library versions and environments.

    NaN values hash as the literal string "NaN" for consistency.
    Datetime index values use isoformat() for cross-version stability.
    """
    df = normalize_df(df)

    hasher = hashlib.sha256()

    # Hash method marker (allows future versioning)
    hasher.update(b"canonical_df_v1\n")

    # Hash column names and dtypes
    col_info = "|".join(f"{c}:{df[c].dtype}" for c in df.columns)
    hasher.update(col_info.encode("utf-8"))

    # Hash index values — use isoformat for DatetimeIndex stability
    if isinstance(df.index, pd.DatetimeIndex):
        idx_str = ",".join(v.isoformat() for v in df.index)
    else:
        idx_str = ",".join(str(v) for v in df.index)
    hasher.update(idx_str.encode("utf-8"))

    # Hash cell values row by row for stability
    # NaN → "NaN" sentinel for consistent hashing across environments
    for _, row in df.iterrows():
        parts = []
        for v in row.values:
            if isinstance(v, float) and np.isnan(v):
                parts.append("NaN")
            else:
                parts.append(repr(v))
        hasher.update(",".join(parts).encode("utf-8"))

    return hasher.hexdigest()


def save_snapshot(df: pd.DataFrame, run_dir: str) -> str:
    """Normalize and save a data snapshot to the run directory.

    Returns the SHA-256 hash of the snapshot.
    """
    df = normalize_df(df)
    path = snapshot_path(run_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    df.to_parquet(path, compression=_PARQUET_COMPRESSION, engine="pyarrow")

    sha = compute_snapshot_hash(df)
    hash_path = snapshot_hash_path(run_dir)
    with open(hash_path, "w") as f:
        f.write(sha + "\n")

    return sha


def load_snapshot(run_dir: str) -> pd.DataFrame:
    """Load a data snapshot from the run directory.

    Raises FileNotFoundError if the snapshot does not exist.
    """
    path = snapshot_path(run_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data snapshot not found: {path}")

    df = pd.read_parquet(path, engine="pyarrow")
    return normalize_df(df)


def verify_snapshot_hash(run_dir: str) -> bool:
    """Verify that the stored snapshot hash matches the recomputed hash.

    Returns True if hashes match, False otherwise.
    Raises FileNotFoundError if snapshot or hash file is missing.
    """
    path = snapshot_path(run_dir)
    hash_path_val = snapshot_hash_path(run_dir)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Data snapshot not found: {path}")
    if not os.path.exists(hash_path_val):
        raise FileNotFoundError(f"Snapshot hash not found: {hash_path_val}")

    df = pd.read_parquet(path, engine="pyarrow")
    recomputed = compute_snapshot_hash(df)

    with open(hash_path_val) as f:
        stored = f.read().strip()

    return stored == recomputed


def snapshot_metadata(df: pd.DataFrame) -> dict:
    """Return metadata dict for embedding in summary.json."""
    df = normalize_df(df)
    return {
        "data_snapshot_rows": len(df),
        "data_snapshot_start": str(df.index.min().date()) if len(df) > 0 else None,
        "data_snapshot_end": str(df.index.max().date()) if len(df) > 0 else None,
        "data_snapshot_hash_method": "canonical_df_v1",
        "data_snapshot_sha256": compute_snapshot_hash(df),
    }


def resolve_replay_path(replay_from: str) -> str:
    """Resolve a --replay-from argument to an actual parquet path.

    Accepts either:
      - A run directory (returns <dir>/DataAgent/data_snapshot.parquet)
      - A direct .parquet file path

    Raises FileNotFoundError with a clear message if the file is missing.
    """
    if replay_from.endswith(".parquet"):
        if not os.path.exists(replay_from):
            raise FileNotFoundError(
                f"Replay parquet not found: {replay_from}"
            )
        return replay_from

    # Treat as run directory
    path = snapshot_path(replay_from)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Data snapshot not found in replay directory: {path}\n"
            f"  (looked in: {replay_from})"
        )
    return path
