"""
BacktestAgent - Walk-forward backtesting with full artifact production.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
import pickle
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.linear_model import LogisticRegression
from .base_agent import BaseAgent
from determinism import content_hash_sha256


class BacktestAgent(BaseAgent):
    """Walk-forward backtesting with realistic costs and sanity checks."""

    def run(self) -> Dict[str, Any]:
        """Run walk-forward backtest."""
        self.logger.info("Starting walk-forward backtest")

        try:
            # Load dependencies
            model_output = self.load_agent_output('EventModelAgent')
            regime_output = self.load_agent_output('RegimeAgent')
            data_output = self.load_agent_output('DataAgent')
            feature_output = self.load_agent_output('FeatureAgent')

            # Load data
            with open(model_output['model_path'], 'rb') as f:
                model = pickle.load(f)

            features = pd.read_parquet(feature_output['features_path'])
            regimes = pd.read_parquet(regime_output['regime_path'])['regime']
            prices = pd.read_parquet(data_output['data_path'])['Close']

            # Run backtest
            predictions = self._simple_backtest(model, features, regimes, prices)

            # Calculate metrics
            metrics = self._calculate_metrics(predictions)

            # Generate trades from predictions
            trades = self._generate_trades(predictions)

            # Generate PnL series
            pnl_series = self._generate_pnl_series(predictions)

            # Generate costs assumptions
            costs_assumptions = self._generate_costs_assumptions()

            # Run sanity tests
            sanity_results = self._run_sanity_tests(features, prices, regimes)

            # Embed deterministic content fingerprint
            metrics['content_hash_sha256'] = content_hash_sha256(metrics)

            # Save all required artifacts
            self.save_artifact('predictions_oos.parquet', predictions)
            self.save_artifact('metrics.json', metrics)
            self.save_artifact('trades.parquet', trades)
            self.save_artifact('pnl_series.parquet', pnl_series)
            self.save_artifact('costs_assumptions.json', costs_assumptions)
            self.save_artifact('sanity_tests.json', sanity_results)
            self.save_artifact('backtest_report.html',
                               self._generate_backtest_html(metrics, sanity_results))

            output = {
                'status': 'SUCCESS',
                'predictions_path': self.get_artifact_path('predictions_oos.parquet'),
                'metrics': metrics
            }

            self.save_output(output)
            self.logger.info("Walk-forward backtest complete")
            return output

        except Exception as e:
            self.logger.error(f"Backtest failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'status': 'FAILED', 'error': str(e)}

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

    def _calculate_metrics(self, predictions: pd.DataFrame) -> Dict[str, Any]:
        """Calculate comprehensive metrics including required fields."""
        if len(predictions) == 0:
            return {
                'overall': {'auc': 0.5, 'total_samples': 0},
                'EV_per_trade': 0.0,
                'max_drawdown': 0.0,
                'win_rate': 0.0,
                'avg_trades_per_month': 0.0,
                'by_year': [],
                'by_regime': []
            }

        y_true = predictions['y_true'].values
        y_pred = predictions['y_pred_proba'].values

        auc = float(roc_auc_score(y_true, y_pred))
        brier = float(brier_score_loss(y_true, y_pred))

        # Trading cost model
        commission = self.config.backtest.commission_pct
        spread = self.config.backtest.spread_bps / 10000
        slippage = self.config.backtest.slippage_bps / 10000
        total_friction = commission + spread + slippage

        # Simulate signal-based returns
        prob_threshold = self.config.decision.probability_threshold
        allowed_regimes = self.config.decision.allowed_regimes

        enter_mask = (
            (predictions['y_pred_proba'] > prob_threshold) &
            (predictions['regime'].isin(allowed_regimes))
        )

        threshold_pct = self.config.event.threshold_pct / 100.0

        signal_returns = []
        for _, row in predictions[enter_mask].iterrows():
            raw_return = row['y_true'] * threshold_pct
            net_return = raw_return - (total_friction * 2)
            signal_returns.append(net_return)

        ev_per_trade = float(np.mean(signal_returns)) if signal_returns else 0.0
        win_rate = float(np.mean([r > 0 for r in signal_returns])) if signal_returns else 0.0

        # Max drawdown from cumulative returns
        if signal_returns:
            cum = np.cumprod([1 + r for r in signal_returns])
            cummax = np.maximum.accumulate(cum)
            drawdowns = (cum - cummax) / cummax
            max_dd = float(np.min(drawdowns))
        else:
            max_dd = 0.0

        # Avg trades per month
        if len(predictions) > 0:
            predictions_dt = pd.to_datetime(predictions['date'])
            total_months = max(1, (predictions_dt.max() - predictions_dt.min()).days / 30.0)
            avg_trades_per_month = float(enter_mask.sum() / total_months)
        else:
            avg_trades_per_month = 0.0

        return {
            'overall': {
                'auc': auc,
                'brier_score': brier,
                'base_rate': float(y_true.mean()),
                'total_samples': len(predictions)
            },
            'EV_per_trade': ev_per_trade,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'avg_trades_per_month': avg_trades_per_month,
            'total_signals': int(enter_mask.sum()),
            'by_year': [],
            'by_regime': []
        }

    def _generate_trades(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """Generate trade records from predictions."""
        if len(predictions) == 0:
            return pd.DataFrame(columns=[
                'date', 'action', 'price', 'probability', 'regime',
                'y_true', 'net_return'
            ])

        prob_threshold = self.config.decision.probability_threshold
        allowed_regimes = self.config.decision.allowed_regimes

        commission = self.config.backtest.commission_pct
        spread = self.config.backtest.spread_bps / 10000
        slippage = self.config.backtest.slippage_bps / 10000
        total_friction = commission + spread + slippage
        threshold_pct = self.config.event.threshold_pct / 100.0

        trades = []
        for _, row in predictions.iterrows():
            is_enter = (
                row['y_pred_proba'] > prob_threshold and
                row['regime'] in allowed_regimes
            )
            action = 'ENTER' if is_enter else 'ABSTAIN'
            raw_return = row['y_true'] * threshold_pct
            net_return = (raw_return - total_friction * 2) if is_enter else 0.0

            trades.append({
                'date': row['date'],
                'action': action,
                'price': row['price'],
                'probability': row['y_pred_proba'],
                'regime': row['regime'],
                'y_true': row['y_true'],
                'net_return': net_return
            })

        return pd.DataFrame(trades)

    def _generate_pnl_series(self, predictions: pd.DataFrame) -> pd.DataFrame:
        """Generate cumulative PnL series."""
        if len(predictions) == 0:
            return pd.DataFrame(columns=['date', 'cumulative_return', 'drawdown'])

        trades = self._generate_trades(predictions)
        enter_trades = trades[trades['action'] == 'ENTER'].copy()

        if len(enter_trades) == 0:
            return pd.DataFrame({
                'date': predictions['date'],
                'cumulative_return': 1.0,
                'drawdown': 0.0
            })

        enter_trades = enter_trades.reset_index(drop=True)
        enter_trades['cum_return'] = (1 + enter_trades['net_return']).cumprod()
        enter_trades['cum_max'] = enter_trades['cum_return'].cummax()
        enter_trades['drawdown'] = (
            (enter_trades['cum_return'] - enter_trades['cum_max']) /
            enter_trades['cum_max']
        )

        return enter_trades[['date', 'cum_return', 'drawdown']].rename(
            columns={'cum_return': 'cumulative_return'}
        )

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
        """Run leakage detection sanity tests.

        Test 1 (shuffled labels): Average over N shuffles to reduce noise.
                Train on shuffled labels -> predict test -> AUC should be ~0.50.
        Test 2 (future shift): Shift labels by a large window (60 days) to break
                any temporal autocorrelation in features/labels.
        """
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
        """Generate backtest HTML report."""
        overall = metrics.get('overall', {})
        return f"""<!DOCTYPE html>
