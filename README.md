# Codex Maintenance Bar

A tiny macOS menu bar app for running Codex local maintenance.

It can:

- Run a safe audit and write a report.
- Run cleanup by quitting Codex first, backing up state, archiving stale sessions, rotating logs, pruning dead config projects, and writing a report.
- Open the latest maintenance report.
- Open report and backup folders.
- Copy the last command output.

The app bundles the `codex_weekly_maintenance.py` script, so it does not require the Codex skill to be installed.

## Build And Run

```sh
./script/build_and_run.sh
```

The built app bundle is staged at:

```text
dist/CodexMaintenanceBar.app
```

## Verify

```sh
./script/build_and_run.sh --verify
```

## Safety

The cleanup action intentionally closes Codex before touching its local state database:

```sh
python3 codex_weekly_maintenance.py --quit-codex --force-quit-codex --apply --write-report
```

Run audit first if you want a read-only look at what cleanup would do.
