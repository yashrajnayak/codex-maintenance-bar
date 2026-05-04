#!/usr/bin/env bash
set -euo pipefail

LABEL="io.github.yashrajnayak.codex-maintenance-bar.login"
APP_PATH="${1:-$HOME/Applications/CodexMaintenanceBar.app}"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH_AGENTS_DIR/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found: $APP_PATH" >&2
  echo "Run ./script/install.sh first, or pass the app path as the first argument." >&2
  exit 2
fi

mkdir -p "$LAUNCH_AGENTS_DIR"

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>$APP_PATH</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST

/bin/launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "$DOMAIN" "$PLIST"
/bin/launchctl enable "$DOMAIN/$LABEL"

echo "Start at login enabled."
echo "LaunchAgent: $PLIST"
echo "App: $APP_PATH"
