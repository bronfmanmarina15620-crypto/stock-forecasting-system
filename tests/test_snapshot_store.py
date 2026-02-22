"""
Tests for data/snapshot_store.py — snapshot hashing stability,
normalization, save/load round-trip, and replay correctness.
"""

import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from data.snapshot_store import (
    compute_snapshot_hash,
    load_snapshot,
    normalize_df,
    resolve_replay_path,
    save_snapshot,
    snapshot_metadata,
    snapshot_path,
    snapshot_hash_path,
    verify_snapshot_hash,
)


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """Create a realistic OHLCV DataFrame for testing."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n, freq="B")
    close = 100.0 + np.cumsum(rng.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "Open": close + rng.randn(n) * 0.1,
            "High": close + abs(rng.randn(n) * 0.5),
            "Low": close - abs(rng.randn(n) * 0.5),
            "Close": close,
            "Volume": rng.randint(1_000_000, 10_000_000, size=n),
        },
        index=dates,
    )
    df.index.name = None
    return df


class TestNormalizeDf:
    """Tests for normalize_df."""

    def test_sort_by_index(self):
        df = _make_ohlcv()
        shuffled = df.sample(frac=1, random_state=99)
        assert not shuffled.index.is_monotonic_increasing
        normalized = normalize_df(shuffled)
        assert normalized.index.is_monotonic_increasing

    def test_strip_timezone(self):
        df = _make_ohlcv()
        df.index = df.index.tz_localize("UTC")
        normalized = normalize_df(df)
        assert normalized.index.tz is None

    def test_enforce_dtypes(self):
        df = _make_ohlcv()
        df["Close"] = df["Close"].astype(np.float32)
        df["Volume"] = df["Volume"].astype(np.float64)
        normalized = normalize_df(df)
        assert normalized["Close"].dtype == np.float64
        assert normalized["Volume"].dtype == np.int64

    def test_drop_duplicates(self):
        df = _make_ohlcv()
        dup = pd.concat([df.iloc[:5], df.iloc[:5]])
        normalized = normalize_df(dup)
        assert not normalized.index.duplicated().any()
        assert len(normalized) <= len(df)

    def test_canonical_column_order(self):
        df = _make_ohlcv()
        df["ExtraCol"] = 1.0
        reordered = df[["Volume", "ExtraCol", "Close", "Low", "High", "Open"]]
        normalized = normalize_df(reordered)
        expected = ["Open", "High", "Low", "Close", "Volume", "ExtraCol"]
        assert list(normalized.columns) == expected


class TestSnapshotHash:
    """Tests for compute_snapshot_hash stability."""

    def test_same_df_same_hash(self):
        df = _make_ohlcv()
        h1 = compute_snapshot_hash(df)
        h2 = compute_snapshot_hash(df)
        assert h1 == h2

    def test_shuffled_input_same_hash(self):
        df = _make_ohlcv()
        shuffled = df.sample(frac=1, random_state=7)
        h_original = compute_snapshot_hash(df)
        h_shuffled = compute_snapshot_hash(shuffled)
        assert h_original == h_shuffled

    def test_tz_aware_same_hash(self):
        df = _make_ohlcv()
        df_tz = df.copy()
        df_tz.index = df_tz.index.tz_localize("UTC")
        h_naive = compute_snapshot_hash(df)
        h_tz = compute_snapshot_hash(df_tz)
        assert h_naive == h_tz

    def test_different_data_different_hash(self):
        df1 = _make_ohlcv(seed=42)
        df2 = _make_ohlcv(seed=99)
        assert compute_snapshot_hash(df1) != compute_snapshot_hash(df2)

    def test_hash_is_sha256_hex(self):
        h = compute_snapshot_hash(_make_ohlcv())
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_column_reorder_same_hash(self):
        """Shuffled column order must produce the same hash after normalization."""
        df = _make_ohlcv()
        reordered = df[["Volume", "Close", "Low", "High", "Open"]]
        assert compute_snapshot_hash(df) == compute_snapshot_hash(reordered)

    def test_hash_stable_across_save_load(self, tmp_path):
        """Hash computed before save must equal hash after load."""
        df = _make_ohlcv()
        h_before = compute_snapshot_hash(df)
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)
        save_snapshot(df, run_dir)
        loaded = load_snapshot(run_dir)
        h_after = compute_snapshot_hash(loaded)
        assert h_before == h_after


class TestSaveLoadSnapshot:
    """Tests for save_snapshot / load_snapshot round-trip."""

    def test_round_trip(self, tmp_path):
        df = _make_ohlcv()
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)

        sha = save_snapshot(df, run_dir)
        loaded = load_snapshot(run_dir)

        assert len(loaded) == len(normalize_df(df))
        assert compute_snapshot_hash(loaded) == sha

    def test_snapshot_hash_file_created(self, tmp_path):
        df = _make_ohlcv()
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)

        sha = save_snapshot(df, run_dir)
        hash_path = snapshot_hash_path(run_dir)
        assert os.path.exists(hash_path)

        with open(hash_path) as f:
            stored = f.read().strip()
        assert stored == sha

    def test_verify_hash_passes(self, tmp_path):
        df = _make_ohlcv()
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)

        save_snapshot(df, run_dir)
        assert verify_snapshot_hash(run_dir) is True

    def test_verify_hash_detects_tampering(self, tmp_path):
        df = _make_ohlcv()
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)

        save_snapshot(df, run_dir)
        # Tamper with hash file
        hash_path = snapshot_hash_path(run_dir)
        with open(hash_path, "w") as f:
            f.write("0" * 64 + "\n")
        assert verify_snapshot_hash(run_dir) is False

    def test_load_missing_snapshot_raises(self, tmp_path):
        run_dir = str(tmp_path / "runs" / "PLTR" / "no_snapshot")
        with pytest.raises(FileNotFoundError):
            load_snapshot(run_dir)


class TestSnapshotMetadata:
    """Tests for snapshot_metadata."""

    def test_metadata_keys(self):
        df = _make_ohlcv()
        meta = snapshot_metadata(df)
        assert "data_snapshot_rows" in meta
        assert "data_snapshot_start" in meta
        assert "data_snapshot_end" in meta
        assert "data_snapshot_sha256" in meta

    def test_metadata_values(self):
        df = _make_ohlcv(n=100)
        meta = snapshot_metadata(df)
        assert meta["data_snapshot_rows"] == 100
        assert meta["data_snapshot_sha256"] == compute_snapshot_hash(df)

    def test_metadata_hash_method(self):
        df = _make_ohlcv()
        meta = snapshot_metadata(df)
        assert meta["data_snapshot_hash_method"] == "canonical_df_v1"


class TestNaNNormalization:
    """Tests for NaN handling in normalization and hashing."""

    def test_nan_in_float_columns_stable_hash(self):
        df = _make_ohlcv(n=10)
        df.iloc[3, df.columns.get_loc("Close")] = np.nan
        h1 = compute_snapshot_hash(df)
        h2 = compute_snapshot_hash(df.copy())
        assert h1 == h2

    def test_none_vs_nan_same_hash(self):
        df1 = _make_ohlcv(n=10)
        df1.iloc[3, df1.columns.get_loc("Close")] = np.nan
        df2 = _make_ohlcv(n=10)
        df2.iloc[3, df2.columns.get_loc("Close")] = None
        # After normalization both should hash identically
        assert compute_snapshot_hash(df1) == compute_snapshot_hash(df2)

    def test_volume_nan_becomes_zero(self):
        df = _make_ohlcv(n=10)
        df.iloc[3, df.columns.get_loc("Volume")] = np.nan
        normalized = normalize_df(df)
        assert normalized.iloc[3]["Volume"] == 0
        assert normalized["Volume"].dtype == np.int64


class TestResolveReplayPath:
    """Tests for resolve_replay_path — accepts dir or .parquet."""

    def test_resolve_dir(self, tmp_path):
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)
        df = _make_ohlcv(n=10)
        save_snapshot(df, run_dir)
        resolved = resolve_replay_path(run_dir)
        assert resolved.endswith("data_snapshot.parquet")
        assert os.path.exists(resolved)

    def test_resolve_parquet_path(self, tmp_path):
        run_dir = str(tmp_path / "runs" / "PLTR" / "test_run")
        os.makedirs(os.path.join(run_dir, "DataAgent"), exist_ok=True)
        df = _make_ohlcv(n=10)
        save_snapshot(df, run_dir)
        parquet_path = snapshot_path(run_dir)
        resolved = resolve_replay_path(parquet_path)
        assert resolved == parquet_path

    def test_resolve_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Data snapshot not found"):
            resolve_replay_path(str(tmp_path / "nonexistent"))

    def test_resolve_missing_parquet_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Replay parquet not found"):
            resolve_replay_path(str(tmp_path / "nonexistent.parquet"))
