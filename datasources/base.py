"""
Base interface for data source adapters.
"""

import os
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd
from datetime import datetime


class DataSourceAdapter(ABC):
    """Base class for all data source adapters."""
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir
        self.name = self.__class__.__name__
    
    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for a ticker.
        
        Returns:
            DataFrame with columns: Date (index), Open, High, Low, Close, Volume
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if data source is available."""
        pass
    
    def get_cache_path(self, ticker: str) -> Optional[str]:
        """Get cache file path for ticker."""
        if self.cache_dir is None:
            return None
        os.makedirs(self.cache_dir, exist_ok=True)
        return os.path.join(self.cache_dir, f"{ticker}_{self.name}.parquet")
    
    def load_from_cache(self, ticker: str) -> Optional[pd.DataFrame]:
        """Load data from cache if available."""
        cache_path = self.get_cache_path(ticker)
        if cache_path and os.path.exists(cache_path):
            # Check if cache is recent (less than 1 day old)
            cache_age_hours = (datetime.now().timestamp() - os.path.getmtime(cache_path)) / 3600
            if cache_age_hours < 24:
                return pd.read_parquet(cache_path)
        return None
    
    def save_to_cache(self, ticker: str, data: pd.DataFrame):
        """Save data to cache."""
        cache_path = self.get_cache_path(ticker)
        if cache_path:
            data.to_parquet(cache_path)
