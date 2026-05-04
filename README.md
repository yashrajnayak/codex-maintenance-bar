# Codex Maintenance Bar

A small macOS menu bar app for running Codex local maintenance.

It lives in the status bar, not the Dock. Look for the small hammer/checkmark icon near the clock.

## What It Does

- `Audit Now`: read-only check of Codex sessions, logs, config, and workspaces. Opens the report when finished.
- `Cleanup Now`: closes Codex first, backs up state, archives stale sessions, rotates logs, prunes dead config paths, writes a report, and opens it when finished.
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

## Important Safety Note

`Cleanup Now` closes the Codex desktop app before touching its local state database. That means any active Codex chat window may disappear during cleanup.

Run `Audit Now` first if you want a read-only preview.

Under the hood, cleanup runs:

```sh
python3 codex_weekly_maintenance.py --quit-codex --force-quit-codex --apply --write-report
```

The menu bar app itself stays open unless you click `Quit`.
