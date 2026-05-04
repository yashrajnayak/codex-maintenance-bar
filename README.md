# Codex Maintenance Bar

A small macOS menu bar app for running Codex local maintenance.

It lives in the status bar, not the Dock. Look for the small hammer/checkmark icon near the clock.

## Related Repositories

- [codex-maintenance-bar](https://github.com/yashrajnayak/codex-maintenance-bar): this repo, the macOS menu bar app for manual cleanup, scheduling, and start-at-login.
- [codex-maintenance](https://github.com/yashrajnayak/codex-maintenance): source-of-truth cleanup script and Codex skill bundled by this app.

## What It Does

- `Audit Now`: read-only check of Codex sessions, logs, config, and workspaces. Opens the report when finished.
- `Cleanup Now`: closes Codex first, backs up state, archives stale sessions, rotates logs, prunes dead config paths, writes a report, and opens it when finished.
- `Enable Weekly Cleanup`: installs a macOS LaunchAgent that runs cleanup every Monday at 9:00 AM.
- `Disable Weekly Cleanup`: removes the LaunchAgent.
- `Schedule Folder`: opens the LaunchAgent log/script folder.
- `Enable Start at Login`: opens the menu bar app automatically after login/restart.
- `Disable Start at Login`: removes that login LaunchAgent.
- `Open Latest Report`: opens the newest Markdown maintenance report.
- `Reports Folder`: opens `~/.codex/maintenance_reports`.
- `Backups Folder`: opens `~/.codex/maintenance_backups`.
- `Copy Last Output`: copies the last script output to the clipboard.

The app bundles the maintenance script, so it does not require the Codex skill to be installed.

## Install

From this repo:

```sh
./script/install.sh
```

This builds the app, installs it to:

```text
~/Applications/CodexMaintenanceBar.app
```

and opens it.

`install.sh` also enables start at login, so the menu bar app reappears after a restart.

## Reopen After Quitting

If you click `Quit` in the menu bar app, the icon disappears. To open it again:

```sh
open ~/Applications/CodexMaintenanceBar.app
```

or from this repo:

```sh
./script/open_app.sh
```

You can also open `~/Applications` in Finder and double-click `CodexMaintenanceBar.app`.

## Open Automatically After Restart

The app uses a LaunchAgent login item:

```text
~/Library/LaunchAgents/io.github.yashrajnayak.codex-maintenance-bar.login.plist
```

Enable it from the menu bar app:

```text
Enable Start at Login
```

or from Terminal:

```sh
./script/enable_start_at_login.sh
```

Disable it with:

```sh
./script/disable_start_at_login.sh
```

Check whether it is loaded:

```sh
launchctl print "gui/$(id -u)/io.github.yashrajnayak.codex-maintenance-bar.login"
```

## Run Without Installing

Build and launch from the repo:

```sh
./script/build_and_run.sh
```

The built app bundle is staged at:

```text
dist/CodexMaintenanceBar.app
```

If you quit it, reopen the staged build with:

```sh
open dist/CodexMaintenanceBar.app
```

## Verify

```sh
./script/build_and_run.sh --verify
```

## Keeping The Script In Sync

`codex-maintenance` is the source of truth for the cleanup script. This app keeps a bundled copy at:

```text
Sources/CodexMaintenanceBar/Resources/codex_weekly_maintenance.py
```

When the maintenance script changes upstream, update this app with:

```sh
./script/sync_maintenance_script.sh
```

Then commit and push the result.

CI also checks this automatically:

```sh
./script/sync_maintenance_script.sh --check
```

For local development against a sibling checkout:

```sh
LOCAL_SOURCE=/path/to/codex-maintenance ./script/sync_maintenance_script.sh
```

## Weekly Schedule

The app can install a user LaunchAgent so cleanup runs even when the menu bar app is not open.

From the menu bar app, click:

```text
Enable Weekly Cleanup
```

This creates:

```text
~/Library/LaunchAgents/io.github.yashrajnayak.codex-maintenance.weekly.plist
```

and copies the bundled maintenance script to:

```text
~/Library/Application Support/CodexMaintenanceBar/codex_weekly_maintenance.py
```

The schedule runs every Monday at 9:00 AM and executes the script directly:

```sh
/usr/bin/python3 ~/Library/Application\ Support/CodexMaintenanceBar/codex_weekly_maintenance.py --quit-codex --force-quit-codex --apply --write-report
```

You can also enable or disable the schedule from Terminal:

```sh
./script/enable_weekly_cleanup.sh
./script/disable_weekly_cleanup.sh
```

Scheduled-run logs live in:

```text
~/Library/Application Support/CodexMaintenanceBar/
```

## Important Safety Note

`Cleanup Now` closes the Codex desktop app before touching its local state database. That means any active Codex chat window may disappear during cleanup.

Run `Audit Now` first if you want a read-only preview.

Under the hood, cleanup runs:

```sh
python3 codex_weekly_maintenance.py --quit-codex --force-quit-codex --apply --write-report
```

The menu bar app itself stays open unless you click `Quit`.
