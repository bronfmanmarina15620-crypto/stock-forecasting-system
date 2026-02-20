"""
Configuration module for stock forecasting system.
All settings, parameters, and constants.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
from datetime import datetime
import json
import os


@dataclass
class DataConfig:
    """Data fetching and processing configuration."""
    lookback_days: int = 730  # 2 years of historical data
    primary_source: str = "yahoo"
    backup_sources: List[str] = field(default_factory=lambda: ["stooq"])
    cache_enabled: bool = True
    cache_dir: str = "data_cache"
    validate_bars: bool = True
    min_trading_days: int = 252  # Minimum days required


@dataclass
class FeatureConfig:
    """Feature engineering configuration."""
    feature_set_id: str = "v1"
    return_windows: List[int] = field(default_factory=lambda: [1, 5, 10, 20])
    vol_windows: List[int] = field(default_factory=lambda: [10, 20, 60])
    ma_windows: List[int] = field(default_factory=lambda: [20, 50, 200])
    volume_zscore_window: int = 60
    atr_window: int = 14


@dataclass
class EventConfig:
    """Event definition configuration."""
    event_name: str = "UP_EVENT"
    forward_window: int = 5  # Days to look forward
    threshold_pct: float = 2.0  # +2% return
    model_type: str = "logistic"  # logistic, random_forest, etc.
    calibration_method: str = "isotonic"  # platt, isotonic


@dataclass
class RegimeConfig:
    """Market regime detection configuration."""
    trend_ma_fast: int = 20
    trend_ma_slow: int = 50
    vol_threshold: float = 1.5  # Multiple of median vol
    vol_window: int = 60


@dataclass
class BacktestConfig:
    """Backtesting configuration."""
    initial_train_days: int = 252  # 1 year
    test_window_days: int = 63  # ~3 months
    step_days: int = 21  # ~1 month
    min_test_samples: int = 20
    
    # Trading frictions
    commission_pct: float = 0.001  # 0.1% per trade
    spread_bps: float = 2.0  # 2 basis points
    slippage_bps: float = 3.0  # 3 basis points
    execution_assumption: str = "eod"  # eod, open
    backtest_mode: str = "signals_only"  # "signals_only" (default) or "legacy_ml"


@dataclass
class DecisionConfig:
    """Decision and risk configuration."""
    default_action: str = "ABSTAIN"
    probability_threshold: float = 0.60  # Enter if P(event) > 60%
    min_calibration_confidence: float = 0.7
    allowed_regimes: List[str] = field(default_factory=lambda: ["TREND_LOW_VOL", "TREND_HIGH_VOL"])
    max_signals_per_month: int = 10


@dataclass
class PortfolioConfig:
    """Portfolio management configuration (PASSIVE MODE)."""
    mode: str = "PASSIVE"  # PASSIVE or ACTIVE
    initial_capital: float = 100000.0
    max_position_size_pct: float = 0.20  # 20% max per position
    max_portfolio_drawdown_pct: float = 0.15  # 15% max drawdown
    cash_buffer_pct: float = 0.10  # Keep 10% in cash
    rebalance_frequency: str = "monthly"  # daily, weekly, monthly


@dataclass
class StrategyConfig:
    """Phase 2 MA150+ATR strategy parameters.

    Defaults mirror config/strategy.yaml (the human-readable source of truth).
    Costs are NOT duplicated here; they live in BacktestConfig.
    """
    atr_length: int = 14
    atr_mult: float = 3.0
    slope_lookback: int = 20
    entry_lookback: int = 20
    atr_pct_high: float = 0.04
    slope_min: float = 0.0
    risk_per_trade: float = 0.005  # placeholder for Phase 4


@dataclass
class MemoryConfig:
    """Memory and learning configuration."""
    db_path: str = "memory/memory_db.sqlite"
    enable_learning: bool = True
    auto_apply_suggestions: bool = False  # MUST be False
    review_frequency_days: int = 30


def _load_strategy_yaml(filepath: str) -> Dict[str, Any]:
    """Load strategy parameters from YAML.  Falls back to empty dict."""
    try:
        import yaml
        with open(filepath, 'r') as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return {}
    # Only extract keys recognised by StrategyConfig (skip 'costs' block)
    allowed = {f.name for f in StrategyConfig.__dataclass_fields__.values()}
    return {k: v for k, v in raw.items() if k in allowed}


@dataclass
class SystemConfig:
    """Overall system configuration."""
    ticker: str = "PLTR"
    tickers: List[str] = field(default_factory=lambda: ["PLTR"])  # Multi-ticker ready
    multi_ticker_enabled: bool = False
    random_seed: int = 42
    n_jobs: int = -1  # CPU cores for parallel processing
    log_level: str = "INFO"
    
    # Sub-configs
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    event: EventConfig = field(default_factory=EventConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)
    
    def save_to_file(self, filepath: str):
        """Save configuration to JSON file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SystemConfig':
        """Load configuration from dictionary."""
        # Reconstruct nested configs
        data['data'] = DataConfig(**data.get('data', {}))
        data['features'] = FeatureConfig(**data.get('features', {}))
        data['event'] = EventConfig(**data.get('event', {}))
        data['regime'] = RegimeConfig(**data.get('regime', {}))
        data['backtest'] = BacktestConfig(**data.get('backtest', {}))
        data['decision'] = DecisionConfig(**data.get('decision', {}))
        data['portfolio'] = PortfolioConfig(**data.get('portfolio', {}))
        data['memory'] = MemoryConfig(**data.get('memory', {}))
        data['strategy'] = StrategyConfig(**data.get('strategy', {}))
        return cls(**data)
    
    @classmethod
    def from_file(cls, filepath: str) -> 'SystemConfig':
        """Load configuration from JSON file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)


def get_default_config(ticker: str = "PLTR") -> SystemConfig:
    """Get default configuration for a ticker.

    If config/strategy.yaml exists, its values override StrategyConfig defaults.
    """
    # Try loading strategy YAML relative to this file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(base_dir, "config", "strategy.yaml")
    strategy_overrides = _load_strategy_yaml(yaml_path)

    config = SystemConfig(strategy=StrategyConfig(**strategy_overrides))
    config.ticker = ticker
    config.tickers = [ticker]
    return config
