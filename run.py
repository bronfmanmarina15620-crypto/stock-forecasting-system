#!/usr/bin/env python3
"""
Main CLI entrypoint for the stock forecasting system.

Usage:
    python run.py --ticker PLTR
    python run.py --ticker PLTR --config custom_config.json
"""

# ── Deterministic thread/env pinning ──────────────────────────
# MUST be set before importing numpy/pandas/scipy so BLAS/LAPACK
# backends read these values at library init time.
import os as _os
for _k, _v in {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}.items():
    _os.environ.setdefault(_k, _v)
_os.environ.setdefault("PYTHONHASHSEED", "0")
del _k, _v
# ──────────────────────────────────────────────────────────────

import argparse
import hashlib
import subprocess
import sys
import os
import json
from datetime import datetime, date, timezone

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SystemConfig, get_default_config
from utils import generate_run_id, setup_run_directory, set_random_seeds, AgentLogger
from agents import OrchestratorAgent


def _save_config_yaml(config: SystemConfig, filepath: str):
    """Save config as YAML for human readability."""
    d = config.to_dict()

    def _dict_to_yaml(data, indent=0):
        lines = []
        prefix = "  " * indent
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(f"{prefix}{k}:")
                lines.append(_dict_to_yaml(v, indent + 1))
            elif isinstance(v, list):
                lines.append(f"{prefix}{k}:")
                for item in v:
                    if isinstance(item, dict):
                        lines.append(f"{prefix}  -")
                        lines.append(_dict_to_yaml(item, indent + 2))
                    else:
                        lines.append(f"{prefix}  - {item}")
            elif isinstance(v, bool):
                lines.append(f"{prefix}{k}: {'true' if v else 'false'}")
            elif v is None:
                lines.append(f"{prefix}{k}: null")
            else:
                lines.append(f"{prefix}{k}: {v}")
        return "\n".join(lines)

    yaml_str = f"# Config snapshot - frozen at run start\n{_dict_to_yaml(d)}\n"
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        f.write(yaml_str)


def _get_git_sha() -> str:
    """Return full git SHA, or 'unknown' if not in a git repo."""
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return 'unknown'


def _resolve_as_of_date(cli_value: str | None) -> date:
    """Resolve as_of_date from CLI flag, env var, or today (in that order)."""
    if cli_value:
        return date.fromisoformat(cli_value)
    env_val = os.environ.get("AS_OF_DATE")
    if env_val:
        return date.fromisoformat(env_val)
    return date.today()


def _write_meta_json(run_dir: str, ticker: str, run_id: str, git_sha: str,
                     as_of_date: date, replay_from: str | None = None):
    """Write _meta.json immediately after run dir creation."""
    meta = {
        'ticker': ticker,
        'run_id': run_id,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'git_sha': git_sha,
        'as_of_date': as_of_date.isoformat(),
    }
    if replay_from:
        meta['replay_from'] = replay_from
    from determinism import dump_canonical_json
    dump_canonical_json(os.path.join(run_dir, '_meta.json'), meta)
    return meta['created_utc']


# ── Single source of truth: summary dict → both files ──────────────

_VALID_DECISIONS = {'ENTER', 'ABSTAIN', 'EXIT', 'UNKNOWN'}

_REQUIRED_OUTPUTS = [
    'final_report.json',
    'final_report.html',
    'BacktestAgent/metrics.json',
    'DecisionRiskAgent/decision_action.json',
    '_meta.json',
]


def _make_summary(ticker: str, run_id: str, git_sha: str, created_utc: str,
                  status: str, as_of_date: date = None,
                  error: str = None) -> dict:
    """Build a summary dict. Decision/trade fields left at defaults."""
    d = {
        'ticker': ticker,
        'run_id': run_id,
        'status': status,
        'created_utc': created_utc,
        'finished_utc': datetime.now(timezone.utc).isoformat(),
        'git_sha': git_sha,
        'has_trade': False,
        'decision': 'UNKNOWN',
        'error': error,
    }
    if as_of_date:
        d['as_of_date'] = as_of_date.isoformat()
    return d


