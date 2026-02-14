"""
Multi-Agent Stock Forecasting System

A production-grade system for event-based stock forecasting with strict safety gates.
"""

__version__ = '1.0.0'
__author__ = 'Multi-Agent Forecasting Team'

from .config import SystemConfig, get_default_config
from .agents import OrchestratorAgent

__all__ = [
    'SystemConfig',
    'get_default_config',
    'OrchestratorAgent'
]
