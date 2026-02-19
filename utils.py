"""
Utility functions for the stock forecasting system.
"""

import os
import json
import random
import string
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
import numpy as np
from loguru import logger


def generate_run_id() -> str:
    """Generate unique run ID with timestamp and random suffix."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{timestamp}_{suffix}"


def setup_run_directory(ticker: str, run_id: str, base_dir: str = "runs") -> str:
    """
    Create run directory structure.
    
    Returns:
        Path to run directory
    """
    run_dir = os.path.join(base_dir, ticker, run_id)
    
    # Create agent subdirectories
    agents = [
        "DataAgent",
        "FeatureAgent",
        "RegimeAgent",
        "EventModelAgent",
        "BacktestAgent",
        "StrategyAgent",
        "DecisionRiskAgent",
        "PortfolioAgent",
        "DashboardAgent",
        "MemoryLearningAgent",
    ]
    
    for agent in agents:
        os.makedirs(os.path.join(run_dir, agent), exist_ok=True)
    
    return run_dir


def save_agent_output(
    run_dir: str,
    agent_name: str,
    output_data: Dict[str, Any],
    logger_instance: Optional[Any] = None
) -> str:
    """Save agent output to output.json."""
    agent_dir = os.path.join(run_dir, agent_name)
    output_path = os.path.join(agent_dir, "output.json")
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2, default=str, sort_keys=True)
    
    if logger_instance:
        logger_instance.info(f"Saved output to {output_path}")
    
    return output_path


def load_agent_output(run_dir: str, agent_name: str) -> Dict[str, Any]:
    """Load agent output from output.json."""
    output_path = os.path.join(run_dir, agent_name, "output.json")
    
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Output not found: {output_path}")
    
    with open(output_path, 'r') as f:
        return json.load(f)


def set_random_seeds(seed: int = 42):
    """Set random seeds for reproducibility.

    Note: PYTHONHASHSEED must be set before the interpreter starts
    (e.g. via env var in the shell). We set it here too for documentation
    but it only takes effect if Python hasn't cached hash seeds yet.
    """
    os.environ['PYTHONHASHSEED'] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    # If using scikit-learn, models will use random_state parameter


def validate_data_leakage_test(
    features_df,
    labels_series,
    train_indices,
    test_indices,
    model,
    threshold: float = 0.05
) -> Dict[str, Any]:
    """
    Test for data leakage by shuffling labels.
    
    If performance doesn't degrade significantly with shuffled labels,
    there's likely leakage.
    
    Returns:
        Dict with test results
    """
    from sklearn.metrics import roc_auc_score
    
    # Original performance
    X_test = features_df.iloc[test_indices]
    y_test = labels_series.iloc[test_indices]
    
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    original_auc = roc_auc_score(y_test, y_pred_proba)
    
    # Shuffled labels performance
    y_test_shuffled = y_test.sample(frac=1, random_state=42).values
    shuffled_auc = roc_auc_score(y_test_shuffled, y_pred_proba)
    
    # Performance should collapse with shuffled labels
    degradation = original_auc - shuffled_auc
    
    passed = degradation > threshold
    
    return {
        "original_auc": float(original_auc),
        "shuffled_auc": float(shuffled_auc),
        "degradation": float(degradation),
        "threshold": threshold,
        "passed": passed,
        "message": "PASS: Model relies on true labels" if passed else "FAIL: Possible data leakage"
    }


def check_future_leakage_test(
    features_df,
    labels_series,
    shift_days: int = 5
) -> Dict[str, Any]:
    """
    Test that shifting labels forward destroys predictive relationship.
    
    Returns:
        Dict with test results
    """
    from scipy.stats import pearsonr
    
    # Calculate correlation between features and labels
    feature_cols = features_df.select_dtypes(include=[np.number]).columns
    
    # Original correlation
    original_corrs = []
    for col in feature_cols:
        if features_df[col].std() > 0:
            corr, _ = pearsonr(
                features_df[col].dropna(),
                labels_series[features_df[col].dropna().index]
            )
            original_corrs.append(abs(corr))
    
    original_max_corr = max(original_corrs) if original_corrs else 0
    
    # Shifted correlation (should be much weaker)
    labels_shifted = labels_series.shift(shift_days)
    valid_idx = features_df.index.intersection(labels_shifted.dropna().index)
    
    shifted_corrs = []
    for col in feature_cols:
        if features_df[col].std() > 0:
            valid = valid_idx.intersection(features_df[col].dropna().index)
            if len(valid) > 10:
                corr, _ = pearsonr(
                    features_df.loc[valid, col],
                    labels_shifted[valid]
                )
                shifted_corrs.append(abs(corr))
    
    shifted_max_corr = max(shifted_corrs) if shifted_corrs else 0
    
    # Shifted correlation should be significantly lower
    passed = shifted_max_corr < original_max_corr * 0.5
    
    return {
        "original_max_correlation": float(original_max_corr),
        "shifted_max_correlation": float(shifted_max_corr),
        "shift_days": shift_days,
        "passed": passed,
        "message": "PASS: Features don't predict shifted future" if passed else "FAIL: Possible future leakage"
    }


def calculate_sharpe_ratio(returns: np.ndarray, periods_per_year: int = 252) -> float:
    """Calculate annualized Sharpe ratio."""
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    return (returns.mean() / returns.std()) * np.sqrt(periods_per_year)


def calculate_max_drawdown(equity_curve: np.ndarray) -> float:
    """Calculate maximum drawdown from equity curve."""
    cummax = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - cummax) / cummax
    return float(drawdown.min())


def format_hebrew_rtl(text: str) -> str:
    """Wrap Hebrew text with RTL direction marker."""
    return f'<span dir="rtl">{text}</span>'


class AgentLogger:
    """Logger wrapper for agents."""
    
    def __init__(self, agent_name: str, run_dir: str):
        self.agent_name = agent_name
        self.log_file = os.path.join(run_dir, agent_name, "agent.log")
        
        # Configure logger
        logger.add(
            self.log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            level="DEBUG",
            rotation="10 MB"
        )
        
        self.logger = logger
    
    def info(self, message: str):
        self.logger.info(f"[{self.agent_name}] {message}")
    
    def warning(self, message: str):
        self.logger.warning(f"[{self.agent_name}] {message}")
    
    def error(self, message: str):
        self.logger.error(f"[{self.agent_name}] {message}")
    
    def debug(self, message: str):
        self.logger.debug(f"[{self.agent_name}] {message}")
