"""
BacktestAgent - Phase 3 strategy evaluation (default) + optional ML walk-forward.

Phase 3 (signals_only, DEFAULT): Consumes StrategyAgent/strategy_signals.parquet
as the SINGLE source of truth for trade execution.  No ML imports or execution.

Legacy ML (legacy_ml, opt-in): Retains walk-forward ML validation for
predictions_oos.parquet and sanity_tests.json (backward compat).
"""

import os

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from .base_agent import BaseAgent
from determinism import content_hash_sha256

# Phase 3 schema locks
REQUIRED_PNL_COLS = ["date", "equity_curve", "daily_return", "position"]
REQUIRED_TRADES_COLS = [
    "entry_date", "entry_price", "exit_date", "exit_price",
    "pnl", "return", "holding_days",
]
REQUIRED_METRICS_KEYS = [
    # Backward compat
    "EV_per_trade", "max_drawdown", "win_rate",
    "avg_trades_per_month", "total_signals",
    # Phase 3 performance
    "total_return", "cagr", "volatility", "sharpe", "exposure_time_pct",
    # Phase 3 trade stats
    "num_trades", "avg_trade_return", "median_trade_return",
    "profit_factor", "avg_holding_days",
    # Regime diagnostics
    "days_regime_ok_pct", "days_range_high_vol_pct",
    "days_abstain_pct", "breakout_entry_count",
    # Costs
    "total_costs", "costs_per_trade_avg",
]

# Stub ML metrics for signals_only mode (numeric defaults so formatters work)
_STUB_ML_METRICS = {
    'legacy_ml': {
        'auc': 0.5,
        'brier_score': 0.5,
        'base_rate': 0.0,
        'total_samples': 0,
    }
}