def _populate_decision(summary: dict, run_dir: str):
    """Read decision_action.json and populate summary in place."""
    path = os.path.join(run_dir, 'DecisionRiskAgent', 'decision_action.json')
    try:
        with open(path) as f:
            data = json.load(f)
        raw = data.get('action', 'UNKNOWN')
        summary['decision'] = raw if raw in _VALID_DECISIONS else 'UNKNOWN'
        summary['has_trade'] = data.get('position', 0) == 1
    except Exception:
        pass  # defaults already set


def _check_required_outputs(run_dir: str) -> str:
    """Return first missing required output path, or None if all present."""
    for rel in _REQUIRED_OUTPUTS:
        if not os.path.exists(os.path.join(run_dir, rel)):
            return rel
    return None


def _persist_summary(summary: dict, run_dir: str):
    """Write BOTH run_summary.json and status.txt from the same dict."""
    from determinism import dump_canonical_json
    summary['finished_utc'] = datetime.now(timezone.utc).isoformat()

    dump_canonical_json(os.path.join(run_dir, 'run_summary.json'), summary)

    with open(os.path.join(run_dir, 'status.txt'), 'w') as f:
        f.write(f"STATUS: {summary['status']}\n")
        f.write(f"TIMESTAMP: {summary['finished_utc']}\n")
        f.write(f"TICKER: {summary['ticker']}\n")
        f.write(f"Commit: {summary['git_sha']}\n")
        if summary.get('error'):
            f.write(f"ERROR: {summary['error']}\n")


def _edge_config_info() -> dict:
    """Return config path, loaded flag, and SHA-256 hash of config/edge.yaml."""
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", "edge.yaml",
    )
    info = {
        "edge_config_path": "config/edge.yaml",
        "edge_config_loaded": False,
        "edge_config_hash_sha256": None,
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "rb") as f:
                info["edge_config_hash_sha256"] = hashlib.sha256(
                    f.read()
                ).hexdigest()
            info["edge_config_loaded"] = True
        except Exception:
            pass
    return info


def _classify_edge_failure(exit_code: int, error: str = None) -> str:
    """Deterministic failure_class from exit_code + error message.

    Mapping:
        exit_code 0 → "NONE"
        exit_code 1 → "EDGE_GATES_FAIL"
        exit_code 2 → classified by error string:
            missing config     → "MISSING_CONFIG"
            missing artifact   → "MISSING_ARTIFACTS"
            parse/schema error → "INVALID_ARTIFACTS"
            anything else      → "EXCEPTION"
    """
    if exit_code == 0:
        return "NONE"
    if exit_code == 1:
        return "EDGE_GATES_FAIL"
    # exit_code == 2 — classify from error
    if not error:
        return "EXCEPTION"
    err_lower = error.lower()
    if "config" in err_lower:
        return "MISSING_CONFIG"
    if "missing" in err_lower and "artifact" in err_lower:
        return "MISSING_ARTIFACTS"
    if "invalid" in err_lower or "parse" in err_lower or "schema" in err_lower:
        return "INVALID_ARTIFACTS"
    if "import" in err_lower:
        return "EXCEPTION"
    # Fallback: distinguish missing vs invalid from the raw message
    if "missing" in err_lower:
        return "MISSING_ARTIFACTS"
    return "EXCEPTION"


