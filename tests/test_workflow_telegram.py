"""Sanity-check that workflow YAML Telegram messages use numeric exit codes.

Loads both nightly workflow YAMLs as raw text and asserts the Telegram
message templates contain the expected exit-code patterns:
  - Success: "exit=0"
  - Failure: numeric exit code variable (not string "FAIL")
  - Missing-summary guardrail: EDGE_SUMMARY_MISSING with exit=2 fallback
"""
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = [
    os.path.join(REPO_ROOT, ".github", "workflows", "nightly_pltr.yml"),
    os.path.join(REPO_ROOT, ".github", "workflows", "nightly_pltr_shadow.yml"),
]


@pytest.fixture(params=WORKFLOWS, ids=["nightly_pltr", "nightly_pltr_shadow"])
def workflow_text(request):
    with open(request.param) as f:
        return f.read()


class TestTelegramExitCodes:
    """Telegram messages must report numeric edge exit codes."""

    def test_success_message_contains_exit_0(self, workflow_text):
        assert "exit=0" in workflow_text, (
            "Success Telegram message must contain 'exit=0'"
        )

    def test_failure_message_uses_numeric_exit_code(self, workflow_text):
        # The failure template must reference the numeric variable, not
        # the string PASS/FAIL from edge_pass.
        # Two patterns: inline "${EDGE_EXIT_CODE}" or printf arg "$EDGE_EXIT_CODE".
        has_inline = "exit=${EDGE_EXIT_CODE}" in workflow_text
        has_printf_arg = (
            '"$EDGE_EXIT_CODE"' in workflow_text
            and "exit=%s" in workflow_text
        )
        assert has_inline or has_printf_arg, (
            "Failure Telegram message must use numeric EDGE_EXIT_CODE variable"
        )

    def test_no_exit_equals_fail_string(self, workflow_text):
        # Ensure old "exit=FAIL" / "exit=${EDGE_EXIT}" patterns are gone.
        assert "exit=${EDGE_EXIT}" not in workflow_text or \
               "exit=${EDGE_EXIT_CODE}" in workflow_text, (
            "Must not use old EDGE_EXIT (string PASS/FAIL) for exit= field"
        )
        assert 'exit=FAIL' not in workflow_text, (
            "Literal 'exit=FAIL' must not appear in Telegram messages"
        )

    def test_edge_exit_code_exported(self, workflow_text):
        assert "edge_exit_code=" in workflow_text, (
            "Workflow must export edge_exit_code from edge_summary.json"
        )

    def test_missing_summary_fallback(self, workflow_text):
        assert "EDGE_SUMMARY_MISSING" in workflow_text, (
            "Missing edge_summary.json must set failure_class=EDGE_SUMMARY_MISSING"
        )

    def test_missing_summary_exit_code_2(self, workflow_text):
        # When edge_summary.json is absent, edge_exit_code must default to 2.
        # Check that the else-branch sets edge_exit_code=2.
        assert 'edge_exit_code=2' in workflow_text or \
               'EDGE_EXIT_CODE:-2' in workflow_text, (
            "Missing edge_summary.json must default edge_exit_code to 2"
        )

    def test_fix_hint_for_edge_summary_missing(self, workflow_text):
        assert "edge_summary.json not produced" in workflow_text, (
            "EDGE_SUMMARY_MISSING must include fix hint about edge_summary.json"
        )
