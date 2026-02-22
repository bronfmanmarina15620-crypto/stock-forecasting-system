"""Tests for tools/edge_validate.py — edge validation gate.

Covers:
- Missing artifact detection (exit code 2)
- Deterministic computation (same inputs → same outputs)
- Threshold boundary behavior (exact equals → pass)
- Gate pass/fail for each metric
- Kill-switch triggers
- Regime NO-TRADE identification
- failure_class classification (NONE, EDGE_GATES_FAIL, MISSING_CONFIG, etc.)
- edge_config_hash_sha256 presence
- VERDICT header in report output
"""

import hashlib
import json
import os
import sys
import textwrap

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.edge_validate import (
    _DEFAULT_THRESHOLDS,
    check_gates,
    check_kill_switch,
    classify_verdict,
    compute_edge_metrics,
    load_artifacts,
    load_edge_config,
)


# ============================================================
# Helpers
# ============================================================


def _make_trades(
    n: int = 40,
    seed: int = 42,
    r_values: list = None,
) -> pd.DataFrame:
    """Build a synthetic trades DataFrame with r_multiple column.

    If r_values is provided, uses those directly (n is ignored).
    Otherwise generates n random trades with fixed seed.
    """
    rng = np.random.RandomState(seed)

    if r_values is not None:
        n = len(r_values)
        r_vals = np.array(r_values, dtype=float)
    else:
        r_vals = rng.randn(n) * 0.5 + 0.1  # slight positive bias

    if n == 0:
        return pd.DataFrame(columns=[
            "entry_date", "entry_price", "exit_date", "exit_price",
            "pnl", "return", "holding_days", "shares", "notional",
            "exposure_pct", "stop_distance", "stop_pct", "risk_budget",
            "r_multiple",
        ])

    dates = pd.bdate_range("2024-01-02", periods=n * 5, freq="B")
    rows = []
    for i in range(n):
        entry_i = i * 5
        exit_i = entry_i + rng.randint(1, 4)
        entry_price = 50.0 + rng.randn() * 5
        stop_dist = max(entry_price * 0.05, 0.5)
        risk_budget = 500.0
        shares = max(1, int(risk_budget / stop_dist))
        exit_price = entry_price + r_vals[i] * stop_dist
        pnl = (exit_price - entry_price) * shares
        rows.append({
            "entry_date": str(dates[entry_i].date()),
            "entry_price": round(entry_price, 4),
            "exit_date": str(dates[min(exit_i, len(dates) - 1)].date()),
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 4),
            "return": round((exit_price / entry_price - 1) * 100, 4),
            "holding_days": exit_i - entry_i,
            "shares": shares,
            "notional": round(shares * entry_price, 4),
            "exposure_pct": 0.10,
            "stop_distance": round(stop_dist, 4),
            "stop_pct": round(stop_dist / entry_price, 4),
            "risk_budget": risk_budget,
            "r_multiple": round(r_vals[i], 6),
        })

    return pd.DataFrame(rows)


def _make_walk_forward(
    n_windows: int = 6,
    expectancies: list = None,
) -> dict:
    """Build synthetic walk_forward.json content."""
    if expectancies is None:
        expectancies = [0.01, 0.02, -0.005, 0.015, 0.008, 0.003]

    windows = []
    for i, exp in enumerate(expectancies):
        windows.append({
            "total_return": round(exp * 100, 4),
            "max_dd": 0.05,
            "trades_count": 20,
            "win_rate": 0.55,
            "expectancy": exp,
            "test_days": 60,
        })

    return {"windows": windows, "n_windows": len(windows)}


def _make_monte_carlo(dd_p95: float = 0.15) -> dict:
    """Build synthetic monte_carlo.json content."""
    return {
        "n_simulations": 1000,
        "n_trades": 40,
        "seed": 20260221,
        "final_return": {
            "mean": 0.10,
            "std": 0.05,
            "p5": 0.02,
            "p50": 0.10,
            "p95": 0.20,
        },
        "max_drawdown": {
            "mean": 0.08,
            "std": 0.03,
            "p5": 0.03,
            "p50": 0.07,
            "p95": dd_p95,
        },
    }


def _make_regime_contribution(
    buckets: list = None,
) -> dict:
    """Build synthetic regime_contribution.json content."""
    if buckets is None:
        buckets = [
            {"regime": "normal", "count": 25, "mean_return": 0.02, "total_return": 0.5},
            {"regime": "quiet", "count": 10, "mean_return": 0.01, "total_return": 0.1},
            {"regime": "expanding", "count": 5, "mean_return": -0.03, "total_return": -0.15},
        ]
    return {"buckets": buckets, "source": "volatility_regime"}


