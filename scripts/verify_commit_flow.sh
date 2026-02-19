#!/usr/bin/env bash
# verify_commit_flow.sh — non-destructive regression test for the commit flow
# Exits 0 on PASS, 1 on FAIL. Does not modify repo state.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "FAIL: not inside a git repository"
    exit 1
fi

PASS=true

check() {
    local label="$1" ok="$2" reason="$3"
    if [ "$ok" = "true" ]; then
        echo "  PASS  $label"
    else
        echo "  FAIL  $label — $reason"
        PASS=false
    fi
}

echo "Commit-flow verification for: $REPO_ROOT"
echo ""

# 1. core.editor
editor=$(git config --local core.editor 2>/dev/null || true)
check "core.editor" \
    "$([ "$editor" = "code --wait" ] && echo true || echo false)" \
    "expected 'code --wait', got '${editor:-<unset>}'"

# 2. git_safe.sh exists + executable
gs="$REPO_ROOT/scripts/git_safe.sh"
check "scripts/git_safe.sh exists" \
    "$([ -f "$gs" ] && echo true || echo false)" \
    "file not found"
check "scripts/git_safe.sh executable" \
    "$([ -x "$gs" ] && echo true || echo false)" \
    "not executable (run: chmod +x scripts/git_safe.sh)"

# 3. commit_helper.sh exists + executable
ch="$REPO_ROOT/scripts/commit_helper.sh"
check "scripts/commit_helper.sh exists" \
    "$([ -f "$ch" ] && echo true || echo false)" \
    "file not found"
check "scripts/commit_helper.sh executable" \
    "$([ -x "$ch" ] && echo true || echo false)" \
    "not executable (run: chmod +x scripts/commit_helper.sh)"

# 4. .vscode/settings.json keys
vs="$REPO_ROOT/.vscode/settings.json"
if [ -f "$vs" ]; then
    for key in git.enableSmartCommit git.postCommitCommand git.confirmSync git.useEditorAsCommitInput; do
        check ".vscode/settings.json has $key" \
            "$(grep -q "\"$key\"" "$vs" && echo true || echo false)" \
            "key missing from $vs"
    done
else
    check ".vscode/settings.json exists" "false" "file not found"
    PASS=false
fi

# 5. No stale LFS hooks
for hook in post-commit post-merge; do
    hf="$REPO_ROOT/.git/hooks/$hook"
    if [ -f "$hf" ] && grep -q "git.lfs\|git-lfs" "$hf" 2>/dev/null; then
        check "no LFS $hook hook" "false" "stale LFS hook found at $hf — delete it"
    else
        check "no LFS $hook hook" "true" ""
    fi
done

echo ""
if [ "$PASS" = true ]; then
    echo "RESULT: PASS — commit flow is correctly configured"
    exit 0
else
    echo "RESULT: FAIL — fix the issues above, then re-run this script"
    exit 1
fi
