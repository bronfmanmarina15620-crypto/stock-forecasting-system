#!/usr/bin/env python3
"""
Main CLI entrypoint for the stock forecasting system.

Usage:
    python run.py --ticker PLTR
    python run.py --ticker PLTR --config custom_config.json
"""

import argparse
import subprocess
import sys
import os
import json
from datetime import datetime, timezone

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


def _write_meta_json(run_dir: str, ticker: str, run_id: str, git_sha: str):
    """Write _meta.json immediately after run dir creation."""
    meta = {
        'ticker': ticker,
        'run_id': run_id,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'git_sha': git_sha,
    }
    with open(os.path.join(run_dir, '_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2)
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
                  status: str, error: str = None) -> dict:
    """Build a summary dict. Decision/trade fields left at defaults."""
    return {
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
    summary['finished_utc'] = datetime.now(timezone.utc).isoformat()

    with open(os.path.join(run_dir, 'run_summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(run_dir, 'status.txt'), 'w') as f:
        f.write(f"STATUS: {summary['status']}\n")
        f.write(f"TIMESTAMP: {summary['finished_utc']}\n")
        f.write(f"TICKER: {summary['ticker']}\n")
        f.write(f"Commit: {summary['git_sha']}\n")
        if summary.get('error'):
            f.write(f"ERROR: {summary['error']}\n")


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
    
    args = parser.parse_args()
    
    # Check multi-ticker mode
    if args.tickers:
        print("⚠️  Multi-ticker mode is not active yet. Using single-ticker mode.")
        print(f"⚠️  Only the first ticker will be used.")
        tickers = args.tickers.split(',')
        ticker = tickers[0].strip()
    else:
        ticker = args.ticker
    
    print(f"\n{'='*60}")
    print(f"Multi-Agent Stock Forecasting System")
    print(f"{'='*60}")
    print(f"Ticker: {ticker}")
    print(f"Mode: SINGLE-TICKER (PLTR ONLY)")
    print(f"{'='*60}\n")
    
    # Load or create configuration
    if args.config and os.path.exists(args.config):
        print(f"Loading configuration from: {args.config}")
        config = SystemConfig.from_file(args.config)
        config.ticker = ticker  # Override ticker
    else:
        print(f"Using default configuration")
        config = get_default_config(ticker)
    
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
    created_utc = _write_meta_json(run_dir, ticker, run_id, git_sha)
    summary = _make_summary(ticker, run_id, git_sha, created_utc, 'STARTED')
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
        result = orchestrator.run()

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

            # All outputs present — populate decision, write SUCCESS
            _populate_decision(summary, run_dir)
            summary['status'] = 'SUCCESS'
            _persist_summary(summary, run_dir)
            _assert_persisted(run_dir, 'SUCCESS')

            print(f"[OK] All agents completed successfully")
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
