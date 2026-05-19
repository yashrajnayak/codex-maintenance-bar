#!/usr/bin/env bash
set -euo pipefail

APP_NAME="codex-powertoyz"
ASSET_NAME="$APP_NAME-macos.zip"
REPO="${CODEX_POWERTOYZ_REPO:-yashrajnayak/codex-powertoyz}"
VERSION="${CODEX_POWERTOYZ_VERSION:-latest}"
RELEASE_URL="${CODEX_POWERTOYZ_RELEASE_URL:-}"
INSTALL_DIR="${CODEX_POWERTOYZ_INSTALL_DIR:-$HOME/Applications}"
ENABLE_LOGIN="${CODEX_POWERTOYZ_ENABLE_LOGIN:-1}"
OPEN_AFTER="${CODEX_POWERTOYZ_OPEN:-1}"
REMOVE_QUARANTINE="${CODEX_POWERTOYZ_REMOVE_QUARANTINE:-0}"

usage() {
  cat <<USAGE
usage: $0 [--version vX.Y.Z] [--repo owner/name] [--url URL] [--install-dir path] [--no-login] [--no-open] [--remove-quarantine]

Downloads the GitHub Release app zip, installs $APP_NAME.app, and opens the menu bar app.

Options:
  --version VERSION       Install a specific release tag instead of the latest release.
  --repo OWNER/NAME       Install from another GitHub repository.
  --url URL               Install from a direct release asset URL.
  --install-dir PATH      Install location. Default: ~/Applications.
  --no-login              Do not enable the LaunchAgent that opens the app at login.
  --no-open               Install without opening the app.
  --remove-quarantine     Remove the browser-download quarantine attribute after install.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:?missing version}"
      shift 2
      ;;
    --repo)
      REPO="${2:?missing repo}"
      shift 2
      ;;
    --url)
      RELEASE_URL="${2:?missing URL}"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="${2:?missing install dir}"
      shift 2
      ;;
    --no-login)
      ENABLE_LOGIN=0
      shift
      ;;
    --no-open)
      OPEN_AFTER=0
      shift
      ;;
    --remove-quarantine)
      REMOVE_QUARANTINE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$INSTALL_DIR" in
  "~") INSTALL_DIR="$HOME" ;;
  "~/"*) INSTALL_DIR="$HOME/${INSTALL_DIR#"~/"}" ;;
esac

if [[ -n "$RELEASE_URL" ]]; then
  DOWNLOAD_URL="$RELEASE_URL"
elif [[ "$VERSION" == "latest" ]]; then
  DOWNLOAD_URL="https://github.com/$REPO/releases/latest/download/$ASSET_NAME"
else
  DOWNLOAD_URL="https://github.com/$REPO/releases/download/$VERSION/$ASSET_NAME"
fi

WORK_DIR="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/codex-powertoyz-install.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

ZIP_PATH="$WORK_DIR/$ASSET_NAME"
EXTRACT_DIR="$WORK_DIR/extract"
mkdir -p "$EXTRACT_DIR"

echo "Downloading $DOWNLOAD_URL"
/usr/bin/curl --fail --location --show-error --progress-bar "$DOWNLOAD_URL" --output "$ZIP_PATH"

/usr/bin/ditto -x -k "$ZIP_PATH" "$EXTRACT_DIR"
SOURCE_APP="$EXTRACT_DIR/$APP_NAME.app"
if [[ ! -d "$SOURCE_APP" ]]; then
  SOURCE_APP="$(/usr/bin/find "$EXTRACT_DIR" -maxdepth 3 -type d -name "$APP_NAME.app" -print -quit)"
fi
if [[ -z "${SOURCE_APP:-}" || ! -d "$SOURCE_APP" ]]; then
  echo "Could not find $APP_NAME.app in downloaded release asset." >&2
  exit 1
fi

INSTALLED_APP="$INSTALL_DIR/$APP_NAME.app"
/usr/bin/pkill -x "$APP_NAME" >/dev/null 2>&1 || true
/bin/mkdir -p "$INSTALL_DIR"
/bin/rm -rf "$INSTALLED_APP"
/usr/bin/ditto "$SOURCE_APP" "$INSTALLED_APP"

if [[ "$REMOVE_QUARANTINE" == "1" ]]; then
  /usr/bin/xattr -dr com.apple.quarantine "$INSTALLED_APP" >/dev/null 2>&1 || true
fi

enable_start_at_login() {
  local label="io.github.yashrajnayak.codex-powertoyz.login"
  local launch_agents_dir="$HOME/Library/LaunchAgents"
  local plist="$launch_agents_dir/$label.plist"
  local domain="gui/$(id -u)"

  /bin/mkdir -p "$launch_agents_dir"
  cat >"$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>$INSTALLED_APP</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
PLIST

  /bin/launchctl bootout "$domain" "$plist" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "$domain" "$plist"
  /bin/launchctl enable "$domain/$label"
  echo "Start at login enabled: $plist"
}

if [[ "$ENABLE_LOGIN" == "1" ]]; then
  if ! enable_start_at_login; then
    echo "Installed, but start at login could not be enabled. You can enable it from the app menu." >&2
  fi
fi

if [[ "$OPEN_AFTER" == "1" ]]; then
  /usr/bin/open "$INSTALLED_APP"
fi

echo "Installed: $INSTALLED_APP"
echo "Look for the wand icon near the clock."