def _setup_run_dir(
    tmp_path,
    trades_df=None,
    walk_forward=None,
    monte_carlo=None,
    regime_contribution=None,
    skip_artifact=None,
) -> str:
    """Create a minimal run directory with required artifacts.

    If skip_artifact is set (e.g. "trades"), that artifact is omitted.
    """
    run_dir = str(tmp_path / "runs" / "TEST" / "20260222_120000_abc123")
    os.makedirs(os.path.join(run_dir, "BacktestAgent"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "RobustnessAgent"), exist_ok=True)

    if trades_df is None:
        trades_df = _make_trades()
    if walk_forward is None:
        walk_forward = _make_walk_forward()
    if monte_carlo is None:
        monte_carlo = _make_monte_carlo()
    if regime_contribution is None:
        regime_contribution = _make_regime_contribution()

    if skip_artifact != "trades":
        trades_df.to_parquet(
            os.path.join(run_dir, "BacktestAgent", "trades.parquet"),
            index=False,
        )

    if skip_artifact != "walk_forward":
        with open(
            os.path.join(run_dir, "RobustnessAgent", "walk_forward.json"), "w"
        ) as f:
            json.dump(walk_forward, f)

    if skip_artifact != "monte_carlo":
        with open(
            os.path.join(run_dir, "RobustnessAgent", "monte_carlo.json"), "w"
        ) as f:
            json.dump(monte_carlo, f)

    if skip_artifact != "regime_contribution":
        with open(
            os.path.join(run_dir, "RobustnessAgent", "regime_contribution.json"),
            "w",
        ) as f:
            json.dump(regime_contribution, f)

    return run_dir


def _default_thresholds(**overrides) -> dict:
    """Return default thresholds with optional overrides."""
    t = dict(_DEFAULT_THRESHOLDS)
    t.update(overrides)
    return t


# ============================================================
# TestLoadArtifacts
# ============================================================


class TestLoadArtifacts:
    """Missing or invalid artifacts must trigger exit code 2."""

    def test_missing_trades_exits_2(self, tmp_path):
        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")
        with pytest.raises(SystemExit) as exc_info:
            load_artifacts(run_dir)
        assert exc_info.value.code == 2

    def test_missing_walk_forward_exits_2(self, tmp_path):
        run_dir = _setup_run_dir(tmp_path, skip_artifact="walk_forward")
        with pytest.raises(SystemExit) as exc_info:
            load_artifacts(run_dir)
        assert exc_info.value.code == 2

    def test_missing_monte_carlo_exits_2(self, tmp_path):
        run_dir = _setup_run_dir(tmp_path, skip_artifact="monte_carlo")
        with pytest.raises(SystemExit) as exc_info:
            load_artifacts(run_dir)
        assert exc_info.value.code == 2

    def test_missing_regime_contribution_exits_2(self, tmp_path):
        run_dir = _setup_run_dir(tmp_path, skip_artifact="regime_contribution")
        with pytest.raises(SystemExit) as exc_info:
            load_artifacts(run_dir)
        assert exc_info.value.code == 2

    def test_missing_r_multiple_column_exits_2(self, tmp_path):
        """trades.parquet without r_multiple column → exit 2."""
        trades = _make_trades()
        trades = trades.drop(columns=["r_multiple"])
        run_dir = _setup_run_dir(tmp_path, trades_df=trades)
        with pytest.raises(SystemExit) as exc_info:
            load_artifacts(run_dir)
        assert exc_info.value.code == 2

    def test_valid_artifacts_load_successfully(self, tmp_path):
        run_dir = _setup_run_dir(tmp_path)
        artifacts = load_artifacts(run_dir)
        assert "trades" in artifacts
        assert "walk_forward" in artifacts
        assert "monte_carlo" in artifacts
        assert "regime_contribution" in artifacts
        assert "r_multiple" in artifacts["trades"].columns


# ============================================================
# TestComputeEdgeMetrics
# ============================================================


