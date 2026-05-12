#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-sync}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_SCRIPT="$ROOT_DIR/codex_weekly_maintenance.py"
APP_SCRIPT="$ROOT_DIR/Sources/CodexMaintenanceBar/Resources/codex_weekly_maintenance.py"
SKILL_SCRIPT="$ROOT_DIR/codex-maintenance/scripts/codex_weekly_maintenance.py"

usage() {
  echo "usage: $0 [sync|--check]" >&2
  echo "" >&2
  echo "Copies the canonical root maintenance script into the app bundle and Codex skill." >&2
}

require_root_script() {
  if [[ ! -f "$ROOT_SCRIPT" ]]; then
    echo "Missing canonical script: $ROOT_SCRIPT" >&2
    exit 2
  fi
}

check_copy() {
  local label="$1"
  local path="$2"

  if [[ ! -f "$path" ]]; then
    echo "Missing $label script copy: $path" >&2
    return 1
  fi

  if ! cmp -s "$ROOT_SCRIPT" "$path"; then
    echo "$label script copy is out of sync with $ROOT_SCRIPT" >&2
    return 1
  fi
}

require_root_script

case "$MODE" in
  sync)
    cp "$ROOT_SCRIPT" "$APP_SCRIPT"
    cp "$ROOT_SCRIPT" "$SKILL_SCRIPT"
    chmod +x "$ROOT_SCRIPT" "$APP_SCRIPT" "$SKILL_SCRIPT"
    echo "Synced app and skill script copies from $ROOT_SCRIPT"
    ;;
  --check|check)
    if check_copy "App bundle" "$APP_SCRIPT" && check_copy "Codex skill" "$SKILL_SCRIPT"; then
      echo "Maintenance script copies are in sync."
    else
      echo "Run: $0 sync" >&2
      exit 1
    fi
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
