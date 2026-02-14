"""
OrchestratorAgent - Main coordinator that executes all agents in order.
"""

import os
from typing import Dict, Any, List
from datetime import datetime
from .base_agent import BaseAgent
from .data_agent import DataAgent
from .feature_agent import FeatureAgent
from .regime_agent import RegimeAgent
from .event_model_agent import EventModelAgent
from .backtest_agent import BacktestAgent
from .decision_risk_agent import DecisionRiskAgent
from .portfolio_agent import PortfolioAgent
from .dashboard_agent import DashboardAgent
from .memory_learning_agent import MemoryLearningAgent


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator that coordinates all agents.
    No agent may directly call another - only Orchestrator coordinates.
    """
    
    def __init__(self, config: Any, run_dir: str, logger: Any = None):
        super().__init__(config, run_dir, logger)
        
        # Define agent execution order
        self.agent_classes = [
            DataAgent,
            FeatureAgent,
            RegimeAgent,
            EventModelAgent,
            BacktestAgent,
            DecisionRiskAgent,
            PortfolioAgent,
            DashboardAgent,
            MemoryLearningAgent
        ]
    
    def run(self) -> Dict[str, Any]:
        """Execute all agents in order."""
        self.logger.info(f"Starting orchestration for {self.config.ticker}")
        
        results = {}
        status = 'SUCCESS'
        errors = []
        
        # Execute each agent
        for agent_class in self.agent_classes:
            agent_name = agent_class.__name__
            self.logger.info(f"Executing {agent_name}...")
            
            try:
                # Instantiate and run agent
                agent = agent_class(self.config, self.run_dir)
                output = agent.run()
                
                # Validate output
                if not self._validate_agent_output(agent_name, output):
                    error_msg = f"{agent_name} produced invalid output"
                    self.logger.error(error_msg)
                    errors.append(error_msg)
                    status = 'FAILED'
                    break
                
                # Check agent status
                if output.get('status') == 'FAILED':
                    error_msg = f"{agent_name} failed: {output.get('error', 'Unknown error')}"
                    self.logger.error(error_msg)
                    errors.append(error_msg)
                    status = 'FAILED'
                    break
                
                elif output.get('status') == 'WARNING':
                    warning_msg = f"{agent_name} completed with warnings"
                    self.logger.warning(warning_msg)
                    if status == 'SUCCESS':
                        status = 'WARNING'
                
                results[agent_name] = output
                self.logger.info(f"{agent_name} completed successfully")
                
            except Exception as e:
                error_msg = f"{agent_name} raised exception: {str(e)}"
                self.logger.error(error_msg)
                errors.append(error_msg)
                status = 'FAILED'
                break
        
        # Write status file
        self._write_status_file(status, errors)
        
        # Create final output
        output = {
            'status': status,
            'ticker': self.config.ticker,
            'run_dir': self.run_dir,
            'timestamp': datetime.now().isoformat(),
            'agent_results': results,
            'errors': errors
        }
        
        self.save_output(output)
        
        if status == 'SUCCESS':
            self.logger.info("✓ All agents completed successfully")
        elif status == 'WARNING':
            self.logger.warning("⚠ Completed with warnings")
        else:
            self.logger.error("✗ Run failed")
        
        return output
    
    def _validate_agent_output(self, agent_name: str, output: Dict[str, Any]) -> bool:
        """Validate that agent produced required output."""
        # Check that output.json exists
        output_path = os.path.join(self.run_dir, agent_name, "output.json")
        
        if not os.path.exists(output_path):
            self.logger.error(f"Missing output.json for {agent_name}")
            return False
        
        # Check that output has required fields
        if 'status' not in output:
            self.logger.error(f"{agent_name} output missing 'status' field")
            return False
        
        return True
    
    def _write_status_file(self, status: str, errors: List[str]):
        """Write status.txt file to run directory."""
        status_path = os.path.join(self.run_dir, 'status.txt')
        
        with open(status_path, 'w') as f:
            f.write(f"STATUS: {status}\n")
            f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
            f.write(f"TICKER: {self.config.ticker}\n")
            
            if errors:
                f.write("\nERRORS:\n")
                for error in errors:
                    f.write(f"- {error}\n")
        
        self.logger.info(f"Status file written: {status_path}")