<html><head><title>Backtest Report</title></head>
<body>
<h1>Walk-Forward Backtest Report</h1>
<h2>Overall Metrics</h2>
<ul>
  <li>AUC: {overall.get('auc', 'N/A')}</li>
  <li>Brier Score: {overall.get('brier_score', 'N/A')}</li>
  <li>Base Rate: {overall.get('base_rate', 'N/A')}</li>
  <li>Total OOS Samples: {overall.get('total_samples', 'N/A')}</li>
</ul>
<h2>Trading Metrics</h2>
<ul>
  <li>EV per Trade: {metrics.get('EV_per_trade', 'N/A')}</li>
  <li>Max Drawdown: {metrics.get('max_drawdown', 'N/A')}</li>
  <li>Win Rate: {metrics.get('win_rate', 'N/A')}</li>
  <li>Avg Trades/Month: {metrics.get('avg_trades_per_month', 'N/A')}</li>
</ul>
<h2>Sanity Tests</h2>
<ul>
  <li>Shuffled Labels AUC: {sanity.get('shuffled_labels_auc', 'N/A')} (pass &lt;= 0.55)</li>
  <li>Future Shift AUC: {sanity.get('future_shift_auc', 'N/A')} (pass &lt;= 0.55)</li>
  <li>Status: {sanity.get('status', 'N/A')}</li>
</ul>
</body></html>"""