class TestComputeEdgeMetrics:
    """Deterministic, correct metric computation."""

    def test_deterministic_same_inputs(self):
        """Two calls with identical inputs must produce identical output."""
        trades = _make_trades(n=40, seed=42)
        wf = _make_walk_forward()
        mc = _make_monte_carlo()
        rc = _make_regime_contribution()

        m1 = compute_edge_metrics(trades, wf, mc, rc, roll_k=20)
        m2 = compute_edge_metrics(trades, wf, mc, rc, roll_k=20)
        assert m1 == m2

    def test_n_equals_trade_count(self):
        trades = _make_trades(n=25, seed=1)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=20,
        )
        assert m["n"] == 25

    def test_expectancy_mean_r_multiple(self):
        """E[R] must equal mean of r_multiple values."""
        r_vals = [1.0, 2.0, -0.5, 0.5, -1.0]
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=3,
        )
        expected = round(float(np.mean(r_vals)), 6)
        assert m["e_r"] == expected

    def test_profit_factor_positive_over_negative(self):
        """PF = sum(positive R) / abs(sum(negative R))."""
        r_vals = [2.0, 1.0, -0.5, -0.5]
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=3,
        )
        expected_pf = round(3.0 / 1.0, 6)
        assert m["pf"] == expected_pf

    def test_profit_factor_no_losers(self):
        """All positive R → PF capped at 999.0."""
        r_vals = [1.0, 2.0, 0.5]
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=3,
        )
        assert m["pf"] == 999.0

    def test_profit_factor_all_losers(self):
        """All negative R → PF = 0.0 (no positive sum)."""
        r_vals = [-1.0, -0.5, -2.0]
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=3,
        )
        assert m["pf"] == 0.0

    def test_mdd_r_computation(self):
        """Known cumulative R curve → known MDD."""
        # cumR: 1, 3, 2, 4, 1 → peak=4 at idx 3, trough=1 at idx 4 → MDD=3
        r_vals = [1.0, 2.0, -1.0, 2.0, -3.0]
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=3,
        )
        assert m["mdd_r"] == 3.0

    def test_rolling_expectancy_all_positive(self):
        """All positive R-multiples → pos_roll_ratio = 1.0."""
        r_vals = [1.0] * 25
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=5,
        )
        assert m["pos_roll_ratio"] == 1.0

    def test_rolling_expectancy_mixed(self):
        """Mix of positive/negative windows."""
        # 10 positive, 10 negative → roll_k=10 gives 11 windows
        r_vals = [1.0] * 10 + [-1.0] * 10
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=10,
        )
        # windows: [0:10]=1.0, [1:11]=0.8, ..., [10:20]=-1.0
        assert 0.0 < m["pos_roll_ratio"] < 1.0

    def test_rolling_too_few_trades(self):
        """N < roll_k → pos_roll_ratio = 0.0."""
        r_vals = [1.0, 2.0]
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=20,
        )
        assert m["pos_roll_ratio"] == 0.0

    def test_empty_trades(self):
        """N=0 → safe defaults for all metrics."""
        trades = _make_trades(r_values=[])
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=20,
        )
        assert m["n"] == 0
        assert m["e_r"] == 0.0
        assert m["pf"] == 0.0
        assert m["mdd_r"] == 0.0
        assert m["win_rate"] == 0.0
        assert m["pos_roll_ratio"] == 0.0

    def test_walk_forward_metrics(self):
        """Walk-forward median and pos-folds computed correctly."""
        # 4 positive, 2 negative expectancies
        exps = [0.01, 0.02, -0.005, 0.015, -0.001, 0.003]
        wf = _make_walk_forward(expectancies=exps)
        trades = _make_trades(n=40)
        m = compute_edge_metrics(
            trades, wf, _make_monte_carlo(),
            _make_regime_contribution(), roll_k=20,
        )
        assert m["wf_median_e"] == pytest.approx(
            float(np.median(exps)), abs=1e-6
        )
        assert m["wf_pos_folds"] == pytest.approx(4.0 / 6.0, abs=1e-6)

    def test_walk_forward_empty(self):
        """No walk-forward windows → safe defaults."""
        wf = {"windows": [], "n_windows": 0}
        trades = _make_trades(n=40)
        m = compute_edge_metrics(
            trades, wf, _make_monte_carlo(),
            _make_regime_contribution(), roll_k=20,
        )
        assert m["wf_median_e"] == 0.0
        assert m["wf_pos_folds"] == 0.0

    def test_monte_carlo_dd_p95(self):
        mc = _make_monte_carlo(dd_p95=0.25)
        trades = _make_trades(n=40)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), mc,
            _make_regime_contribution(), roll_k=20,
        )
        assert m["mc_dd_p95"] == 0.25


# ============================================================
# TestCheckGates
# ============================================================


