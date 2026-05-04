#!/usr/bin/env bash
set -euo pipefail

APP_NAME="CodexMaintenanceBar"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLED_APP="$HOME/Applications/$APP_NAME.app"
BUILT_APP="$ROOT_DIR/dist/$APP_NAME.app"

if [[ -d "$INSTALLED_APP" ]]; then
  /usr/bin/open "$INSTALLED_APP"
elif [[ -d "$BUILT_APP" ]]; then
  /usr/bin/open "$BUILT_APP"
else
  "$ROOT_DIR/script/build_and_run.sh"
fi