def _run_edge_validation(run_dir: str):
    """Run edge validation and persist report + summary JSON.

    Writes:
        <run_dir>/edge_report.txt   — human-readable report
        <run_dir>/edge_summary.json — machine-readable summary

    Returns True if edge gates pass, False otherwise.
    On import/artifact errors, writes a MISSING summary and returns False.
    """
    try:
        from tools.edge_validate import (
            load_edge_config,
            load_artifacts,
            compute_edge_metrics,
            check_gates,
            check_kill_switch,
            print_report,
        )
    except ImportError as e:
        err = f"import error: {e}"
        _write_edge_summary(run_dir, edge_pass=False, exit_code=2, error=err)
        return False

    try:
        thresholds = load_edge_config()
    except SystemExit:
        err = "missing or invalid config/edge.yaml"
        _write_edge_summary(run_dir, edge_pass=False, exit_code=2, error=err)
        return False

    try:
        artifacts = load_artifacts(run_dir)
    except SystemExit:
        err = "missing or invalid artifacts"
        _write_edge_summary(run_dir, edge_pass=False, exit_code=2, error=err)
        return False

    metrics = compute_edge_metrics(
        trades_df=artifacts["trades"],
        walk_forward=artifacts["walk_forward"],
        monte_carlo=artifacts["monte_carlo"],
        regime_contribution=artifacts["regime_contribution"],
        roll_k=thresholds["roll_k"],
    )

    gates = check_gates(metrics, thresholds)
    kill_switch = check_kill_switch(metrics, thresholds)

    all_pass = all(g["passed"] for g in gates.values())
    ks_triggered = kill_switch["triggered"]
    edge_pass = all_pass and not ks_triggered
    exit_code = 0 if edge_pass else 1

    # Capture report text
    import io
    buf = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(buf):
        print_report(metrics, gates, kill_switch)
    report_text = buf.getvalue()

    # Write edge_report.txt
    with open(os.path.join(run_dir, "edge_report.txt"), "w") as f:
        f.write(report_text)

    # Build failure_class + config info
    failure_class = _classify_edge_failure(exit_code)
    config_info = _edge_config_info()

    # Write edge_summary.json
    summary = {
        "edge_pass": edge_pass,
        "exit_code": exit_code,
        "failure_class": failure_class,
        "N": metrics["n"],
        "expectancy": metrics["e_r"],
        "pf": metrics["pf"],
        "mdd_r": metrics["mdd_r"],
        "win_rate": metrics["win_rate"],
        "pos_roll_ratio": metrics["pos_roll_ratio"],
        "wf_median_e": metrics["wf_median_e"],
        "wf_pos_folds": metrics["wf_pos_folds"],
        "kill_switch": ks_triggered,
        "gates": {
            name: {"passed": g["passed"], "value": g["value"],
                   "threshold": g["threshold"]}
            for name, g in gates.items()
        },
        "regime_table": metrics.get("regime_table", []),
    }
    summary.update(config_info)
    from determinism import dump_canonical_json
    dump_canonical_json(os.path.join(run_dir, "edge_summary.json"), summary)

    return edge_pass


def _write_edge_summary(run_dir: str, edge_pass: bool, exit_code: int,
                        error: str = None):
    """Write a minimal edge_summary.json on error."""
    failure_class = _classify_edge_failure(exit_code, error)
    config_info = _edge_config_info()
    summary = {
        "edge_pass": edge_pass,
        "exit_code": exit_code,
        "failure_class": failure_class,
        "N": 0,
        "expectancy": 0.0,
        "pf": 0.0,
        "mdd_r": 0.0,
        "win_rate": 0.0,
        "pos_roll_ratio": 0.0,
        "wf_median_e": 0.0,
        "wf_pos_folds": 0.0,
        "kill_switch": False,
        "gates": {},
        "regime_table": [],
        "error": error,
    }
    summary.update(config_info)
    from determinism import dump_canonical_json
    dump_canonical_json(os.path.join(run_dir, "edge_summary.json"), summary)
    with open(os.path.join(run_dir, "edge_report.txt"), "w") as f:
        f.write(f"VERDICT: {failure_class}\n")
        f.write(f"EDGE: MISSING — {error}\n")


def _read_edge_exit_code(run_dir: str) -> int:
    """Read exit_code from edge_summary.json, default 2 on any error."""
    try:
        with open(os.path.join(run_dir, 'edge_summary.json')) as f:
            return json.load(f).get('exit_code', 2)
    except Exception:
        return 2