class TestCheckGates:
    """Gate evaluation logic."""

    def _passing_metrics(self) -> dict:
        """Metrics that pass all default gates."""
        return {
            "n": 50,
            "e_r": 0.5,
            "pf": 2.0,
            "mdd_r": 5.0,
            "pos_roll_ratio": 0.7,
            "wf_median_e": 0.01,
            "wf_pos_folds": 0.8,
            "trailing_negative_windows": 0,
            "mc_dd_p95": 0.15,
            "regime_table": [],
        }

    def test_all_gates_pass(self):
        gates = check_gates(self._passing_metrics(), _default_thresholds())
        assert all(g["passed"] for g in gates.values())

    def test_n_below_min_fails(self):
        metrics = self._passing_metrics()
        metrics["n"] = 20  # below n_min=30
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["n_min"]["passed"]

    def test_expectancy_below_min_fails(self):
        metrics = self._passing_metrics()
        metrics["e_r"] = -0.1  # below default e_min=0.0
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["e_min"]["passed"]

    def test_pf_below_min_fails(self):
        metrics = self._passing_metrics()
        metrics["pf"] = 0.8  # below default pf_min=1.0
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["pf_min"]["passed"]

    def test_mdd_above_max_fails(self):
        metrics = self._passing_metrics()
        metrics["mdd_r"] = 20.0  # above default mdd_max=5.0
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["mdd_max"]["passed"]

    def test_rolling_below_min_fails(self):
        metrics = self._passing_metrics()
        metrics["pos_roll_ratio"] = 0.3  # below explicit threshold 0.5
        gates = check_gates(metrics, _default_thresholds(pos_roll_ratio_min=0.5))
        assert not gates["pos_roll_ratio_min"]["passed"]

    def test_wf_e_below_min_fails(self):
        metrics = self._passing_metrics()
        metrics["wf_median_e"] = -0.01  # below default 0.0
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["wf_e_min"]["passed"]

    def test_wf_pos_folds_below_min_fails(self):
        metrics = self._passing_metrics()
        metrics["wf_pos_folds"] = 0.3  # below explicit threshold 0.5
        gates = check_gates(metrics, _default_thresholds(wf_pos_folds_min=0.5))
        assert not gates["wf_pos_folds_min"]["passed"]

    def test_boundary_exact_equals_passes(self):
        """Value exactly at threshold → pass (>= / <=)."""
        metrics = self._passing_metrics()
        thresholds = _default_thresholds()
        metrics["n"] = thresholds["n_min"]
        metrics["e_r"] = thresholds["e_min"]
        metrics["pf"] = thresholds["pf_min"]
        metrics["mdd_r"] = thresholds["mdd_max"]
        metrics["pos_roll_ratio"] = thresholds["pos_roll_ratio_min"]
        metrics["wf_median_e"] = thresholds["wf_e_min"]
        metrics["wf_pos_folds"] = thresholds["wf_pos_folds_min"]
        gates = check_gates(metrics, thresholds)
        assert all(g["passed"] for g in gates.values())

    def test_n_below_min_floor_fails(self):
        """N < n_min_floor (30) must FAIL the n_min gate, not PASS."""
        metrics = self._passing_metrics()
        metrics["n"] = 10  # well below n_min=30
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["n_min"]["passed"]

    def test_pos_roll_below_floor_fails(self):
        """pos_roll_ratio below 0.5 floor must FAIL."""
        metrics = self._passing_metrics()
        metrics["pos_roll_ratio"] = 0.0  # below pos_roll_ratio_min=0.5
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["pos_roll_ratio_min"]["passed"]

    def test_wf_pos_folds_below_floor_fails(self):
        """wf_pos_folds below 0.5 floor must FAIL."""
        metrics = self._passing_metrics()
        metrics["wf_pos_folds"] = 0.0  # below wf_pos_folds_min=0.5
        gates = check_gates(metrics, _default_thresholds())
        assert not gates["wf_pos_folds_min"]["passed"]


# ============================================================
# TestKillSwitch
# ============================================================


