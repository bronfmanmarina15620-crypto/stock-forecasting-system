"""
MemoryLearningAgent - Learns from runs and makes improvement suggestions.
"""
import os
import pandas as pd
import sqlite3
import json
from typing import Dict, Any
from datetime import datetime
from .base_agent import BaseAgent


class MemoryLearningAgent(BaseAgent):
    """Agent responsible for learning and memory."""
    
    def run(self) -> Dict[str, Any]:
        """Persist run data and generate insights."""
        self.logger.info("Starting memory and learning")
        
        try:
            # Load all agent outputs
            decision_output = self.load_agent_output('DecisionRiskAgent')
            backtest_output = self.load_agent_output('BacktestAgent')
            portfolio_output = self.load_agent_output('PortfolioAgent')
            
            # Initialize database
            db_path = self._get_db_path()
            self._initialize_database(db_path)
            
            # Persist current run
            self._persist_run(
                db_path,
                decision_output=decision_output,
                backtest_output=backtest_output,
                portfolio_output=portfolio_output
            )
            
            # Generate insights from historical runs
            insights = self._generate_insights(db_path)
            
            # Generate suggestions (NO AUTO-APPLY)
            suggestions = self._generate_suggestions(insights)
            
            # Create lessons learned document
            lessons_learned = self._create_lessons_learned(insights, suggestions)
            
            # Save artifacts
            self.save_artifact('lessons_learned.md', lessons_learned)
            self.save_artifact('suggestions.json', suggestions)
            
            # Prepare output
            output = {
                'status': 'SUCCESS',
                'db_path': db_path,
                'insights': insights,
                'suggestions': suggestions,
                'note': 'Suggestions are for REVIEW ONLY. No automatic changes are applied.'
            }
            
            self.save_output(output)
            self.logger.info("Memory and learning complete")
            
            return output
            
        except Exception as e:
            self.logger.error(f"Memory learning failed: {str(e)}")
            return {
                'status': 'FAILED',
                'error': str(e)
            }
    
    def _get_db_path(self) -> str:
        """Get database path."""
        import os
        db_dir = "memory"
        os.makedirs(db_dir, exist_ok=True)
        return os.path.join(db_dir, "memory_db.sqlite")
    
    def _initialize_database(self, db_path: str):
        """Initialize SQLite database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                ticker TEXT,
                timestamp TEXT,
                auc REAL,
                max_drawdown REAL,
                expected_value REAL,
                signals_per_month REAL,
                abstain_pct REAL,
                win_rate REAL
            )
        """)
        
        # Create suggestions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                suggestion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                timestamp TEXT,
                suggestion_type TEXT,
                suggestion_text TEXT,
                applied BOOLEAN DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _persist_run(self, db_path: str, **kwargs):
        """Persist current run to database."""
        decision_output = kwargs['decision_output']
        backtest_output = kwargs['backtest_output']
        
        decision_stats = decision_output['decision_stats']
        bt_metrics = backtest_output.get('metrics', {})
        legacy_ml = bt_metrics.get('legacy_ml', {})

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            os.path.basename(self.run_dir),  # run_id
            self.config.ticker,
            datetime.now().isoformat(),
            legacy_ml.get('auc', 0.5),
            decision_stats['max_drawdown'],
            decision_stats['expected_value_per_signal'],
            decision_stats['signals_per_month'],
            decision_stats['abstain_percentage'],
            decision_stats['win_rate']
        ))
        
        conn.commit()
        conn.close()
    
    def _generate_insights(self, db_path: str) -> Dict[str, Any]:
        """Generate insights from historical runs."""
        conn = sqlite3.connect(db_path)
        
        # Load historical runs
        df = pd.read_sql_query("SELECT * FROM runs WHERE ticker = ?", conn, params=(self.config.ticker,))
        
        conn.close()
        
        if len(df) == 0:
            return {
                'num_runs': 0,
                'insights': []
            }
        
        insights = []
        
        # Insight 1: Performance trend
        if len(df) >= 3:
            recent_auc = df.tail(3)['auc'].mean()
            older_auc = df.head(max(3, len(df)-3))['auc'].mean()
            
            if recent_auc < older_auc * 0.95:
                insights.append({
                    'type': 'performance_degradation',
                    'message': f'Performance has degraded: Recent AUC {recent_auc:.3f} vs Historical {older_auc:.3f}'
                })
        
        # Insight 2: Drawdown issues
        if df['max_drawdown'].min() < -0.20:
            insights.append({
                'type': 'high_drawdown',
                'message': f'Maximum drawdown observed: {df["max_drawdown"].min():.1%}'
            })
        
        # Insight 3: Low signal frequency
        if df['signals_per_month'].mean() < 2:
            insights.append({
                'type': 'low_signal_frequency',
                'message': f'Average signals per month is low: {df["signals_per_month"].mean():.1f}'
            })
        
        return {
            'num_runs': len(df),
            'insights': insights,
            'stats': {
                'avg_auc': float(df['auc'].mean()),
                'avg_drawdown': float(df['max_drawdown'].mean()),
                'avg_signals_per_month': float(df['signals_per_month'].mean())
            }
        }
    
    def _generate_suggestions(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate improvement suggestions.
        
        CRITICAL: These are SUGGESTIONS ONLY. No automatic application.
        """
        suggestions = []
        
        for insight in insights.get('insights', []):
            if insight['type'] == 'performance_degradation':
                suggestions.append({
                    'type': 'model_retrain',
                    'priority': 'HIGH',
                    'suggestion': 'Consider retraining model with recent data or adjusting feature set',
                    'auto_apply': False
                })
            
            elif insight['type'] == 'high_drawdown':
                suggestions.append({
                    'type': 'risk_reduction',
                    'priority': 'HIGH',
                    'suggestion': 'Consider reducing position size or tightening probability threshold',
                    'auto_apply': False
                })
            
            elif insight['type'] == 'low_signal_frequency':
                suggestions.append({
                    'type': 'threshold_adjustment',
                    'priority': 'MEDIUM',
                    'suggestion': 'Consider lowering probability threshold to increase signal frequency',
                    'auto_apply': False
                })
        
        return {
            'suggestions': suggestions,
            'requires_review': True,
            'auto_apply_enabled': self.config.memory.auto_apply_suggestions,
            'warning': 'All suggestions require manual review and validation before applying'
        }
    
    def _create_lessons_learned(self, insights: Dict[str, Any], suggestions: Dict[str, Any]) -> str:
        """Create lessons learned markdown document."""
        doc = f"""# Lessons Learned - {self.config.ticker}

## Run Summary
- Total Runs: {insights['num_runs']}
- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Insights

"""
        
        if insights['num_runs'] > 0:
            doc += f"""
### Performance Statistics
- Average AUC: {insights['stats']['avg_auc']:.3f}
- Average Drawdown: {insights['stats']['avg_drawdown']:.1%}
- Average Signals/Month: {insights['stats']['avg_signals_per_month']:.1f}

"""
        
        if insights.get('insights'):
            doc += "### Key Findings\n\n"
            for insight in insights['insights']:
                doc += f"- **{insight['type']}**: {insight['message']}\n"
        
        doc += "\n## Suggestions\n\n"
        
        if suggestions['suggestions']:
            for sugg in suggestions['suggestions']:
                doc += f"""
### {sugg['type']} (Priority: {sugg['priority']})
{sugg['suggestion']}

**Auto-Apply**: {sugg['auto_apply']}

"""
        else:
            doc += "No suggestions at this time.\n"
        
        doc += f"""
---

**Important**: All suggestions require manual review and walk-forward validation before implementation.
Auto-apply is {'ENABLED' if self.config.memory.auto_apply_suggestions else 'DISABLED'} in configuration.
"""
        
        return doc