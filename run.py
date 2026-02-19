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


def _write_status_txt(run_dir: str, status: str, ticker: str, git_sha: str,
                      error: str = None):
    """Write/overwrite status.txt at run lifecycle boundaries."""
    with open(os.path.join(run_dir, 'status.txt'), 'w') as f:
        f.write(f"STATUS: {status}\n")
        f.write(f"TIMESTAMP: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"TICKER: {ticker}\n")
        f.write(f"Commit: {git_sha}\n")
        if error:
            f.write(f"ERROR: {error}\n")


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

    # Write _meta.json and initial status.txt (STARTED)
    _write_meta_json(run_dir, ticker, run_id, git_sha)
    _write_status_txt(run_dir, 'STARTED', ticker, git_sha)

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
        
        if result['status'] == 'SUCCESS':
            _write_status_txt(run_dir, 'SUCCESS', ticker, git_sha)
            print("[OK] All agents completed successfully")
            print(f"\nFinal Report: {run_dir}/final_report.html")
            print(f"JSON Report: {run_dir}/final_report.json")
            print(f"Status: {run_dir}/status.txt")
            return 0

        elif result['status'] == 'WARNING':
            _write_status_txt(run_dir, 'WARNING', ticker, git_sha)
            print("⚠ Completed with warnings")
            print(f"\nFinal Report: {run_dir}/final_report.html")
            print("\nWarnings:")
            for error in result.get('errors', []):
                print(f"  - {error}")
            return 0

        else:
            err_str = '; '.join(result.get('errors', ['Unknown error']))
            _write_status_txt(run_dir, 'FAILED', ticker, git_sha, error=err_str)
            print("[FAIL] Run failed")
            print("\nErrors:")
            for error in result.get('errors', []):
                print(f"  - {error}")
            return 1
    
    except Exception as e:
        _write_status_txt(run_dir, 'FAILED', ticker, git_sha, error=str(e))
        logger.error(f"Fatal error: {str(e)}")
        print(f"\n[FAIL] Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
