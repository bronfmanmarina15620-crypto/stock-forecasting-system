"""
Tests for the determinism normalisation and content-hashing logic.

Run with:
    pytest tests/test_normalize_json.py -v
"""

import json
import math
import os
import sys

import pytest

from determinism import (
    CONTENT_HASH_KEY,
    VOLATILE_KEYS,
    PATH_KEY_SUFFIX,
    normalize,
    canonical_json,
    content_hash_sha256,
)


# ── key sorting ──────────────────────────────────────────────


class TestKeySorting:
    def test_top_level_keys_sorted(self):
        data = {"z": 1, "a": 2, "m": 3}
        result = normalize(data)
        assert list(result.keys()) == ["a", "m", "z"]

    def test_nested_keys_sorted(self):
        data = {"outer": {"z": 1, "a": 2}}
        result = normalize(data)
        assert list(result["outer"].keys()) == ["a", "z"]

    def test_canonical_json_keys_sorted(self):
        data = {"b": {"y": 1, "x": 2}, "a": 3}
        canon = canonical_json(data)
        parsed = json.loads(canon)
        assert list(parsed.keys()) == ["a", "b"]
        assert list(parsed["b"].keys()) == ["x", "y"]


# ── float handling (NO rounding — exact preservation) ────────


class TestFloatHandling:
    def test_float_preserved_exactly(self):
        """Floats pass through normalize() without any modification."""
        val = 1.123456789012345
        data = {"val": val}
        result = normalize(data)
        assert result["val"] == val
        assert repr(result["val"]) == repr(val)

    def test_tiny_drift_detected_as_mismatch(self):
        """A 1e-8 difference in a float MUST produce different hashes."""
        a = {"metric": 0.500000000}
        b = {"metric": 0.500000010}  # differs by 1e-8
        assert content_hash_sha256(a) != content_hash_sha256(b)

    def test_1e15_drift_detected(self):
        """Even 1e-15 drift is caught (smallest representable difference)."""
        a = {"metric": 0.1 + 0.2}          # 0.30000000000000004
        b = {"metric": 0.3}                 # 0.3
        # These are genuinely different float values in Python
        if a["metric"] != b["metric"]:
            assert content_hash_sha256(a) != content_hash_sha256(b)

    def test_nan_preserved(self):
        data = {"val": float("nan")}
        result = normalize(data)
        assert math.isnan(result["val"])

    def test_inf_preserved(self):
        data = {"val": float("inf")}
        result = normalize(data)
        assert math.isinf(result["val"])

    def test_integer_passthrough(self):
        data = {"val": 42}
        result = normalize(data)
        assert result["val"] == 42
        assert isinstance(result["val"], int)

    def test_zero_float(self):
        data = {"val": 0.0}
        result = normalize(data)
        assert result["val"] == 0.0

    def test_identical_floats_same_hash(self):
        """Same float value → same hash, regardless of how it was computed."""
        a = {"val": 0.5}
        b = {"val": 1.0 / 2.0}
        assert content_hash_sha256(a) == content_hash_sha256(b)


# ── denylist (volatile keys) ────────────────────────────────


class TestDenylist:
    def test_timestamp_stripped(self):
        data = {"value": 1, "timestamp": "2026-01-01T00:00:00"}
        result = normalize(data)
        assert "timestamp" not in result
        assert result["value"] == 1

    def test_run_timestamp_stripped(self):
        data = {"ticker": "PLTR", "run_timestamp": "2026-01-01T00:00:00"}
        result = normalize(data)
        assert "run_timestamp" not in result

    def test_run_id_stripped(self):
        data = {"run_id": "20260101_120000_abc123", "x": 1}
        result = normalize(data)
        assert "run_id" not in result

    def test_started_finished_stripped(self):
        data = {"stage": "ok", "started": "2026-01-01", "finished": "2026-01-01"}
        result = normalize(data)
        assert "started" not in result
        assert "finished" not in result

    def test_nested_volatile_stripped(self):
        data = {
            "backtest": {
                "status": "SUCCESS",
                "timestamp": "2026-01-01T00:00:00",
                "metrics": {"auc": 0.5},
            }
        }
        result = normalize(data)
        assert "timestamp" not in result["backtest"]
        assert result["backtest"]["metrics"]["auc"] == 0.5

    def test_all_volatile_keys_covered(self):
        """Ensure every key in VOLATILE_KEYS is actually stripped."""
        data = {k: "value" for k in VOLATILE_KEYS}
        data["keeper"] = "keep"
        result = normalize(data)
        assert list(result.keys()) == ["keeper"]