class BacktestAgent(BaseAgent):
    """Phase 3 strategy backtesting with optional ML walk-forward."""

    def run(self) -> Dict[str, Any]:
        """Run backtest in configured mode (signals_only | legacy_ml)."""
        mode = getattr(self.config.backtest, 'backtest_mode', 'signals_only')
        self.logger.info(f"Backtest mode: {mode}")

        if mode == 'signals_only':
            return self._run_signals_only()
        elif mode == 'legacy_ml':
            return self._run_legacy_ml()
        else:
            raise ValueError(
                f"Unknown backtest_mode: '{mode}'. "
                f"Must be 'signals_only' or 'legacy_ml'."
            )

    # ==================================================================
    # signals_only mode (Phase 3 default)
    # ==================================================================

    def _run_signals_only(self) -> Dict[str, Any]:
        """Phase 3 signal-driven backtest.  No ML imports or execution.

        Design invariant: this method (and everything it calls) must NEVER
        import or invoke sklearn / pickle / ML model code.  Enforced by
        test_signals_only_does_not_import_or_run_legacy_ml.
        """
        self.logger.info("Running signals_only backtest (no ML)")

        try:
            data_output = self.load_agent_output('DataAgent')

            strategy_signals = pd.read_parquet(
                os.path.join(self.run_dir, 'StrategyAgent',
                             'strategy_signals.parquet')
            )
            close = pd.read_parquet(data_output['data_path'])['Close']

            emit_stubs = getattr(
                self.config.backtest, 'emit_legacy_stubs', True
            )
            ml_input = _STUB_ML_METRICS if emit_stubs else {}

            trades = self._build_strategy_trades(strategy_signals, close)
            pnl_series = self._build_strategy_pnl(strategy_signals, close)
            metrics = self._calculate_strategy_metrics(
                strategy_signals, close, trades, pnl_series, ml_input
            )

            metrics['content_hash_sha256'] = content_hash_sha256(metrics)
            costs_assumptions = self._generate_costs_assumptions()

            # Phase 3 artifacts (always written at top level)
            self.save_artifact('costs_assumptions.json', costs_assumptions)
            self.save_artifact('trades.parquet', trades)
            self.save_artifact('pnl_series.parquet', pnl_series)
            self.save_artifact('metrics.json', metrics)

            # Legacy ML stubs — isolated under legacy_ml/ subfolder
            stub_sanity = {}
            if emit_stubs:
                legacy_dir = os.path.join(self.agent_dir, 'legacy_ml')
                os.makedirs(legacy_dir, exist_ok=True)

                stub_predictions = pd.DataFrame(
                    columns=[
                        'date', 'y_true', 'y_pred_proba', 'regime', 'price',
                    ]
                )
                stub_sanity = {
                    'shuffled_labels_auc': 0.50,
                    'future_shift_auc': 0.50,
                    'status': 'SKIPPED',
                    'reason':
                        'signals_only mode: ML sanity tests not applicable',
                }
                self.save_artifact(
                    'legacy_ml/predictions_oos.parquet', stub_predictions,
                )
                self.save_artifact(
                    'legacy_ml/sanity_tests.json', stub_sanity,
                )

            self.save_artifact(
                'backtest_report.html',
                self._generate_backtest_html(metrics, stub_sanity),
            )

            last_trade_summary = None
            if len(trades) > 0:
                last_trade_summary = trades.iloc[-1].to_dict()

            output = {
                'status': 'SUCCESS',
                'metrics': metrics,
                'last_trade_summary': last_trade_summary,
            }

            self.save_output(output)
            n_trades = len(trades)
            total_ret = metrics.get('total_return', 0)
            self.logger.info(
                f"Backtest complete (signals_only): {n_trades} trades, "
                f"total_return={total_ret:.2%}"
            )
            return output

        except Exception as e:
            self.logger.error(f"Backtest failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'status': 'FAILED', 'error': str(e)}

    # ==================================================================
    # legacy_ml mode (opt-in backward compat)
    # ==================================================================

    def _run_legacy_ml(self) -> Dict[str, Any]:
        """Walk-forward ML validation + Phase 3 strategy backtest."""
        self.logger.info("Running legacy_ml backtest (ML walk-forward enabled)")

        import pickle  # lazy: only in legacy_ml

        try:
            # ML walk-forward
            model_output = self.load_agent_output('EventModelAgent')
            regime_output = self.load_agent_output('RegimeAgent')
            data_output = self.load_agent_output('DataAgent')
            feature_output = self.load_agent_output('FeatureAgent')

            with open(model_output['model_path'], 'rb') as f:
                model = pickle.load(f)

            features = pd.read_parquet(feature_output['features_path'])
            regimes = pd.read_parquet(regime_output['regime_path'])['regime']
            prices = pd.read_parquet(data_output['data_path'])['Close']

            predictions = self._simple_backtest(model, features, regimes, prices)
            ml_metrics = self._calculate_ml_metrics(predictions)
            sanity_results = self._run_sanity_tests(features, prices, regimes)
            costs_assumptions = self._generate_costs_assumptions()

            self.save_artifact('predictions_oos.parquet', predictions)
            self.save_artifact('sanity_tests.json', sanity_results)
            self.save_artifact('costs_assumptions.json', costs_assumptions)

            # Phase 3: Strategy-based backtest
            strategy_signals = pd.read_parquet(
                os.path.join(self.run_dir, 'StrategyAgent',
                             'strategy_signals.parquet')
            )
            close = pd.read_parquet(data_output['data_path'])['Close']

            trades = self._build_strategy_trades(strategy_signals, close)
            pnl_series = self._build_strategy_pnl(strategy_signals, close)
            metrics = self._calculate_strategy_metrics(
                strategy_signals, close, trades, pnl_series, ml_metrics
            )

            metrics['content_hash_sha256'] = content_hash_sha256(metrics)

            self.save_artifact('trades.parquet', trades)
            self.save_artifact('pnl_series.parquet', pnl_series)
            self.save_artifact('metrics.json', metrics)
            self.save_artifact(
                'backtest_report.html',
                self._generate_backtest_html(metrics, sanity_results),
            )

            last_trade_summary = None
            if len(trades) > 0:
                last_trade_summary = trades.iloc[-1].to_dict()

            output = {
                'status': 'SUCCESS',
                'predictions_path': self.get_artifact_path(
                    'predictions_oos.parquet'),
                'metrics': metrics,
                'last_trade_summary': last_trade_summary,
            }

            self.save_output(output)
            n_trades = len(trades)
            total_ret = metrics.get('total_return', 0)
            self.logger.info(
                f"Backtest complete (legacy_ml): {n_trades} trades, "
                f"total_return={total_ret:.2%}"
            )
            return output

        except Exception as e:
            self.logger.error(f"Backtest failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'status': 'FAILED', 'error': str(e)}

    # ------------------------------------------------------------------
    # ML walk-forward (legacy_ml only)
    # ------------------------------------------------------------------

    def _simple_backtest(self, model, features, regimes, prices):
        """Walk-forward backtest with strict chronological separation."""
        predictions_list = []

        # Parameters from config
        train_size = self.config.backtest.initial_train_days
        test_size = self.config.backtest.test_window_days
        step = self.config.backtest.step_days

        # Align all data
        common_idx = features.index.intersection(regimes.index).intersection(prices.index)
        features = features.loc[common_idx]
        regimes = regimes.loc[common_idx]
        prices = prices.loc[common_idx]

        # Create labels (forward return > threshold)
        forward_window = self.config.event.forward_window
        threshold = self.config.event.threshold_pct / 100.0
        forward_return = prices.shift(-forward_window) / prices - 1
        y_all = (forward_return >= threshold).astype(int)

        # Walk forward
        for i in range(train_size, len(features) - forward_window, step):
            train_end = i
            train_start = max(0, train_end - train_size)

            test_start = train_end
            test_end = min(len(features) - forward_window, test_start + test_size)

            if test_end - test_start < self.config.backtest.min_test_samples:
                break

            # Get data
            X_train = features.iloc[train_start:train_end]
            y_train = y_all.iloc[train_start:train_end]
            X_test = features.iloc[test_start:test_end]
            y_test = y_all.iloc[test_start:test_end]

            # Remove NaN
            train_mask = ~(X_train.isna().any(axis=1) | y_train.isna())
            test_mask = ~(X_test.isna().any(axis=1) | y_test.isna())

            X_train = X_train[train_mask]
            y_train = y_train[train_mask]
            X_test = X_test[test_mask]
            y_test = y_test[test_mask]

            if len(X_train) < 50 or len(X_test) < 10:
                continue

            # Train and predict
            model.fit(X_train, y_train)
            y_pred_proba = model.predict_proba(X_test)[:, 1]

            # Store predictions
            for j, idx in enumerate(X_test.index):
                predictions_list.append({
                    'date': str(idx),
                    'y_true': int(y_test.iloc[j]),
                    'y_pred_proba': float(y_pred_proba[j]),
                    'regime': str(regimes.loc[idx]),
                    'price': float(prices.loc[idx])
                })

        predictions_df = pd.DataFrame(predictions_list)
        self.logger.info(f"Created {len(predictions_df)} OOS predictions")
        return predictions_df

    def _calculate_ml_metrics(
        self, predictions: pd.DataFrame
    ) -> Dict[str, Any]:
        """Calculate ML-only metrics (AUC, Brier) for backward compat."""
        from sklearn.metrics import roc_auc_score, brier_score_loss  # lazy

        if len(predictions) == 0:
            return {
                'legacy_ml': {
                    'auc': 0.5, 'brier_score': 0.5,
                    'base_rate': 0.0, 'total_samples': 0,
                }
            }

        y_true = predictions['y_true'].values
        y_pred = predictions['y_pred_proba'].values

        auc = float(roc_auc_score(y_true, y_pred))
        brier = float(brier_score_loss(y_true, y_pred))

        return {
            'legacy_ml': {
                'auc': auc,
                'brier_score': brier,
                'base_rate': float(y_true.mean()),
                'total_samples': len(predictions),
            }
        }

    # ------------------------------------------------------------------
    # Phase 3: Strategy-based backtest
    # ------------------------------------------------------------------

    def _get_one_way_cost(self) -> float:
        """One-way trading cost from existing config plumbing."""
        commission = self.config.backtest.commission_pct
        spread = self.config.backtest.spread_bps / 10000
        slippage = self.config.backtest.slippage_bps / 10000
        return commission + spread + slippage

    def _build_strategy_trades(
        self,
        strategy_signals: pd.DataFrame,
        close: pd.Series,
    ) -> pd.DataFrame:
        """Build trade records from Phase 2 entry/exit signals.

        Each completed trade: entry_signal -> ... -> exit_signal.
        Open trades at end of series are NOT included.
        """
        trades = []
        in_trade = False
        entry_date = entry_price = None
        round_trip_cost = self._get_one_way_cost() * 2

        close_aligned = close.reindex(strategy_signals.index)

        for i in range(len(strategy_signals)):
            idx = strategy_signals.index[i]
            entry_sig = bool(strategy_signals['entry_signal'].iloc[i])
            exit_sig = bool(strategy_signals['exit_signal'].iloc[i])
            price = float(close_aligned.iloc[i])

            if entry_sig and not in_trade:
                in_trade = True
                entry_date = idx
                entry_price = price

            if exit_sig and in_trade:
                gross_ret = (
                    (price / entry_price) - 1 if entry_price != 0 else 0.0
                )
                net_ret = gross_ret - round_trip_cost
                dt_str = lambda d: (
                    str(d.date()) if hasattr(d, 'date') else str(d)
                )
                trades.append({
                    'entry_date': dt_str(entry_date),
                    'entry_price': entry_price,
                    'exit_date': dt_str(idx),
                    'exit_price': price,
                    'pnl': price - entry_price,
                    'return': net_ret,
                    'holding_days': (idx - entry_date).days,
                })
                in_trade = False

        if not trades:
            return pd.DataFrame(
                columns=REQUIRED_TRADES_COLS,
            )

        return pd.DataFrame(trades)[REQUIRED_TRADES_COLS]

    def _build_strategy_pnl(
        self,
        strategy_signals: pd.DataFrame,
        close: pd.Series,
    ) -> pd.DataFrame:
        """Build daily PnL series from strategy position.

        Convention: position[t-1]=1 earns close[t]/close[t-1]-1 on day t.
        Costs deducted at entry and exit days.
        """
        close_aligned = close.reindex(strategy_signals.index)
        position = strategy_signals['position']

        daily_close_ret = close_aligned.pct_change().fillna(0)
        prev_position = position.shift(1).fillna(0)
        daily_return = (daily_close_ret * prev_position).copy()

        # Cost adjustments at entry/exit points
        one_way_cost = self._get_one_way_cost()
        daily_return.loc[strategy_signals['entry_signal']] -= one_way_cost
        daily_return.loc[strategy_signals['exit_signal']] -= one_way_cost

        equity_curve = (1 + daily_return).cumprod()

        return pd.DataFrame({
            'date': strategy_signals.index,
            'equity_curve': equity_curve.values,
            'daily_return': daily_return.values,
            'position': position.values,
        })

    def _calculate_strategy_metrics(
        self,
        signals: pd.DataFrame,
        close: pd.Series,
        trades_df: pd.DataFrame,
        pnl_df: pd.DataFrame,
        ml_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate comprehensive Phase 3 metrics."""
        n = len(signals)
        position = signals['position']

        # --- Performance ---
        equity = pnl_df['equity_curve'].values
        total_return = (
            float(equity[-1] / equity[0] - 1)
            if n > 0 and equity[0] > 0 else 0.0
        )

        years = n / 252.0
        if years > 0 and equity[-1] > 0 and equity[0] > 0:
            cagr = float((equity[-1] / equity[0]) ** (1 / years) - 1)
        else:
            cagr = 0.0

        cummax = np.maximum.accumulate(equity)
        drawdown = np.where(cummax > 0, (equity - cummax) / cummax, 0.0)
        max_dd = float(np.min(drawdown)) if n > 0 else 0.0

        daily_returns = pnl_df['daily_return'].values
        vol = (
            float(np.std(daily_returns, ddof=1) * np.sqrt(252))
            if n > 1 else 0.0
        )

        mean_daily = float(np.mean(daily_returns)) if n > 0 else 0.0
        std_daily = (
            float(np.std(daily_returns, ddof=1)) if n > 1 else 0.0
        )
        sharpe = (
            float((mean_daily / std_daily) * np.sqrt(252))
            if std_daily > 0 else 0.0
        )

        exposure_pct = float(position.sum() / n * 100) if n > 0 else 0.0

        # --- Trade stats ---
        num_trades = len(trades_df)
        if num_trades > 0:
            trade_returns = trades_df['return']
            win_rate = float((trade_returns > 0).mean())
            avg_trade_return = float(trade_returns.mean())
            median_trade_return = float(trade_returns.median())
            avg_holding = float(trades_df['holding_days'].mean())

            gross_profit = float(trade_returns[trade_returns > 0].sum())
            gross_loss = float(abs(trade_returns[trade_returns < 0].sum()))
            if gross_loss > 0:
                profit_factor = float(gross_profit / gross_loss)
            elif gross_profit > 0:
                profit_factor = None  # All winners, JSON null
            else:
                profit_factor = 0.0
        else:
            win_rate = 0.0
            avg_trade_return = 0.0
            median_trade_return = 0.0
            avg_holding = 0.0
            profit_factor = 0.0

        # --- Regime diagnostics ---
        regime_ok_pct = (
            float(signals['regime_ok'].sum() / n * 100) if n > 0 else 0.0
        )
        rhv_pct = (
            float(signals['range_high_vol'].sum() / n * 100)
            if n > 0 else 0.0
        )
        abstain_pct = (
            float((position == 0).sum() / n * 100) if n > 0 else 100.0
        )
        entry_count = int(signals['entry_signal'].sum())

        # --- Costs ---
        one_way = self._get_one_way_cost()
        total_costs = float(num_trades * 2 * one_way)
        costs_per_trade = float(2 * one_way) if num_trades > 0 else 0.0

        # --- Avg trades per month ---
        months = n / 21.0
        avg_trades_per_month = (
            float(num_trades / months) if months > 0 else 0.0
        )

        metrics = {
            # Backward compat keys (validate_run.py)
            'EV_per_trade': avg_trade_return,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'avg_trades_per_month': avg_trades_per_month,
            'total_signals': entry_count,

            # Phase 3 performance
            'total_return': total_return,
            'cagr': cagr,
            'volatility': vol,
            'sharpe': sharpe,
            'exposure_time_pct': exposure_pct,

            # Phase 3 trade stats
            'num_trades': num_trades,
            'avg_trade_return': avg_trade_return,
            'median_trade_return': median_trade_return,
            'profit_factor': profit_factor,
            'avg_holding_days': avg_holding,

            # Regime diagnostics
            'days_regime_ok_pct': regime_ok_pct,
            'days_range_high_vol_pct': rhv_pct,
            'days_abstain_pct': abstain_pct,
            'breakout_entry_count': entry_count,

            # Costs
            'total_costs': total_costs,
            'costs_per_trade_avg': costs_per_trade,
        }

        # Add legacy_ml only if provided (signals_only with stubs, or legacy_ml mode)
        legacy_ml = ml_metrics.get('legacy_ml')
        if legacy_ml is not None:
            metrics['legacy_ml'] = legacy_ml

        return metrics

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _generate_costs_assumptions(self) -> Dict[str, Any]:
        """Document trading cost assumptions."""
        commission = self.config.backtest.commission_pct
        spread = self.config.backtest.spread_bps / 10000
        slippage = self.config.backtest.slippage_bps / 10000

        return {
            'commission_pct': commission,
            'spread_bps': self.config.backtest.spread_bps,
            'slippage_bps': self.config.backtest.slippage_bps,
            'total_one_way_pct': commission + spread + slippage,
            'total_round_trip_pct': (commission + spread + slippage) * 2,
            'execution_assumption': self.config.backtest.execution_assumption,
            'forward_window_days': self.config.event.forward_window,
            'event_threshold_pct': self.config.event.threshold_pct
        }

    def _run_sanity_tests(self, features, prices, regimes) -> Dict[str, Any]:
        """Run leakage detection sanity tests (legacy_ml only).

        Test 1 (shuffled labels): Average over N shuffles to reduce noise.
                Train on shuffled labels -> predict test -> AUC should be ~0.50.
        Test 2 (future shift): Shift labels by a large window (60 days) to break
                any temporal autocorrelation in features/labels.
        """
        from sklearn.metrics import roc_auc_score  # lazy: only in legacy_ml
        from sklearn.linear_model import LogisticRegression  # lazy

        forward_window = self.config.event.forward_window
        threshold = self.config.event.threshold_pct / 100.0

        common_idx = features.index.intersection(prices.index)
        features_aligned = features.loc[common_idx]
        prices_aligned = prices.loc[common_idx]

        forward_return = prices_aligned.shift(-forward_window) / prices_aligned - 1
        y_all = (forward_return >= threshold).astype(int)

        valid_mask = ~(features_aligned.isna().any(axis=1) | y_all.isna())
        X = features_aligned[valid_mask]
        y = y_all[valid_mask]

        if len(X) < 100:
            return {
                'shuffled_labels_auc': 0.50,
                'future_shift_auc': 0.50,
                'status': 'SKIPPED',
                'reason': f'Insufficient data: {len(X)} samples'
            }

        split = int(len(X) * 0.7)
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]

        if len(y_test.unique()) < 2 or len(y_train.unique()) < 2:
            return {
                'shuffled_labels_auc': 0.50,
                'future_shift_auc': 0.50,
                'status': 'SKIPPED',
                'reason': 'Insufficient label diversity'
            }

        # Test 1: Shuffled labels - average over 5 shuffles for stability
        shuffle_aucs = []
        for seed in range(42, 47):
            try:
                y_train_shuffled = y_train.sample(frac=1, random_state=seed).values
                model_s = LogisticRegression(random_state=seed, max_iter=1000)
                model_s.fit(X_train, y_train_shuffled)
                y_pred_s = model_s.predict_proba(X_test)[:, 1]
                shuffle_aucs.append(float(roc_auc_score(y_test, y_pred_s)))
            except Exception:
                shuffle_aucs.append(0.50)
        shuffled_auc = float(np.mean(shuffle_aucs))

        # Test 2: Future shift - use large shift (60 days) to truly break signal
        large_shift = 60
        try:
            y_shifted = y.shift(large_shift).dropna().astype(int)
            valid_shifted = X.index.intersection(y_shifted.index)
            X_shifted = X.loc[valid_shifted]
            y_shifted = y_shifted.loc[valid_shifted]

            split_s = int(len(X_shifted) * 0.7)
            if split_s > 50 and (len(X_shifted) - split_s) > 20:
                X_tr_s = X_shifted.iloc[:split_s]
                y_tr_s = y_shifted.iloc[:split_s]
                X_te_s = X_shifted.iloc[split_s:]
                y_te_s = y_shifted.iloc[split_s:]

                if len(y_te_s.unique()) >= 2 and len(y_tr_s.unique()) >= 2:
                    model_shift = LogisticRegression(random_state=42, max_iter=1000)
                    model_shift.fit(X_tr_s, y_tr_s)
                    y_pred_shift = model_shift.predict_proba(X_te_s)[:, 1]
                    future_shift_auc = float(roc_auc_score(y_te_s, y_pred_shift))
                else:
                    future_shift_auc = 0.50
            else:
                future_shift_auc = 0.50
        except Exception:
            future_shift_auc = 0.50

        return {
            'shuffled_labels_auc': shuffled_auc,
            'future_shift_auc': future_shift_auc,
            'shuffled_labels_pass': shuffled_auc <= 0.55,
            'future_shift_pass': future_shift_auc <= 0.55,
            'status': 'PASS' if (shuffled_auc <= 0.55 and future_shift_auc <= 0.55) else 'FAIL'
        }

    def _generate_backtest_html(self, metrics: Dict, sanity: Dict) -> str:
        """Generate backtest HTML report with Phase 3 metrics."""
        overall = metrics.get('legacy_ml', {})
        pf = metrics.get('profit_factor')
        pf_str = f"{pf:.2f}" if pf is not None else "N/A (all winners)"

        return f"""<!DOCTYPE html>
<html><head><title>Backtest Report</title></head>
<body>
<h1>Walk-Forward Backtest Report</h1>
<h2>Strategy Performance (Phase 3)</h2>
<ul>
  <li>Total Return: {metrics.get('total_return', 0):.2%}</li>
  <li>CAGR: {metrics.get('cagr', 0):.2%}</li>
  <li>Max Drawdown: {metrics.get('max_drawdown', 0):.2%}</li>
  <li>Sharpe Ratio: {metrics.get('sharpe', 0):.2f}</li>
  <li>Volatility: {metrics.get('volatility', 0):.2%}</li>
  <li>Exposure: {metrics.get('exposure_time_pct', 0):.1f}%</li>
</ul>
<h2>Trade Statistics</h2>
<ul>
  <li>Number of Trades: {metrics.get('num_trades', 0)}</li>
  <li>Win Rate: {metrics.get('win_rate', 0):.1%}</li>
  <li>Avg Trade Return: {metrics.get('avg_trade_return', 0):.2%}</li>
  <li>Median Trade Return: {metrics.get('median_trade_return', 0):.2%}</li>
  <li>Profit Factor: {pf_str}</li>
  <li>Avg Holding Days: {metrics.get('avg_holding_days', 0):.1f}</li>
</ul>
<h2>Regime Diagnostics</h2>
<ul>
  <li>Regime OK Days: {metrics.get('days_regime_ok_pct', 0):.1f}%</li>
  <li>RANGE_HIGH_VOL Days: {metrics.get('days_range_high_vol_pct', 0):.1f}%</li>
  <li>Abstain Days: {metrics.get('days_abstain_pct', 0):.1f}%</li>
  <li>Breakout Entry Count: {metrics.get('breakout_entry_count', 0)}</li>
</ul>
<h2>Costs</h2>
<ul>
  <li>Total Costs: {metrics.get('total_costs', 0):.4%}</li>
  <li>Cost per Trade (round-trip): {metrics.get('costs_per_trade_avg', 0):.4%}</li>
</ul>
<h2>ML Validation (backward compat)</h2>
<ul>
  <li>AUC: {overall.get('auc', 'N/A')}</li>
  <li>Brier Score: {overall.get('brier_score', 'N/A')}</li>
  <li>Base Rate: {overall.get('base_rate', 'N/A')}</li>
  <li>Total OOS Samples: {overall.get('total_samples', 'N/A')}</li>
</ul>
<h2>Sanity Tests</h2>
<ul>
  <li>Shuffled Labels AUC: {sanity.get('shuffled_labels_auc', 'N/A')} (pass &lt;= 0.55)</li>
  <li>Future Shift AUC: {sanity.get('future_shift_auc', 'N/A')} (pass &lt;= 0.55)</li>
  <li>Status: {sanity.get('status', 'N/A')}</li>
</ul>
</body></html>"""
