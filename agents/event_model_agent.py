"""
EventModelAgent - Trains probabilistic model for event prediction.
"""

import pandas as pd
import numpy as np
import pickle
from typing import Dict, Any
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, classification_report
from .base_agent import BaseAgent


class EventModelAgent(BaseAgent):
    """Agent responsible for event model training."""
    
    def run(self) -> Dict[str, Any]:
        """Train event prediction model."""
        self.logger.info("Starting event model training")
        
        try:
            # Load dependencies
            data_output = self.load_agent_output('DataAgent')
            feature_output = self.load_agent_output('FeatureAgent')
            
            if data_output['status'] != 'SUCCESS' or feature_output['status'] != 'SUCCESS':
                return {
                    'status': 'FAILED',
                    'error': 'Dependencies failed'
                }
            
            # Load data
            df = pd.read_parquet(data_output['data_path'])
            features_df = pd.read_parquet(feature_output['features_path'])
            
            # Create event labels
            labels = self._create_event_labels(df)
            
            # Align features and labels
            common_idx = features_df.index.intersection(labels.index)
            X = features_df.loc[common_idx]
            y = labels.loc[common_idx]
            
            # Train model
            model, calibration_info = self._train_model(X, y)
            
            # Create model card
            model_card = self._create_model_card(model, X, y, calibration_info)
            
            # Save artifacts
            model_path = self.save_artifact('event_model.pkl', None)
            with open(model_path, 'wb') as f:
                pickle.dump(model, f)
            
            self.save_artifact('calibration.json', calibration_info)
            self.save_artifact('model_card.md', model_card)
            
            # Prepare output
            output = {
                'status': 'SUCCESS',
                'model_path': model_path,
                'event_name': self.config.event.event_name,
                'event_definition': f"{self.config.event.forward_window}-day return >= {self.config.event.threshold_pct}%",
                'calibration_info': calibration_info
            }
            
            self.save_output(output)
            self.logger.info("Event model training complete")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Event model training failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _create_event_labels(self, df: pd.DataFrame) -> pd.Series:
        """
        Create event labels looking forward.
        
        CRITICAL: Labels must be strictly forward-looking.
        """
        close = df['Close']
        
        # Calculate forward return
        forward_return = close.shift(-self.config.event.forward_window) / close - 1
        
        # Create binary label
        threshold = self.config.event.threshold_pct / 100
        labels = (forward_return >= threshold).astype(int)
        
        # Drop last N rows (no forward data available)
        labels = labels.iloc[:-self.config.event.forward_window]
        
        return labels
    
    def _train_model(self, X: pd.DataFrame, y: pd.Series) -> tuple:
        """Train and calibrate model."""
        # Use only first 80% for training (last 20% reserved for final testing)
        split_idx = int(len(X) * 0.8)
        X_train = X.iloc[:split_idx]
        y_train = y.iloc[:split_idx]
        
        # Train base model
        base_model = LogisticRegression(
            random_state=self.config.random_seed,
            max_iter=1000,
            class_weight='balanced'
        )
        base_model.fit(X_train, y_train)
        
        # Calibrate probabilities
        if self.config.event.calibration_method == 'isotonic':
            model = CalibratedClassifierCV(base_model, method='isotonic', cv=5)
        else:
            model = CalibratedClassifierCV(base_model, method='sigmoid', cv=5)
        
        model.fit(X_train, y_train)
        
        # Evaluate calibration on training set
        y_pred_proba = model.predict_proba(X_train)[:, 1]
        
        calibration_info = {
            'method': self.config.event.calibration_method,
            'train_auc': float(roc_auc_score(y_train, y_pred_proba)),
            'base_rate': float(y_train.mean()),
            'calibration_curve': self._get_calibration_curve(y_train, y_pred_proba)
        }
        
        return model, calibration_info
    
    def _get_calibration_curve(self, y_true: pd.Series, y_pred_proba: np.ndarray) -> Dict[str, list]:
        """Get calibration curve data."""
        from sklearn.calibration import calibration_curve
        
        prob_true, prob_pred = calibration_curve(y_true, y_pred_proba, n_bins=10, strategy='quantile')
        
        return {
            'predicted_probabilities': prob_pred.tolist(),
            'true_frequencies': prob_true.tolist()
        }
    
    def _create_model_card(
        self,
        model: Any,
        X: pd.DataFrame,
        y: pd.Series,
        calibration_info: Dict[str, Any]
    ) -> str:
        """Create model card documentation."""
        # Feature importance
        if hasattr(model.calibrated_classifiers_[0].estimator, 'coef_'):
            feature_importance = pd.DataFrame({
                'feature': X.columns,
                'coefficient': model.calibrated_classifiers_[0].estimator.coef_[0]
            })
            feature_importance['abs_coef'] = abs(feature_importance['coefficient'])
            feature_importance = feature_importance.sort_values('abs_coef', ascending=False)
            top_features = feature_importance.head(10).to_string()
        else:
            top_features = "N/A"
        
        card = f"""# Event Model Card

## Model Information
- **Event**: {self.config.event.event_name}
- **Definition**: {self.config.event.forward_window}-day return >= {self.config.event.threshold_pct}%
- **Model Type**: {self.config.event.model_type}
- **Calibration Method**: {self.config.event.calibration_method}

## Training Data
- **Samples**: {len(X)}
- **Features**: {len(X.columns)}
- **Base Rate**: {calibration_info['base_rate']:.3f}

## Performance
- **Training AUC**: {calibration_info['train_auc']:.3f}

## Top Features
```
{top_features}
```

## Calibration
Calibration method: {self.config.event.calibration_method}

## Usage Notes
- Model outputs probabilities, not point predictions
- Probabilities are calibrated to represent true frequencies
- Use with caution outside training distribution
"""
        return card
