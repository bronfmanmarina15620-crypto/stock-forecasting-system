"""
Base agent class for all agents in the system.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pathlib import Path
import os
import json


class BaseAgent(ABC):
    """Base class for all agents."""
    
    def __init__(self, config: Any, run_dir: str, logger: Optional[Any] = None):
        self.config = config
        self.run_dir = run_dir
        self.agent_name = self.__class__.__name__
        self.agent_dir = os.path.join(run_dir, self.agent_name)
        self.logger = logger
        
        # Ensure agent directory exists
        os.makedirs(self.agent_dir, exist_ok=True)
        
        # Initialize agent-specific logger if not provided
        if self.logger is None:
            from utils import AgentLogger
            self.logger = AgentLogger(self.agent_name, run_dir)
    
    @abstractmethod
    def run(self) -> Dict[str, Any]:
        """
        Execute the agent's main logic.
        
        Returns:
            Dict with agent output
        """
        pass
    
    def save_output(self, output_data: Dict[str, Any]) -> str:
        """Save agent output to output.json."""
        output_path = os.path.join(self.agent_dir, "output.json")

        # Add metadata
        output_data['agent_name'] = self.agent_name
        output_data['timestamp'] = str(pd.Timestamp.now())

        from determinism import dump_canonical_json
        dump_canonical_json(output_path, output_data, default=str)

        self.logger.info(f"Saved output to {output_path}")
        return output_path
    
    def load_agent_output(self, agent_name: str) -> Dict[str, Any]:
        """Load another agent's output."""
        output_path = os.path.join(self.run_dir, agent_name, "output.json")
        
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Output not found for {agent_name}: {output_path}")
        
        with open(output_path, 'r') as f:
            return json.load(f)
    
    def save_artifact(self, filename: str, data: Any):
        """Save an artifact (file) in the agent's directory."""
        filepath = os.path.join(self.agent_dir, filename)

        # Handle different data types
        if isinstance(data, (dict, list)):
            from determinism import dump_canonical_json
            dump_canonical_json(filepath, data, default=str)
        elif hasattr(data, 'to_parquet'):  # DataFrame
            data.to_parquet(filepath)
        elif hasattr(data, 'to_csv'):  # DataFrame
            data.to_csv(filepath)
        else:
            # Try to write as text
            with open(filepath, 'w') as f:
                f.write(str(data))
        
        self.logger.info(f"Saved artifact: {filename}")
        return filepath
    
    def get_artifact_path(self, filename: str) -> str:
        """Get full path to an artifact."""
        return os.path.join(self.agent_dir, filename)


import pandas as pd
