"""
Invariant guardrail tests for DecisionRiskAgent.

Ensures decision_action follows Phase 2 long-only rules:
- action must be ENTER or ABSTAIN
- ENTER requires position == 1
- ABSTAIN requires non-empty "because" list
"""

import pytest

import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_mod = importlib.import_module("agents.decision_risk_agent")
_validate_decision_action = _mod._validate_decision_action
_VALID_ACTIONS = _mod._VALID_ACTIONS


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDecisionActionInvariants:
    """_validate_decision_action must enforce Phase 2 long-only rules."""

    def test_valid_actions_constant(self):
        assert _VALID_ACTIONS == {"ENTER", "ABSTAIN"}

    def test_valid_enter_passes(self):
        decision = {
            "action": "ENTER",
            "position": 1,
            "regime_ok": True,
            "entry_signal": True,
            "because": ["Entry: breakout triggered and regime_ok"],
        }
        # Should not raise
        _validate_decision_action(decision)

    def test_valid_abstain_passes(self):
        decision = {
            "action": "ABSTAIN",
            "position": 0,
            "regime_ok": False,
            "entry_signal": False,
            "because": ["Regime fail: close<=MA150"],
        }
        # Should not raise
        _validate_decision_action(decision)

    def test_rejects_exit_action(self):
        decision = {
            "action": "EXIT",
            "position": 0,
            "because": ["some reason"],
        }
        with pytest.raises(ValueError, match="invalid action.*EXIT"):
            _validate_decision_action(decision)

    def test_rejects_unknown_action(self):
        decision = {
            "action": "UNKNOWN",
            "position": 0,
            "because": ["some reason"],
        }
        with pytest.raises(ValueError, match="invalid action.*UNKNOWN"):
            _validate_decision_action(decision)

    def test_rejects_short_action(self):
        decision = {
            "action": "SHORT",
            "position": -1,
            "because": ["some reason"],
        }
        with pytest.raises(ValueError, match="invalid action.*SHORT"):
            _validate_decision_action(decision)

    def test_enter_requires_position_one(self):
        decision = {
            "action": "ENTER",
            "position": 0,
            "because": ["Entry triggered"],
        }
        with pytest.raises(ValueError, match="ENTER requires position=1"):
            _validate_decision_action(decision)

    def test_abstain_requires_nonempty_because(self):
        decision = {
            "action": "ABSTAIN",
            "position": 0,
            "because": [],
        }
        with pytest.raises(ValueError, match="non-empty 'because'"):
            _validate_decision_action(decision)

    def test_abstain_rejects_missing_because(self):
        decision = {
            "action": "ABSTAIN",
            "position": 0,
        }
        with pytest.raises(ValueError, match="non-empty 'because'"):
            _validate_decision_action(decision)

    def test_enter_with_multiple_reasons(self):
        decision = {
            "action": "ENTER",
            "position": 1,
            "because": [
                "Hold: trailing stop intact",
                "Entry: breakout triggered and regime_ok",
            ],
        }
        # Should not raise
        _validate_decision_action(decision)
