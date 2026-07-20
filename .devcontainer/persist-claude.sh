#!/usr/bin/env bash
# Keeps Claude Code's auth/history/session state on the devcontainer's
# claude-code-config volume (mounted at ~/.claude) so it survives rebuilds.
#
# ~/.claude.json lives outside that directory as a single file, so it's
# symlinked into the volume. Re-run on every container start (not just
# create) in case Claude Code ever replaces the symlink with a fresh real
# file instead of writing through it.
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
CLAUDE_JSON="$HOME/.claude.json"
PERSISTED_JSON="$CLAUDE_DIR/.claude.json"

mkdir -p "$CLAUDE_DIR"
sudo chown -R vscode:vscode "$CLAUDE_DIR"

if [ -f "$CLAUDE_JSON" ] && [ ! -L "$CLAUDE_JSON" ]; then
  cp -f "$CLAUDE_JSON" "$PERSISTED_JSON"
fi

ln -sf "$PERSISTED_JSON" "$CLAUDE_JSON"
chown -h vscode:vscode "$CLAUDE_JSON"
