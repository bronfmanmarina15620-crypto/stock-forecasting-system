#!/usr/bin/env bash
# git_safe.sh — wrapper that overrides Codespaces' GIT_EDITOR=true
#
# Codespaces sets GIT_EDITOR=true globally, which causes git to use the
# "true" binary as the editor (exits immediately, empty message, abort).
# This wrapper forces "code --wait" so git falls back to VS Code.
#
# Usage:  bash scripts/git_safe.sh commit -m "msg"
#         bash scripts/git_safe.sh <any git subcommand>

set -euo pipefail

export GIT_EDITOR="code --wait"
export EDITOR="code --wait"
export VISUAL="code --wait"

exec git "$@"
