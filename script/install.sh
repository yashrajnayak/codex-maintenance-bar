#!/usr/bin/env bash
set -euo pipefail

APP_NAME="CodexMaintenanceBar"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${1:-$HOME/Applications}"
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"
INSTALLED_APP="$INSTALL_DIR/$APP_NAME.app"

"$ROOT_DIR/script/build_and_run.sh" --bundle >/dev/null

pkill -x "$APP_NAME" >/dev/null 2>&1 || true
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALLED_APP"
/usr/bin/ditto "$APP_BUNDLE" "$INSTALLED_APP"

/usr/bin/open "$INSTALLED_APP"
"$ROOT_DIR/script/enable_start_at_login.sh" "$INSTALLED_APP"

echo "Installed and opened: $INSTALLED_APP"
echo "To reopen later: open \"$INSTALLED_APP\""
echo "Start at login is enabled."