class TestKillSwitch:
    """Kill-switch trigger conditions."""

    def test_no_trigger_normal(self):
        metrics = {
            "mdd_r": 3.0,
            "trailing_negative_windows": 0,
        }
        ks = check_kill_switch(metrics, _default_thresholds())
        assert not ks["triggered"]
        assert ks["reasons"] == []

    def test_rolling_fail_streak_triggers(self):
        metrics = {
            "mdd_r": 3.0,
            "trailing_negative_windows": 5,  # equals roll_fail_streak=5
        }
        ks = check_kill_switch(metrics, _default_thresholds())
        assert ks["triggered"]
        assert any("rolling_fail_streak" in r for r in ks["reasons"])

    def test_dd_shock_triggers(self):
        metrics = {
            "mdd_r": 10.0,  # equals dd_shock=10.0
            "trailing_negative_windows": 0,
        }
        ks = check_kill_switch(metrics, _default_thresholds())
        assert ks["triggered"]
        assert any("dd_shock" in r for r in ks["reasons"])

    def test_both_triggers(self):
        metrics = {
            "mdd_r": 15.0,
            "trailing_negative_windows": 10,
        }
        ks = check_kill_switch(metrics, _default_thresholds())
        assert ks["triggered"]
        assert len(ks["reasons"]) == 2

    def test_just_below_thresholds_no_trigger(self):
        metrics = {
            "mdd_r": 9.99,  # just below dd_shock=10.0
            "trailing_negative_windows": 4,  # just below roll_fail_streak=5
        }
        ks = check_kill_switch(metrics, _default_thresholds())
        assert not ks["triggered"]


# ============================================================
# TestRegimeContribution
# ============================================================


class TestRegimeContribution:
    """Regime NO-TRADE identification."""

    def test_no_trade_regime_identified(self):
        """Regime with negative mean_return flagged as no_trade."""
        buckets = [
            {"regime": "normal", "count": 20, "mean_return": 0.02, "total_return": 0.4},
            {"regime": "expanding", "count": 10, "mean_return": -0.05, "total_return": -0.5},
        ]
        rc = _make_regime_contribution(buckets=buckets)
        trades = _make_trades(n=40)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(), rc, roll_k=20,
        )
        rt = m["regime_table"]
        assert len(rt) == 2
        normal = next(r for r in rt if r["regime"] == "normal")
        expanding = next(r for r in rt if r["regime"] == "expanding")
        assert not normal["no_trade"]
        assert expanding["no_trade"]

    def test_all_regimes_positive(self):
        buckets = [
            {"regime": "normal", "count": 30, "mean_return": 0.01, "total_return": 0.3},
        ]
        rc = _make_regime_contribution(buckets=buckets)
        trades = _make_trades(n=40)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(), rc, roll_k=20,
        )
        assert all(not r["no_trade"] for r in m["regime_table"])

    def test_empty_regime_table(self):
        rc = _make_regime_contribution(buckets=[])
        trades = _make_trades(n=40)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(), rc, roll_k=20,
        )
        assert m["regime_table"] == []


# ============================================================
# TestEdgeConfig
# ============================================================


