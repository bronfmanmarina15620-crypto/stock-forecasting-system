#!/usr/bin/env python3
"""
Main CLI entrypoint for the stock forecasting system.

Usage:
    python run.py --ticker PLTR
    python run.py --ticker PLTR --config custom_config.json
"""

import argparse
import sys
import os
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SystemConfig, get_default_config
from utils import generate_run_id, setup_run_directory, set_random_seeds, AgentLogger
from agents import OrchestratorAgent


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
    
    print(f"Run ID: {run_id}")
    print(f"Run Directory: {run_dir}\n")
    
    # Save configuration snapshot
    config.save_to_file(os.path.join(run_dir, 'config.json'))
    
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
            print("✓ All agents completed successfully")
            print(f"\nFinal Report: {run_dir}/final_report.html")
            print(f"JSON Report: {run_dir}/final_report.json")
            print(f"Status: {run_dir}/status.txt")
            return 0
        
        elif result['status'] == 'WARNING':
            print("⚠ Completed with warnings")
            print(f"\nFinal Report: {run_dir}/final_report.html")
            print("\nWarnings:")
            for error in result.get('errors', []):
                print(f"  - {error}")
            return 0
        
        else:
            print("✗ Run failed")
            print("\nErrors:")
            for error in result.get('errors', []):
                print(f"  - {error}")
            return 1
    
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        print(f"\n✗ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
