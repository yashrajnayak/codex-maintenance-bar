#!/usr/bin/env bash
set -euo pipefail

APP_NAME="codex-powertoyz"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
RELEASE_DIR="$DIST_DIR/release"
ASSET_NAME="$APP_NAME-macos.zip"
CHECKSUMS_NAME="checksums.txt"

VERSION="${1:-${GITHUB_REF_NAME:-}}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(git -C "$ROOT_DIR" describe --tags --always --dirty 2>/dev/null || date -u +%Y%m%d%H%M%S)"
fi
VERSION="${VERSION#refs/tags/}"
APP_VERSION="${VERSION#v}"
if [[ -z "$APP_VERSION" ]]; then
  APP_VERSION="0.0.0"
fi
BUNDLE_VERSION="${GITHUB_RUN_NUMBER:-1}"

rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"

APP_VERSION="$APP_VERSION" BUNDLE_VERSION="$BUNDLE_VERSION" SWIFT_CONFIGURATION=release \
  "$ROOT_DIR/script/build_and_run.sh" --bundle >/dev/null

/usr/bin/plutil -lint "$APP_BUNDLE/Contents/Info.plist" >/dev/null
test -x "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
test -x "$APP_BUNDLE/Contents/Resources/codex_weekly_maintenance.py"
test -x "$APP_BUNDLE/Contents/Resources/codex_workspace_artifact_cleanup.py"
test -x "$APP_BUNDLE/Contents/Resources/codex_cache_cleanup.py"
test -x "$APP_BUNDLE/Contents/Resources/codex_archived_chat_prune.py"

if [[ "${CODE_SIGN:-1}" != "0" ]]; then
  SIGN_IDENTITY="${CODE_SIGN_IDENTITY:--}"
  /usr/bin/codesign --force --deep --sign "$SIGN_IDENTITY" "$APP_BUNDLE"
  /usr/bin/codesign --verify --deep --strict "$APP_BUNDLE"
fi

ZIP_PATH="$RELEASE_DIR/$ASSET_NAME"
CHECKSUMS_PATH="$RELEASE_DIR/$CHECKSUMS_NAME"

(
  cd "$DIST_DIR"
  /usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP_NAME.app" "$ZIP_PATH"
)

(
  cd "$RELEASE_DIR"
  /usr/bin/shasum -a 256 "$ASSET_NAME" > "$CHECKSUMS_NAME"
)

echo "Packaged $ZIP_PATH"
echo "Checksums $CHECKSUMS_PATH"
