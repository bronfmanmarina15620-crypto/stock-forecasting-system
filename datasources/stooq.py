"""
Stooq data source adapter (backup).
This is a stub implementation.
"""

import pandas as pd
from datetime import datetime
from .base import DataSourceAdapter


class StooqAdapter(DataSourceAdapter):
    """Adapter for Stooq data (stub implementation)."""
    
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from Stooq.
        
        Note: This is a stub implementation.
        To use Stooq, install pandas_datareader and implement the logic.
        """
        raise NotImplementedError(
            "Stooq adapter is a stub. "
            "Install pandas_datareader and implement fetch_ohlcv method."
        )
    
    def is_available(self) -> bool:
        """Check if Stooq is available."""
        try:
            import pandas_datareader as pdr
            return True
        except ImportError:
            return False
