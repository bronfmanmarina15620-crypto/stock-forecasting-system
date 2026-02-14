"""
Yahoo Finance data source adapter.
"""

import pandas as pd
from datetime import datetime
from typing import Optional
from .base import DataSourceAdapter


class YahooFinanceAdapter(DataSourceAdapter):
    """Adapter for Yahoo Finance data."""
    
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Fetch OHLCV data from Yahoo Finance."""
        # Check cache first
        cached_data = self.load_from_cache(ticker)
        if cached_data is not None:
            # Make sure dates are timezone-naive for comparison
            if cached_data.index.tz is not None:
                cached_data.index = cached_data.index.tz_localize(None)
            
            # Filter to requested date range
            mask = (cached_data.index >= start_date) & (cached_data.index <= end_date)
            return cached_data[mask].copy()
        
        try:
            import yfinance as yf
            
            # Download data
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date, auto_adjust=True)
            
            if df.empty:
                raise ValueError(f"No data returned for {ticker}")
            
            # Standardize column names
            df = df.rename(columns={
                'Open': 'Open',
                'High': 'High',
                'Low': 'Low',
                'Close': 'Close',
                'Volume': 'Volume'
            })
            
            # Keep only OHLCV columns
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            
            # Ensure index is datetime and timezone-naive
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df.index.name = 'Date'
            
            # Save to cache
            self.save_to_cache(ticker, df)
            
            return df
            
        except Exception as e:
            raise RuntimeError(f"Failed to fetch data from Yahoo Finance: {str(e)}")
    
    def is_available(self) -> bool:
        """Check if Yahoo Finance is available."""
        try:
            import yfinance as yf
            # Try a simple test
            test = yf.Ticker("AAPL")
            test.info  # This will fail if API is down
            return True
        except:
            return False