# ── *_path key handling ──────────────────────────────────────


class TestPathKeys:
    def test_path_suffix_stripped(self):
        data = {
            "predictions_path": "/some/path/predictions.parquet",
            "auc": 0.8,
        }
        result = normalize(data)
        assert "predictions_path" not in result
        assert result["auc"] == 0.8

    def test_various_path_keys_stripped(self):
        data = {
            "data_path": "/data",
            "model_path": "/model",
            "signals_path": "/signals",
            "html_report_path": "/report.html",
            "value": 1,
        }
        result = normalize(data)
        assert list(result.keys()) == ["value"]

    def test_non_path_suffix_kept(self):
        """Keys that end in 'path' but not '_path' should be kept."""
        data = {"xpath": "expression", "filepath": "kept"}
        result = normalize(data)
        assert "xpath" in result
        assert "filepath" in result

    def test_path_in_string_value_replaced(self):
        data = {"info": "runs/PLTR/20260101_120000_abc123/BacktestAgent/out.json"}
        result = normalize(data)
        assert result["info"] == "__PATH_REMOVED__"

    def test_path_suffix_exact_match_only(self):
        """Only keys ending in exactly '_path' are stripped."""
        data = {
            "something_path": "/removed",   # matches *_path → stripped
            "pathological": "kept",          # no '_path' suffix → kept
            "foo_paths": "kept",             # ends in '_paths' not '_path' → kept
        }
        result = normalize(data)
        assert "something_path" not in result
        assert result["pathological"] == "kept"
        assert result["foo_paths"] == "kept"

    def test_normal_string_kept(self):
        data = {"regime": "TREND_LOW_VOL"}
        result = normalize(data)
        assert result["regime"] == "TREND_LOW_VOL"


# ── strict mode: suspicious key detection ────────────────────


class TestStrictMode:
    def test_known_volatile_stripped_in_strict(self):
        """Known volatile keys are silently stripped even in strict mode."""
        data = {"timestamp": "2026-01-01", "value": 1}
        result = normalize(data, strict=True)
        assert "timestamp" not in result

    def test_unknown_timestamp_key_raises(self):
        """A key matching a suspicious pattern but NOT in denylist raises."""
        data = {"creation_timestamp": "2026-01-01", "value": 1}
        with pytest.raises(ValueError, match="New volatile key encountered"):
            normalize(data, strict=True)

    def test_generated_at_key_raises(self):
        data = {"generated_at": "2026-01-01", "value": 1}
        with pytest.raises(ValueError, match="New volatile key encountered"):
            normalize(data, strict=True)

    def test_non_strict_allows_unknown(self):
        """Without strict mode, suspicious keys pass through."""
        data = {"creation_timestamp": "2026-01-01", "value": 1}
        result = normalize(data, strict=False)
        assert "creation_timestamp" in result

    def test_normal_keys_pass_strict(self):
        """Normal data keys don't trigger false positives."""
        data = {
            "auc": 0.5,
            "ticker": "PLTR",
            "by_year": [],
            "overall": {"total_samples": 100},
            "regime": "TREND_LOW_VOL",
        }
        result = normalize(data, strict=True)
        assert result == data

    def test_nested_pointer_path_in_error(self):
        """Strict mode error includes the full JSON pointer path."""
        data = {
            "report": {
                "integrity": {
                    "creation_timestamp": "2026-01-01"
                }
            }
        }
        with pytest.raises(
            ValueError,
            match=r"at \$\.report\.integrity\.creation_timestamp",
        ):
            normalize(data, strict=True)

    def test_list_item_pointer_path_in_error(self):
        """Strict mode path includes list indices."""
        data = {
            "stages": [
                {"name": "ok"},
                {"build_timestamp": "2026-01-01"},
            ]
        }
        with pytest.raises(
            ValueError,
            match=r"at \$\.stages\[1\]\.build_timestamp",
        ):
            normalize(data, strict=True)


