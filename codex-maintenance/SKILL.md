---
name: codex-maintenance
description: Audit, back up, archive, restore, and safely clean local Codex Desktop state. Use when the user asks to keep Codex fast, clean old Codex sessions, archive stale chats, rotate Codex logs, prune dead Codex project config, create handoff docs for old threads, restore a Codex maintenance backup, or set up repeatable Codex local maintenance.
metadata:
  short-description: Keep Codex local state tidy and fast
---

# Codex Maintenance

Use the bundled script for deterministic work:

```sh
python3 scripts/codex_weekly_maintenance.py --write-report
```

Default mode is audit-only. It inspects Codex state, sessions, archived sessions, logs, config project paths, stale workspace folders, background processes, and SQLite schemas without changing anything.

## Workflow

1. Run audit first and read the report.
2. If Codex is open, either ask the user to quit it or use the explicit quit flags.
3. Run apply only when the user wants cleanup:

```sh
python3 scripts/codex_weekly_maintenance.py --apply --write-report
```

4. To close Codex before cleanup, use:

```sh
python3 scripts/codex_weekly_maintenance.py --quit-codex --force-quit-codex --apply --write-report
```

5. To restore from a backup:

```sh
python3 scripts/codex_weekly_maintenance.py --quit-codex --restore-backup /path/to/maintenance_backups/YYYYMMDDTHHMMSSZ
```

## Guardrails

- Never mutate Codex state while Codex is running unless the user explicitly asked to close Codex first.
- Prefer audit mode for diagnosis, support, or review.
- Keep `--force-quit-codex` opt-in because it can terminate in-flight work.
- Use `--keep-thread` or `--keep-title-regex` for sessions the user wants to keep active.
- Mention the backup path and report path after any apply or restore run.

## What Apply Does

- Acquires a lockfile to prevent overlapping runs.
- Creates a backup with `manifest.json`.
- Copies config, global state, session index, state/log databases, memories, skills, plugins, automations, and candidate session transcripts.
- Archives old active session JSONL files and updates the local state database.
- Creates handoff docs for archived threads.
- Prunes missing or temporary project paths from config.
- Moves stale Codex workspaces into an archive folder.
- Rotates large Codex logs.
- Writes a Markdown report.

## Common Options

- `--archive-days 10`: archive active chats older than this many days.
- `--worktree-days 14`: move stale workspace folders older than this many days.
- `--log-mb 100`: rotate log databases above this size.
- `--codex-home PATH`: override Codex home, usually `~/.codex`.
- `--workspace-root PATH`: override Codex workspace root, usually `~/Documents/Codex`.
- `--skip-session-archive`, `--skip-config-prune`, `--skip-workspaces`, `--skip-logs`: narrow cleanup scope.
