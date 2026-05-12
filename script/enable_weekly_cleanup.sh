#!/usr/bin/env bash
set -euo pipefail

LABEL="io.github.yashrajnayak.codex-powertoyz.weekly-maintenance"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT_DIR="$HOME/Library/Application Support/codex-powertoyz"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
SCRIPT_SOURCE="$ROOT_DIR/Sources/CodexPowertoyz/Resources/codex_weekly_maintenance.py"
SCRIPT_DEST="$SUPPORT_DIR/codex_weekly_maintenance.py"
PLIST="$LAUNCH_AGENTS_DIR/$LABEL.plist"
STDOUT_LOG="$SUPPORT_DIR/weekly-cleanup.out.log"
STDERR_LOG="$SUPPORT_DIR/weekly-cleanup.err.log"
DOMAIN="gui/$(id -u)"

mkdir -p "$SUPPORT_DIR" "$LAUNCH_AGENTS_DIR"
cp "$SCRIPT_SOURCE" "$SCRIPT_DEST"
chmod +x "$SCRIPT_DEST"

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$SCRIPT_DEST</string>
    <string>--quit-codex</string>
    <string>--force-quit-codex</string>
    <string>--apply</string>
    <string>--write-report</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>9</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$STDOUT_LOG</string>
  <key>StandardErrorPath</key>
  <string>$STDERR_LOG</string>
</dict>
</plist>
PLIST

/bin/launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "$DOMAIN" "$PLIST"
/bin/launchctl enable "$DOMAIN/$LABEL"

echo "Weekly cleanup enabled for Mondays at 9:00 AM."
echo "LaunchAgent: $PLIST"
echo "Script copy: $SCRIPT_DEST"
echo "Logs: $STDOUT_LOG and $STDERR_LOG"