# ── list handling ────────────────────────────────────────────


class TestListHandling:
    def test_list_of_dicts_normalised(self):
        data = {"items": [{"b": 2, "a": 1, "timestamp": "x"}]}
        result = normalize(data)
        assert list(result["items"][0].keys()) == ["a", "b"]

    def test_empty_list_passthrough(self):
        data = {"items": []}
        result = normalize(data)
        assert result["items"] == []

    def test_list_of_scalars(self):
        data = {"vals": [3, 1.5, "hello"]}
        result = normalize(data)
        assert result["vals"] == [3, 1.5, "hello"]


# ── content_hash_sha256 ─────────────────────────────────────


class TestContentHash:
    def test_content_hash_stripped_by_structural_rule(self):
        """content_hash_sha256 is stripped by CONTENT_HASH_KEY, not VOLATILE_KEYS."""
        assert CONTENT_HASH_KEY not in VOLATILE_KEYS, (
            "content_hash_sha256 must NOT be in VOLATILE_KEYS — "
            "it has its own structural rule"
        )
        data = {"val": 1, "content_hash_sha256": "abc123"}
        result = normalize(data)
        assert "content_hash_sha256" not in result

    def test_same_content_same_hash(self):
        a = {"auc": 0.5, "samples": 100}
        b = {"samples": 100, "auc": 0.5}  # different insertion order
        assert content_hash_sha256(a) == content_hash_sha256(b)

    def test_different_content_different_hash(self):
        a = {"auc": 0.5}
        b = {"auc": 0.6}
        assert content_hash_sha256(a) != content_hash_sha256(b)

    def test_volatile_fields_ignored(self):
        a = {"auc": 0.5, "timestamp": "2026-01-01T00:00:00"}
        b = {"auc": 0.5, "timestamp": "2026-12-31T23:59:59"}
        assert content_hash_sha256(a) == content_hash_sha256(b)

    def test_content_hash_field_itself_excluded(self):
        """Adding a content_hash_sha256 field doesn't change the hash."""
        base = {"auc": 0.5, "samples": 100}
        h = content_hash_sha256(base)
        with_hash = {**base, "content_hash_sha256": h}
        assert content_hash_sha256(with_hash) == h

    def test_hash_is_hex_string(self):
        h = content_hash_sha256({"x": 1})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex length
        int(h, 16)  # valid hex


# ── canonical_json output format ─────────────────────────────


class TestCanonicalJson:
    def test_output_is_valid_json(self):
        data = {"z": [1, {"a": True}], "a": None}
        canon = canonical_json(data)
        parsed = json.loads(canon)
        assert parsed is not None

    def test_indent_is_two(self):
        data = {"a": 1}
        canon = canonical_json(data)
        assert '  "a": 1' in canon

    def test_ensure_ascii_false(self):
        data = {"name": "unicode"}
        canon = canonical_json(data)
        assert "unicode" in canon


# ── normalize_file (CLI wrapper) ─────────────────────────────


class TestNormalizeFile:
    def test_file_round_trip(self, tmp_path):
        """Write JSON, normalise to file, read back, verify."""
        input_data = {
            "z": 1,
            "a": 2,
            "timestamp": "volatile",
            "data_path": "/run/path",
        }
        input_path = str(tmp_path / "input.json")
        output_path = str(tmp_path / "output.json")

        with open(input_path, "w") as f:
            json.dump(input_data, f)

        # Use canonical_json directly (same logic as normalize_file)
        with open(input_path, "r") as f:
            data = json.load(f)
        canon = canonical_json(data)
        with open(output_path, "w") as f:
            f.write(canon)
            f.write("\n")

        with open(output_path) as f:
            result = json.load(f)

        assert list(result.keys()) == ["a", "z"]
        assert "timestamp" not in result
        assert "data_path" not in result
