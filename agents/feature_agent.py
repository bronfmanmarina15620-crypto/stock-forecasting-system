"""
FeatureAgent - Generates features strictly as-of time.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from .base_agent import BaseAgent


class FeatureAgent(BaseAgent):
    """Agent responsible for feature engineering."""
    
    def run(self) -> Dict[str, Any]:
        """Generate features from price data."""
        self.logger.info("Starting feature generation")
        
        try:
            # Load data from DataAgent
            data_output = self.load_agent_output('DataAgent')
            
            if data_output['status'] != 'SUCCESS':
                return {
                    'status': 'FAILED',
                    'error': 'DataAgent failed, cannot generate features'
                }
            
            # Load price data
            df = pd.read_parquet(data_output['data_path'])
            
            # Generate features
            features_df = self._generate_features(df)
            
            # Create feature manifest
            feature_manifest = self._create_feature_manifest(features_df)
            
            # Save artifacts
            feature_path = self.save_artifact(
                f"features_{self.config.features.feature_set_id}.parquet",
                features_df
            )
            self.save_artifact('feature_manifest.json', feature_manifest)
            
            # Prepare output
            output = {
                'status': 'SUCCESS',
                'feature_set_id': self.config.features.feature_set_id,
                'features_path': feature_path,
                'feature_count': len(feature_manifest['features']),
                'sample_count': len(features_df),
                'feature_manifest': feature_manifest
            }
            
            self.save_output(output)
            self.logger.info(f"Generated {output['feature_count']} features")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Feature generation failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _generate_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate all features strictly as-of time.
        
        CRITICAL: All features must be calculable using only past data.
        """
        features = pd.DataFrame(index=df.index)
        
        # Price-based features
        close = df['Close']
        high = df['High']
        low = df['Low']
        volume = df['Volume']
        
        # Returns (lagged to avoid leakage)
        for window in self.config.features.return_windows:
            features[f'return_{window}d'] = close.pct_change(window).shift(1)
        
        # Gap (today's open vs yesterday's close)
        features['gap'] = (df['Open'] / close.shift(1) - 1).shift(1)
        
        # Volatility (realized)
        for window in self.config.features.vol_windows:
            returns = close.pct_change()
            features[f'vol_{window}d'] = returns.rolling(window).std().shift(1)
        
        # ATR (Average True Range)
        atr_window = self.config.features.atr_window
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        features['atr'] = tr.rolling(atr_window).mean().shift(1)
        features['atr_pct'] = (features['atr'] / close.shift(1))
        
        # Moving averages
        for window in self.config.features.ma_windows:
            ma = close.rolling(window).mean()
            features[f'ma_{window}'] = (close.shift(1) / ma.shift(1) - 1)
            
            # MA slope
            ma_slope = ma.diff(5) / ma
            features[f'ma_{window}_slope'] = ma_slope.shift(1)
        
        # Volume features
        vol_window = self.config.features.volume_zscore_window
        vol_mean = volume.rolling(vol_window).mean()
        vol_std = volume.rolling(vol_window).std()
        features['volume_zscore'] = ((volume.shift(1) - vol_mean.shift(1)) / vol_std.shift(1))
        
        # Relative volume
        features['rel_volume'] = (volume.shift(1) / vol_mean.shift(1))
        
        # Price momentum
        features['momentum_20'] = (close.shift(1) / close.shift(21) - 1)
        features['momentum_60'] = (close.shift(1) / close.shift(61) - 1)
        
        # Range features
        features['high_low_range'] = ((high - low) / close).shift(1)
        features['close_position'] = ((close - low) / (high - low)).shift(1)
        
        # Drop NaN rows (from rolling calculations)
        features = features.dropna()
        
        return features
    
    def _create_feature_manifest(self, features_df: pd.DataFrame) -> Dict[str, Any]:
        """Create manifest describing all features."""
        feature_list = []
        
        for col in features_df.columns:
            feature_list.append({
                'name': col,
                'dtype': str(features_df[col].dtype),
                'missing_pct': float(features_df[col].isnull().sum() / len(features_df) * 100),
                'mean': float(features_df[col].mean()),
                'std': float(features_df[col].std()),
                'min': float(features_df[col].min()),
                'max': float(features_df[col].max())
            })
        
        return {
            'feature_set_id': self.config.features.feature_set_id,
            'feature_count': len(feature_list),
            'features': feature_list,
            'generation_rules': {
                'return_windows': self.config.features.return_windows,
                'vol_windows': self.config.features.vol_windows,
                'ma_windows': self.config.features.ma_windows,
                'atr_window': self.config.features.atr_window
            }
        }