class TestEdgeConfig:
    """Config loading from YAML."""

    def test_load_default_config(self):
        """load_edge_config with nonexistent path and _allow_defaults → defaults."""
        cfg = load_edge_config("/nonexistent/path.yaml", _allow_defaults=True)
        assert cfg == _DEFAULT_THRESHOLDS

    def test_missing_config_exits_2(self):
        """load_edge_config with nonexistent path (no _allow_defaults) → exit 2."""
        with pytest.raises(SystemExit) as exc_info:
            load_edge_config("/nonexistent/path.yaml")
        assert exc_info.value.code == 2

    def test_load_real_config(self):
        """Load from actual config/edge.yaml if it exists."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "edge.yaml"
        )
        if os.path.exists(config_path):
            cfg = load_edge_config(config_path)
            # Must have all required keys
            for key in _DEFAULT_THRESHOLDS:
                assert key in cfg

    def test_load_custom_config(self, tmp_path):
        """Custom YAML overrides defaults."""
        yaml_content = textwrap.dedent("""\
            edge_gates:
              n_min: 50
              e_min: 0.1
        """)
        cfg_path = str(tmp_path / "custom_edge.yaml")
        with open(cfg_path, "w") as f:
            f.write(yaml_content)

        cfg = load_edge_config(cfg_path)
        assert cfg["n_min"] == 50
        assert cfg["e_min"] == 0.1
        # Other keys should be defaults
        assert cfg["pf_min"] == _DEFAULT_THRESHOLDS["pf_min"]

    def test_missing_config_with_allow_defaults(self):
        """_allow_defaults=True → fallback to _DEFAULT_THRESHOLDS (no exit)."""
        cfg = load_edge_config("/tmp/does_not_exist.yaml", _allow_defaults=True)
        assert cfg == _DEFAULT_THRESHOLDS


# ============================================================
# TestEndToEnd
# ============================================================


class TestEndToEnd:
    """Integration: load → compute → check → report."""

    def test_full_pipeline_passing(self, tmp_path):
        """All-positive trades → all gates pass."""
        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01])
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)

        artifacts = load_artifacts(run_dir)
        metrics = compute_edge_metrics(
            artifacts["trades"], artifacts["walk_forward"],
            artifacts["monte_carlo"], artifacts["regime_contribution"],
            roll_k=20,
        )
        gates = check_gates(metrics, _default_thresholds())
        ks = check_kill_switch(metrics, _default_thresholds())

        assert all(g["passed"] for g in gates.values())
        assert not ks["triggered"]

    def test_full_pipeline_failing(self, tmp_path):
        """All-negative trades → gates fail."""
        r_vals = [-1.0] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[-0.01] * 6)
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)

        artifacts = load_artifacts(run_dir)
        metrics = compute_edge_metrics(
            artifacts["trades"], artifacts["walk_forward"],
            artifacts["monte_carlo"], artifacts["regime_contribution"],
            roll_k=20,
        )
        gates = check_gates(metrics, _default_thresholds())

        assert not gates["e_min"]["passed"]
        assert not gates["pf_min"]["passed"]

    def test_trailing_negative_streak(self):
        """Trailing negative windows computed for kill-switch."""
        # 15 positive then 10 negative → last 10 are negative
        r_vals = [1.0] * 15 + [-1.0] * 10
        trades = _make_trades(r_values=r_vals)
        m = compute_edge_metrics(
            trades, _make_walk_forward(), _make_monte_carlo(),
            _make_regime_contribution(), roll_k=5,
        )
        # Last several rolling windows should be negative
        assert m["trailing_negative_windows"] > 0


# ============================================================
# TestValidateRunEdgeIntegration
# ============================================================


class TestValidateRunEdgeIntegration:
    """Test that validate_run.py Step 10 (edge gates) works correctly."""

    def test_validate_edge_gates_missing_trades(self, tmp_path):
        """Missing trades.parquet → fail_reasons populated, edge_exit_code=2."""
        from validate_run import validate_edge_gates
        from pathlib import Path

        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")
        failures, warnings, edge_exit_code = validate_edge_gates(Path(run_dir))
        assert len(failures) > 0
        assert any("missing" in f.lower() or "MISSING" in f for f in failures)
        assert edge_exit_code == 2

    def test_validate_edge_gates_passing(self, tmp_path):
        """All-positive trades → no failures, edge_exit_code=0."""
        from validate_run import validate_edge_gates
        from pathlib import Path

        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01]
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        failures, warnings, edge_exit_code = validate_edge_gates(Path(run_dir))
        assert failures == []
        assert edge_exit_code == 0

    def test_validate_edge_gates_failing(self, tmp_path):
        """All-negative trades → failures, edge_exit_code=1."""
        from validate_run import validate_edge_gates
        from pathlib import Path

        r_vals = [-1.0] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[-0.01] * 6)
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        failures, warnings, edge_exit_code = validate_edge_gates(Path(run_dir))
        assert len(failures) > 0
        assert any("EDGE: FAIL" in f for f in failures)
        assert edge_exit_code == 1


# ============================================================
# TestRunEdgePersistence
# ============================================================


class TestRunEdgePersistence:
    """Test that run.py persists edge_report.txt and edge_summary.json."""

    def test_edge_summary_written_on_success(self, tmp_path):
        """_run_edge_validation writes edge_summary.json."""
        # We can't call run.py main() but we can call _run_edge_validation
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from run import _run_edge_validation

        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01]
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)

        result = _run_edge_validation(run_dir)

        assert result is True

        # Check files exist
        summary_path = os.path.join(run_dir, "edge_summary.json")
        report_path = os.path.join(run_dir, "edge_report.txt")
        assert os.path.exists(summary_path)
        assert os.path.exists(report_path)

        # Validate edge_summary.json contents
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["edge_pass"] is True
        assert summary["exit_code"] == 0
        assert summary["N"] == 40
        assert summary["expectancy"] > 0
        assert summary["pf"] > 0
        assert summary["kill_switch"] is False
        assert "gates" in summary
        assert "regime_table" in summary

    def test_edge_report_written_on_success(self, tmp_path):
        """_run_edge_validation writes edge_report.txt."""
        from run import _run_edge_validation

        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01]
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        _run_edge_validation(run_dir)

        report_path = os.path.join(run_dir, "edge_report.txt")
        with open(report_path) as f:
            report = f.read()
        assert "EDGE VALIDATION REPORT" in report
        assert "VERDICT: PASS" in report

    def test_edge_summary_written_on_failure(self, tmp_path):
        """Failing trades → edge_summary.json with edge_pass=False."""
        from run import _run_edge_validation

        r_vals = [-1.0] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[-0.01] * 6)
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)

        result = _run_edge_validation(run_dir)
        assert result is False

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)
        assert summary["edge_pass"] is False
        assert summary["exit_code"] == 1

    def test_edge_missing_artifacts_writes_summary(self, tmp_path):
        """Missing artifacts → edge_summary.json with exit_code=2, hard fail."""
        from run import _run_edge_validation

        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")
        result = _run_edge_validation(run_dir)
        assert result is False

        summary_path = os.path.join(run_dir, "edge_summary.json")
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["edge_pass"] is False
        assert summary["exit_code"] == 2
        assert "error" in summary


# ============================================================
# TestEdgeHardFailure — invariant: no SUCCESS when edge != 0
# ============================================================


class TestEdgeHardFailure:
    """A run cannot be marked SUCCESS when edge_exit_code != 0.

    Simulates the success path in run.py main() and verifies that
    edge failures force FAILED status on disk.
    """

    def _simulate_success_path(self, run_dir):
        """Mirror the edge-aware finalization logic from run.py main().

        Returns (summary_dict, program_exit_code).
        """
        from run import (
            _run_edge_validation,
            _read_edge_exit_code,
            _make_summary,
            _persist_summary,
        )

        summary = _make_summary(
            "TEST", "test_run", "abc123", "2026-01-01T00:00:00Z", "STARTED",
        )

        edge_pass = _run_edge_validation(run_dir)

        if not edge_pass:
            edge_exit_code = _read_edge_exit_code(run_dir)
            summary["status"] = "FAILED"
            if edge_exit_code == 2:
                summary["error"] = (
                    "Edge validation: missing or invalid artifacts"
                )
            else:
                summary["error"] = "Edge validation: gates failed"
            _persist_summary(summary, run_dir)
            return summary, edge_exit_code

        summary["status"] = "SUCCESS"
        _persist_summary(summary, run_dir)
        return summary, 0

    def test_edge_gate_fail_prevents_success(self, tmp_path):
        """edge exit_code=1 (gates fail) => status.txt != SUCCESS."""
        r_vals = [-1.0] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[-0.01] * 6)
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)

        summary, exit_code = self._simulate_success_path(run_dir)

        assert summary["status"] == "FAILED"
        assert exit_code == 1

        # Verify on-disk status.txt
        with open(os.path.join(run_dir, "status.txt")) as f:
            status_text = f.read()
        assert "SUCCESS" not in status_text
        assert "FAILED" in status_text

    def test_edge_missing_artifacts_prevents_success(self, tmp_path):
        """edge exit_code=2 (missing artifacts) => status.txt != SUCCESS."""
        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")

        summary, exit_code = self._simulate_success_path(run_dir)

        assert summary["status"] == "FAILED"
        assert exit_code == 2

        # Verify on-disk status.txt
        with open(os.path.join(run_dir, "status.txt")) as f:
            status_text = f.read()
        assert "SUCCESS" not in status_text
        assert "FAILED" in status_text

    def test_edge_pass_allows_success(self, tmp_path):
        """edge exit_code=0 (pass) => status may be SUCCESS."""
        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01],
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)

        summary, exit_code = self._simulate_success_path(run_dir)

        assert summary["status"] == "SUCCESS"
        assert exit_code == 0

        # Verify on-disk status.txt
        with open(os.path.join(run_dir, "status.txt")) as f:
            status_text = f.read()
        assert "SUCCESS" in status_text


# ============================================================
# TestClassifyVerdict
# ============================================================


class TestClassifyVerdict:
    """classify_verdict() returns correct token from gates + kill_switch."""

    def test_all_pass_no_kill(self):
        gates = {"g1": {"passed": True}, "g2": {"passed": True}}
        ks = {"triggered": False, "reasons": []}
        assert classify_verdict(gates, ks) == "PASS"

    def test_gate_fail(self):
        gates = {"g1": {"passed": True}, "g2": {"passed": False}}
        ks = {"triggered": False, "reasons": []}
        assert classify_verdict(gates, ks) == "FAIL_GATES"

    def test_kill_switch_triggered(self):
        gates = {"g1": {"passed": True}}
        ks = {"triggered": True, "reasons": ["dd_shock"]}
        assert classify_verdict(gates, ks) == "FAIL_GATES"


# ============================================================
# TestFailureClassification
# ============================================================


class TestFailureClassification:
    """failure_class in edge_summary.json must be correct per scenario."""

    def test_pass_failure_class_none(self, tmp_path):
        """edge pass → failure_class == 'NONE'."""
        from run import _run_edge_validation

        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01],
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)
        assert summary["failure_class"] == "NONE"

    def test_gate_fail_failure_class(self, tmp_path):
        """gate fail → failure_class == 'EDGE_GATES_FAIL'."""
        from run import _run_edge_validation

        r_vals = [-1.0] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[-0.01] * 6)
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)
        assert summary["failure_class"] == "EDGE_GATES_FAIL"

    def test_missing_artifacts_failure_class(self, tmp_path):
        """missing trades.parquet → failure_class == 'MISSING_ARTIFACTS'."""
        from run import _run_edge_validation

        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)
        assert summary["failure_class"] == "MISSING_ARTIFACTS"

    def test_missing_config_failure_class(self, tmp_path, monkeypatch):
        """missing config/edge.yaml → failure_class == 'MISSING_CONFIG'."""
        from run import _run_edge_validation

        run_dir = _setup_run_dir(tmp_path)

        # Patch load_edge_config to raise SystemExit(2) simulating missing config
        def _fake_load_edge_config(*args, **kwargs):
            raise SystemExit(2)

        monkeypatch.setattr(
            "run.load_edge_config", _fake_load_edge_config,
            raising=False,
        )
        # We need to monkeypatch via the import inside _run_edge_validation
        # Since it does `from tools.edge_validate import load_edge_config`,
        # we need to patch at the source
        import tools.edge_validate as ev_mod
        original = ev_mod.load_edge_config
        monkeypatch.setattr(ev_mod, "load_edge_config", _fake_load_edge_config)

        _run_edge_validation(run_dir)

        monkeypatch.setattr(ev_mod, "load_edge_config", original)

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)
        assert summary["failure_class"] == "MISSING_CONFIG"

    def test_edge_config_hash_present_when_loaded(self, tmp_path):
        """edge_config_hash_sha256 present and correct when config loaded."""
        from run import _run_edge_validation

        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01],
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)

        assert summary["edge_config_loaded"] is True
        assert summary["edge_config_path"] == "config/edge.yaml"

        # Verify hash matches actual file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "edge.yaml",
        )
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                expected_hash = hashlib.sha256(f.read()).hexdigest()
            assert summary["edge_config_hash_sha256"] == expected_hash

    def test_edge_config_hash_null_when_missing(self, tmp_path, monkeypatch):
        """edge_config_hash_sha256 is null when config not found."""
        from run import _run_edge_validation, _edge_config_info

        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")

        # Patch _edge_config_info to simulate missing config
        def _fake_config_info():
            return {
                "edge_config_path": "config/edge.yaml",
                "edge_config_loaded": False,
                "edge_config_hash_sha256": None,
            }

        import run as run_mod
        monkeypatch.setattr(run_mod, "_edge_config_info", _fake_config_info)

        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_summary.json")) as f:
            summary = json.load(f)
        assert summary["edge_config_loaded"] is False
        assert summary["edge_config_hash_sha256"] is None


# ============================================================
# TestVerdictHeader
# ============================================================


class TestVerdictHeader:
    """VERDICT line must appear as the first line of edge_report.txt."""

    def test_verdict_pass_in_report(self, tmp_path):
        from run import _run_edge_validation

        r_vals = [0.5] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(
            expectancies=[0.01, 0.02, 0.015, 0.008, 0.005, 0.01],
        )
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_report.txt")) as f:
            first_line = f.readline().strip()
        assert first_line == "VERDICT: PASS"

    def test_verdict_fail_gates_in_report(self, tmp_path):
        from run import _run_edge_validation

        r_vals = [-1.0] * 40
        trades = _make_trades(r_values=r_vals)
        wf = _make_walk_forward(expectancies=[-0.01] * 6)
        run_dir = _setup_run_dir(tmp_path, trades_df=trades, walk_forward=wf)
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_report.txt")) as f:
            first_line = f.readline().strip()
        assert first_line == "VERDICT: FAIL_GATES"

    def test_verdict_missing_in_error_report(self, tmp_path):
        """Missing artifacts → VERDICT line present in error report."""
        from run import _run_edge_validation

        run_dir = _setup_run_dir(tmp_path, skip_artifact="trades")
        _run_edge_validation(run_dir)

        with open(os.path.join(run_dir, "edge_report.txt")) as f:
            first_line = f.readline().strip()
        assert first_line.startswith("VERDICT:")