def _assert_persisted(run_dir: str, expected_status: str):
    """Re-read run_summary.json and assert status matches."""
    path = os.path.join(run_dir, 'run_summary.json')
    with open(path) as f:
        on_disk = json.load(f)
    if on_disk.get('status') != expected_status:
        raise RuntimeError(
            f"Summary persistence mismatch: expected {expected_status}, "
            f"got {on_disk.get('status')}"
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Multi-Agent Stock Forecasting System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --ticker PLTR
  python run.py --ticker PLTR --config my_config.json
  
  # Multi-ticker mode (not active yet):
  # python run.py --tickers TSLA,MSFT,IBIT
        """
    )
    
    parser.add_argument(
        '--ticker',
        type=str,
        default='PLTR',
        help='Stock ticker to analyze (default: PLTR)'
    )
    
    parser.add_argument(
        '--tickers',
        type=str,
        help='Comma-separated list of tickers (multi-ticker mode - not active)'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        help='Path to custom configuration JSON file'
    )
    
    parser.add_argument(
        '--run-dir',
        type=str,
        default='runs',
        help='Base directory for runs (default: runs)'
    )

    parser.add_argument(
        '--mode',
        type=str,
        choices=['backtest', 'shadow'],
        default='backtest',
        help='Run mode: backtest (default) or shadow (monitoring-only, no trading)'
    )

    parser.add_argument(
        '--lookback-days',
        type=int,
        default=None,
        help='Override data lookback window in calendar days (default: 730)'
    )

    parser.add_argument(
        '--min-bars',
        type=int,
        default=None,
        help='Override minimum required trading days (default: 252)'
    )

    parser.add_argument(
        '--as-of',
        type=str,
        default=None,
        help='As-of date for data fetch (YYYY-MM-DD). '
             'Precedence: CLI > env AS_OF_DATE > today'
    )

    parser.add_argument(
        '--replay-from',
        type=str,
        default=None,
        help='Path to source run directory for replay mode. '
             'Loads data snapshot from that run instead of fetching live data.'
    )

    parser.add_argument(
        '--skip-edge',
        action='store_true',
        default=False,
        help='Skip edge validation gate. Useful for determinism checks '
             'where only content parity matters.'
    )

    args = parser.parse_args()
    
    # Check multi-ticker mode
    if args.tickers:
        print("⚠️  Multi-ticker mode is not active yet. Using single-ticker mode.")
        print(f"⚠️  Only the first ticker will be used.")
        tickers = args.tickers.split(',')
        ticker = tickers[0].strip()
    else:
        ticker = args.ticker
    
    run_mode = args.mode
    replay_from = args.replay_from

    # Resolve as_of_date: CLI > env > today
    as_of_date = _resolve_as_of_date(args.as_of)

    print(f"\n{'='*60}")
    print(f"Multi-Agent Stock Forecasting System")
    print(f"{'='*60}")
    print(f"Ticker: {ticker}")
    print(f"Mode: {run_mode.upper()}")
    print(f"As-of date: {as_of_date.isoformat()}")
    if replay_from:
        print(f"Replay from: {replay_from}")
    print(f"{'='*60}\n")
    
    # Load or create configuration
    if args.config and os.path.exists(args.config):
        print(f"Loading configuration from: {args.config}")
        config = SystemConfig.from_file(args.config)
        config.ticker = ticker  # Override ticker
    else:
        print(f"Using default configuration")
        config = get_default_config(ticker)
    
    # Apply CLI overrides for data window
    if args.lookback_days is not None:
        config.data.lookback_days = args.lookback_days
    if args.min_bars is not None:
        config.data.min_trading_days = args.min_bars

    print(f"lookback_days: {config.data.lookback_days}")
    print(f"min_bars: {config.data.min_trading_days}")

    # Set random seeds
    set_random_seeds(config.random_seed)
    
    # Generate run ID and setup directory
    run_id = generate_run_id()
    run_dir = setup_run_directory(ticker, run_id, args.run_dir)
    
    git_sha = _get_git_sha()

    print(f"Run ID: {run_id}")
    print(f"RUN_ID={run_id}")
    print(f"Run Directory: {run_dir}\n")

    # Write _meta.json and initial STARTED state
    created_utc = _write_meta_json(run_dir, ticker, run_id, git_sha,
                                   as_of_date, replay_from)
    summary = _make_summary(ticker, run_id, git_sha, created_utc, 'STARTED',
                            as_of_date=as_of_date)
    _persist_summary(summary, run_dir)

    # Save configuration snapshot (JSON + YAML)
    config.save_to_file(os.path.join(run_dir, 'config.json'))
    _save_config_yaml(config, os.path.join(run_dir, 'config_snapshot.yaml'))

    # Create orchestrator logger
    logger = AgentLogger('Orchestrator', run_dir)
    logger.info(f"Starting run for {ticker}")
    logger.info(f"Run ID: {run_id}")
    logger.info(f"Configuration: {config.to_dict()}")

    # Run orchestrator
    try:
        orchestrator = OrchestratorAgent(config, run_dir, logger)
        result = orchestrator.run(
            mode=run_mode,
            as_of_date=as_of_date,
            replay_from=replay_from,
        )

        print(f"\n{'='*60}")
        print(f"Run Status: {result['status']}")
        print(f"{'='*60}\n")

        if result['status'] in ('SUCCESS', 'WARNING'):
            # Validate required outputs BEFORE writing SUCCESS
            missing = _check_required_outputs(run_dir)
            if missing:
                summary['status'] = 'FAILED'
                summary['error'] = f"Missing required output: {missing}"
                _persist_summary(summary, run_dir)
                print(f"[FAIL] {summary['error']}")
                return 1

            # All outputs present — populate decision
            _populate_decision(summary, run_dir)

            # Embed data snapshot metadata if snapshot exists
            from data.snapshot_store import snapshot_path, snapshot_metadata
            import pandas as pd
            snap_file = snapshot_path(run_dir)
            if os.path.exists(snap_file):
                snap_df = pd.read_parquet(snap_file, engine="pyarrow")
                summary.update(snapshot_metadata(snap_df))

            # Run edge validation BEFORE writing final status
            if args.skip_edge:
                print("\n[EDGE] Edge validation: SKIPPED (--skip-edge)")
                edge_pass = True
            else:
                edge_pass = _run_edge_validation(run_dir)
                edge_status = "PASS" if edge_pass else "FAIL"
                print(f"\n[EDGE] Edge validation: {edge_status}")
                print(f"  Edge report: {run_dir}/edge_report.txt")
                print(f"  Edge summary: {run_dir}/edge_summary.json")

                if not edge_pass:
                    edge_exit_code = _read_edge_exit_code(run_dir)
                    summary['status'] = 'FAILED'
                    if edge_exit_code == 2:
                        summary['error'] = 'Edge validation: missing or invalid artifacts'
                    else:
                        summary['error'] = 'Edge validation: gates failed'
                    _persist_summary(summary, run_dir)
                    print(f"\n[FAIL] Edge validation failed — run marked FAILED")
                    return edge_exit_code

            # Edge passed (or skipped) — write SUCCESS
            summary['status'] = 'SUCCESS'
            _persist_summary(summary, run_dir)
            _assert_persisted(run_dir, 'SUCCESS')

            print(f"\n[OK] All agents completed successfully")
            print(f"  Decision: {summary['decision']}  HasTrade: {summary['has_trade']}")
            print(f"\nFinal Report: {run_dir}/final_report.html")
            print(f"JSON Report: {run_dir}/final_report.json")
            print(f"Status: {run_dir}/status.txt")
            return 0

        else:
            summary['status'] = 'FAILED'
            summary['error'] = '; '.join(result.get('errors', ['Unknown error']))
            _populate_decision(summary, run_dir)
            _persist_summary(summary, run_dir)
            print("[FAIL] Run failed")
            print("\nErrors:")
            for error in result.get('errors', []):
                print(f"  - {error}")
            return 1

    except Exception as e:
        summary['status'] = 'FAILED'
        summary['error'] = str(e)
        _persist_summary(summary, run_dir)
        logger.error(f"Fatal error: {str(e)}")
        print(f"\n[FAIL] Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
