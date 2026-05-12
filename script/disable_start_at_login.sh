#!/usr/bin/env bash
set -euo pipefail

LABEL="io.github.yashrajnayak.codex-powertoyz.login"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

/bin/launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "Start at login disabled."
