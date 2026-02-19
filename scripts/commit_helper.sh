#!/usr/bin/env bash
# commit_helper.sh — safe commit + push for Codespaces / github.dev
#
# Usage:
#   bash scripts/commit_helper.sh "message"              # commit + push
#   bash scripts/commit_helper.sh --no-push "message"    # commit only
#   bash scripts/commit_helper.sh                        # interactive prompt + push
#   bash scripts/commit_helper.sh --allow-unstaged "msg" # skip unstaged warning
set -euo pipefail

# ── Override Codespaces GIT_EDITOR=true ─────────────────────────────
export GIT_EDITOR="code --wait"
export EDITOR="code --wait"
export VISUAL="code --wait"

# ── Parse flags ─────────────────────────────────────────────────────
DO_PUSH=true
ALLOW_UNSTAGED=false
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-push)        DO_PUSH=false;        shift ;;
        --allow-unstaged) ALLOW_UNSTAGED=true;  shift ;;
        --)              shift; POSITIONAL+=("$@"); break ;;
        -*)              echo "ERROR: Unknown flag: $1"; exit 1 ;;
        *)               POSITIONAL+=("$1");  shift ;;
    esac
done

# ── Check for staged changes ───────────────────────────────────────
staged=$(git diff --cached --name-status)
if [ -z "$staged" ]; then
    echo "ERROR: No staged changes. Stage files first:"
    echo "  git add <file>        # stage specific files"
    echo "  git add -A            # stage everything"
    exit 1
fi

# ── Warn about unstaged changes ────────────────────────────────────
unstaged=$(git diff --name-only)
if [ -n "$unstaged" ] && [ "$ALLOW_UNSTAGED" = false ]; then
    echo "WARNING: You have unstaged changes that will NOT be committed:"
    echo "$unstaged" | sed 's/^/  /'
    echo ""
    printf "Continue anyway? [y/N] "
    read -r yn
    case "$yn" in
        [Yy]*) ;;
        *)     echo "Aborted."; exit 1 ;;
    esac
fi

# ── Show staged summary ────────────────────────────────────────────
echo "Staged changes:"
echo "$staged" | sed 's/^/  /'
echo ""

# ── Get commit message ──────────────────────────────────────────────
if [ ${#POSITIONAL[@]} -gt 0 ]; then
    msg="${POSITIONAL[*]}"
else
    printf "Enter commit message: "
    read -r msg
fi

if [ -z "$msg" ]; then
    echo "ERROR: Empty commit message. Aborting."
    exit 1
fi

# ── Commit ──────────────────────────────────────────────────────────
echo "Committing..."
if ! git commit -m "$msg"; then
    echo ""
    echo "FAILED: git commit exited with error."
    exit 1
fi

# ── Push (unless --no-push) ─────────────────────────────────────────
if [ "$DO_PUSH" = true ]; then
    echo "Pushing to remote..."
    if ! git push; then
        echo ""
        echo "FAILED: git push exited with error. Commit succeeded but push did not."
        exit 1
    fi
fi

# ── Success ─────────────────────────────────────────────────────────
echo ""
echo "========================================="
if [ "$DO_PUSH" = true ]; then
    echo " SUCCESS: commit + push complete"
else
    echo " SUCCESS: commit complete (push skipped)"
fi
echo " Message: $msg"
echo " Branch:  $(git branch --show-current)"
echo " Remote:  $(git remote get-url origin)"
echo "========================================="
