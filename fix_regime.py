# fix_regime.py - תיקון RegimeAgent
print("🔧 מתקן את RegimeAgent...")

fixed_code = '''"""
RegimeAgent - Labels market regimes (trend/range, vol).
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from .base_agent import BaseAgent


class RegimeAgent(BaseAgent):
    """Agent responsible for market regime detection."""
    
    def run(self) -> Dict[str, Any]:
        """Label market regimes."""
        self.logger.info("Starting regime detection")
        
        try:
            # Load data
            data_output = self.load_agent_output('DataAgent')
            
            if data_output['status'] != 'SUCCESS':
                return {
                    'status': 'FAILED',
                    'error': 'DataAgent failed, cannot detect regimes'
                }
            
            df = pd.read_parquet(data_output['data_path'])
            
            # Detect regimes
            regime_series = self._detect_regimes(df)
            
            # Create regime definition
            regime_def = self._create_regime_definition(regime_series)
            
            # Save artifacts
            self.save_artifact('regime_series.parquet', regime_series.to_frame('regime'))
            self.save_artifact('regime_definition.json', regime_def)
            
            # Prepare output
            output = {
                'status': 'SUCCESS',
                'regime_path': self.get_artifact_path('regime_series.parquet'),
                'regime_definition': regime_def
            }
            
            self.save_output(output)
            self.logger.info("Regime detection complete")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Regime detection failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _detect_regimes(self, df: pd.DataFrame) -> pd.Series:
        """
        Detect market regimes using simple, transparent rules.
        
        Regimes:
        - TREND_LOW_VOL: trending with low volatility
        - TREND_HIGH_VOL: trending with high volatility
        - RANGE_LOW_VOL: ranging with low volatility
        - RANGE_HIGH_VOL: ranging with high volatility
        """
        close = df['Close']
        
        # Trend detection: fast MA vs slow MA
        ma_fast = close.rolling(self.config.regime.trend_ma_fast).mean()
        ma_slow = close.rolling(self.config.regime.trend_ma_slow).mean()
        
        is_trending = (ma_fast > ma_slow * 1.01) | (ma_fast < ma_slow * 0.99)
        
        # Volatility detection
        returns = close.pct_change()
        vol_window = self.config.regime.vol_window
        realized_vol = returns.rolling(vol_window).std()
        median_vol = realized_vol.rolling(vol_window * 3).median()
        
        is_high_vol = realized_vol > median_vol * self.config.regime.vol_threshold
        
        # Combine into regime labels
        regime = pd.Series(index=df.index, dtype=str)
        
        # Shift by 1 to avoid look-ahead bias
        is_trending_shifted = is_trending.shift(1).fillna(False)
        is_high_vol_shifted = is_high_vol.shift(1).fillna(False)
        
        regime.loc[is_trending_shifted & ~is_high_vol_shifted] = 'TREND_LOW_VOL'
        regime.loc[is_trending_shifted & is_high_vol_shifted] = 'TREND_HIGH_VOL'
        regime.loc[~is_trending_shifted & ~is_high_vol_shifted] = 'RANGE_LOW_VOL'
        regime.loc[~is_trending_shifted & is_high_vol_shifted] = 'RANGE_HIGH_VOL'
        
        # Fill any NaN with UNKNOWN
        regime = regime.fillna('UNKNOWN')
        
        return regime
    
    def _create_regime_definition(self, regime_series: pd.Series) -> Dict[str, Any]:
        """Create regime definition with statistics."""
        # Count occurrences
        regime_counts = regime_series.value_counts().to_dict()
        regime_pcts = (regime_series.value_counts(normalize=True) * 100).to_dict()
        
        # Recent regime
        recent_regime = regime_series.iloc[-1] if len(regime_series) > 0 else 'UNKNOWN'
        
        return {
            'regimes': [
                'TREND_LOW_VOL',
                'TREND_HIGH_VOL',
                'RANGE_LOW_VOL',
                'RANGE_HIGH_VOL',
                'UNKNOWN'
            ],
            'regime_counts': regime_counts,
            'regime_percentages': {k: float(v) for k, v in regime_pcts.items()},
            'recent_regime': recent_regime,
            'detection_rules': {
                'trend_ma_fast': self.config.regime.trend_ma_fast,
                'trend_ma_slow': self.config.regime.trend_ma_slow,
                'vol_threshold': self.config.regime.vol_threshold,
                'vol_window': self.config.regime.vol_window
            }
        }
'''

# שמור את הקובץ
with open('agents/regime_agent.py', 'w', encoding='utf-8') as f:
    f.write(fixed_code)

print("✅ RegimeAgent תוקן!")
print("\nעכשיו הריצי:")
print("python run.py --ticker PLTR")