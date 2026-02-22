"""
DataAgent - Fetches and validates market data.

Supports:
  - Live fetch with as_of_date (end_date for data window)
  - Replay mode: loads frozen data_snapshot.parquet from a source run
  - Always saves a normalized data_snapshot.parquet + snapshot_hash.txt
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from datetime import date, datetime, timedelta
from .base_agent import BaseAgent
from datasources import YahooFinanceAdapter, StooqAdapter
from data.snapshot_store import (
    save_snapshot,
    load_snapshot,
    snapshot_metadata,
    snapshot_path,
    resolve_replay_path,
)


class DataAgent(BaseAgent):
    """Agent responsible for data fetching and quality validation."""

    def run(self, *, as_of_date: Optional[date] = None,
            replay_from: Optional[str] = None) -> Dict[str, Any]:
        """Fetch and validate market data.

        Parameters
        ----------
        as_of_date : date, optional
            End date for the data window. Defaults to today.
        replay_from : str, optional
            Path to source run directory. If set, loads snapshot
            from that run instead of fetching live data.
        """
        self.logger.info(f"Starting data fetch for {self.config.ticker}")

        try:
            if replay_from:
                # Replay mode: load frozen snapshot
                # resolve_replay_path accepts both a run dir and a direct .parquet path
                resolved = resolve_replay_path(replay_from)
                self.logger.info(f"Replay mode: loading snapshot from {resolved}")
                from data.snapshot_store import normalize_df
                df_raw = normalize_df(pd.read_parquet(resolved, engine="pyarrow"))
                self.logger.info(f"Loaded snapshot: {len(df_raw)} bars")
            else:
                # Live mode: fetch from data sources
                if as_of_date is None:
                    as_of_date = date.today()

                end_date = datetime.combine(as_of_date, datetime.max.time())
                start_date = end_date - timedelta(days=self.config.data.lookback_days)

                df_raw = self._fetch_data_with_fallback(
                    self.config.ticker,
                    start_date,
                    end_date
                )

            # Validate data quality
            quality_report = self._validate_data_quality(df_raw)

            # If critical issues, fail
            if not quality_report['passed']:
                self.logger.error("Data quality check FAILED")
                return {
                    'status': 'FAILED',
                    'error': 'Data quality validation failed',
                    'quality_report': quality_report
                }

            # Apply adjustments (already done by yfinance auto_adjust=True)
            df_adj = df_raw.copy()

            # Save data snapshot (normalized, deterministic)
            snap_sha = save_snapshot(df_raw, self.run_dir)
            self.logger.info(f"Saved data snapshot: sha256={snap_sha[:16]}...")

            # Save legacy artifacts
            self.save_artifact('bars_raw.parquet', df_raw)
            self.save_artifact('bars_adj.parquet', df_adj)
            self.save_artifact('quality_report.json', quality_report)

            # Prepare output
            snap_meta = snapshot_metadata(df_raw)
            output = {
                'status': 'SUCCESS',
                'ticker': self.config.ticker,
                'start_date': str(df_raw.index.min().date()),
                'end_date': str(df_raw.index.max().date()),
                'bars_count': len(df_adj),
                'data_path': self.get_artifact_path('bars_adj.parquet'),
                'quality_report': quality_report,
                'replay_mode': replay_from is not None,
            }
            output.update(snap_meta)

            self.save_output(output)
            self.logger.info(f"Data fetch complete: {len(df_adj)} bars")

            return output

        except Exception as e:
            self.logger.error(f"Data fetch failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }

    def _fetch_data_with_fallback(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Fetch data with fallback to backup sources."""
        # Try primary source
        primary_adapter = YahooFinanceAdapter(
            cache_dir=self.config.data.cache_dir if self.config.data.cache_enabled else None
        )

        try:
            if primary_adapter.is_available():
                self.logger.info(f"Fetching from primary source: {primary_adapter.name}")
                df = primary_adapter.fetch_ohlcv(ticker, start_date, end_date)

                if len(df) >= self.config.data.min_trading_days:
                    return df
                else:
                    raise ValueError(f"Insufficient data: {len(df)} bars")

        except Exception as e:
            self.logger.warning(f"Primary source failed: {str(e)}")

        # Try backup sources
        for backup_name in self.config.data.backup_sources:
            try:
                if backup_name == "stooq":
                    adapter = StooqAdapter()
                else:
                    continue

                if adapter.is_available():
                    self.logger.info(f"Trying backup source: {adapter.name}")
                    df = adapter.fetch_ohlcv(ticker, start_date, end_date)

                    if len(df) >= self.config.data.min_trading_days:
                        return df

            except Exception as e:
                self.logger.warning(f"Backup source {backup_name} failed: {str(e)}")

        raise RuntimeError("All data sources failed")

    def _validate_data_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate data quality and detect issues."""
        issues = []
        warnings = []

        # Check minimum bars
        if len(df) < self.config.data.min_trading_days:
            issues.append(f"Insufficient data: {len(df)} < {self.config.data.min_trading_days}")

        # Check for missing values
        missing_pct = (df.isnull().sum() / len(df) * 100).to_dict()
        for col, pct in missing_pct.items():
            if pct > 5:
                issues.append(f"High missing values in {col}: {pct:.1f}%")
            elif pct > 0:
                warnings.append(f"Missing values in {col}: {pct:.1f}%")

        # Check for duplicates
        duplicates = df.index.duplicated().sum()
        if duplicates > 0:
            issues.append(f"Duplicate dates: {duplicates}")

        # Check for outliers (extreme price movements)
        returns = df['Close'].pct_change()
        extreme_returns = returns[abs(returns) > 0.50]  # >50% daily move
        if len(extreme_returns) > 0:
            warnings.append(f"Extreme returns detected: {len(extreme_returns)} days")

        # Check for zero volume
        zero_volume_days = (df['Volume'] == 0).sum()
        if zero_volume_days > 0:
            warnings.append(f"Zero volume days: {zero_volume_days}")

        # Check for negative prices
        if (df[['Open', 'High', 'Low', 'Close']] <= 0).any().any():
            issues.append("Negative or zero prices detected")

        # Check for impossible OHLC relationships
        invalid_ohlc = (
            (df['High'] < df['Low']) |
            (df['High'] < df['Open']) |
            (df['High'] < df['Close']) |
            (df['Low'] > df['Open']) |
            (df['Low'] > df['Close'])
        ).sum()

        if invalid_ohlc > 0:
            issues.append(f"Invalid OHLC relationships: {invalid_ohlc}")

        passed = len(issues) == 0

        return {
            'passed': passed,
            'issues': issues,
            'warnings': warnings,
            'bars_count': len(df),
            'date_range': {
                'start': str(df.index.min().date()),
                'end': str(df.index.max().date())
            },
            'missing_values': missing_pct
        }
