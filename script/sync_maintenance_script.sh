#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-sync}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT_DIR/Sources/CodexMaintenanceBar/Resources/codex_weekly_maintenance.py"
UPSTREAM_REF="${UPSTREAM_REF:-main}"
UPSTREAM_RAW_URL="${UPSTREAM_RAW_URL:-https://raw.githubusercontent.com/yashrajnayak/codex-maintenance/$UPSTREAM_REF/codex_weekly_maintenance.py}"
LOCAL_SOURCE="${LOCAL_SOURCE:-}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
TMP_SCRIPT="$TMP_DIR/codex_weekly_maintenance.py"

usage() {
  echo "usage: $0 [sync|--check]" >&2
  echo "" >&2
  echo "Environment:" >&2
  echo "  LOCAL_SOURCE=/path/to/codex-maintenance  Use a local checkout instead of GitHub raw." >&2
  echo "  UPSTREAM_REF=main                         Git ref to fetch from upstream." >&2
  echo "  UPSTREAM_RAW_URL=https://...              Full raw script URL override." >&2
}

fetch_source() {
  if [[ -n "$LOCAL_SOURCE" ]]; then
    if [[ -f "$LOCAL_SOURCE/codex_weekly_maintenance.py" ]]; then
      cp "$LOCAL_SOURCE/codex_weekly_maintenance.py" "$TMP_SCRIPT"
      return
    fi

    if [[ -f "$LOCAL_SOURCE/codex-maintenance/scripts/codex_weekly_maintenance.py" ]]; then
      cp "$LOCAL_SOURCE/codex-maintenance/scripts/codex_weekly_maintenance.py" "$TMP_SCRIPT"
      return
    fi

    echo "Could not find codex_weekly_maintenance.py under LOCAL_SOURCE=$LOCAL_SOURCE" >&2
    exit 2
  fi

  curl -fsSL "$UPSTREAM_RAW_URL" -o "$TMP_SCRIPT"
}

fetch_source

case "$MODE" in
  sync)
    cp "$TMP_SCRIPT" "$DEST"
    chmod +x "$DEST"
    echo "Synced maintenance script from $UPSTREAM_RAW_URL"
    ;;
  --check|check)
    if cmp -s "$TMP_SCRIPT" "$DEST"; then
      echo "Bundled maintenance script is in sync."
    else
      echo "Bundled maintenance script is out of sync with $UPSTREAM_RAW_URL" >&2
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
