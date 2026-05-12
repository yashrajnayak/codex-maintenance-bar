#!/usr/bin/env python3
"""Backup and prune archived Codex chats.

Dry-run is safe while Codex is open. Apply refuses to run until Codex is closed
unless --quit-codex is passed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import shutil
import sqlite3
import subprocess
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CODEX_HOME = Path("~/.codex").expanduser()
ARCHIVED_DIR = CODEX_HOME / "archived_sessions"
STATE_DB = CODEX_HOME / "state_5.sqlite"
SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
BACKUP_ROOT = CODEX_HOME / "maintenance_backups" / "archived-chat-prune"
REPORT_ROOT = CODEX_HOME / "maintenance_reports"
DEFAULT_KEEP_THREADS: set[str] = set()


@dataclass(frozen=True)
class ArchivedThread:
    id: str
    updated_at: int
    title: str
    rollout_path: Path
    size: int


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def codex_is_running() -> tuple[bool, list[str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    hits = []
    for line in result.stdout.splitlines():
        command = line.strip()
        if (
            "/Applications/Codex.app/" in command
            or command.endswith(" codex app-server")
            or "Contents/Resources/codex app-server" in command
        ):
            hits.append(command)
    return bool(hits), hits


def codex_process_ids() -> list[int]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    pids = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid_text, command = parts
        if (
            "/Applications/Codex.app/" in command
            or command.endswith(" codex app-server")
            or "Contents/Resources/codex app-server" in command
        ):
            try:
                pids.append(int(pid_text))
            except ValueError:
                pass
    return pids


def quit_codex(force: bool) -> list[str]:
    actions: list[str] = []
    if not codex_is_running()[0]:
        return ["Codex was not running."]

    if os.uname().sysname == "Darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "Codex" to quit'],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        actions.append("Asked Codex.app to quit gracefully.")

    for _ in range(15):
        if not codex_is_running()[0]:
            actions.append("Codex exited cleanly.")
            return actions
        time.sleep(1)

    for pid in codex_process_ids():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    actions.append("Sent SIGTERM to remaining Codex process(es).")

    for _ in range(10):
        if not codex_is_running()[0]:
            actions.append("Codex exited after SIGTERM.")
            return actions
        time.sleep(1)

    if force:
        for pid in codex_process_ids():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        actions.append("Sent SIGKILL to remaining Codex process(es).")

    return actions


def connect_state(readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{STATE_DB}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
    else:
        con = sqlite3.connect(STATE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def archived_threads(keep_threads: set[str]) -> list[ArchivedThread]:
    with connect_state(readonly=True) as con:
        rows = con.execute(
            """
            SELECT id, updated_at, title, rollout_path
            FROM threads
            WHERE archived = 1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    threads = []
    for row in rows:
        if row["id"] in keep_threads:
            continue
        path = Path(row["rollout_path"])
        size = path.stat().st_size if path.exists() else 0
        threads.append(
            ArchivedThread(
                id=row["id"],
                updated_at=row["updated_at"],
                title=row["title"],
                rollout_path=path,
                size=size,
            )
        )
    return threads


def archived_files_on_disk(keep_threads: set[str]) -> list[Path]:
    if not ARCHIVED_DIR.exists():
        return []
    files = []
    for path in ARCHIVED_DIR.rglob("*.jsonl"):
        if any(thread_id in path.name for thread_id in keep_threads):
            continue
        files.append(path)
    return sorted(files)


def write_manifest(threads: list[ArchivedThread], files: list[Path], path: Path) -> None:
    thread_ids = {thread.id for thread in threads}
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["thread_id", "updated_at_utc", "size_bytes", "rollout_path", "title"],
        )
        writer.writeheader()
        for thread in threads:
            writer.writerow(
                {
                    "thread_id": thread.id,
                    "updated_at_utc": datetime.fromtimestamp(thread.updated_at, timezone.utc).isoformat(),
                    "size_bytes": thread.size,
                    "rollout_path": str(thread.rollout_path),
                    "title": thread.title.replace("\n", "\\n"),
                }
            )
        for file_path in files:
            if any(thread_id in file_path.name for thread_id in thread_ids):
                continue
            writer.writerow(
                {
                    "thread_id": "",
                    "updated_at_utc": "",
                    "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
                    "rollout_path": str(file_path),
                    "title": "orphan archived transcript file",
                }
            )


def create_backup(threads: list[ArchivedThread], files: list[Path], timestamp: str) -> Path:
    backup_dir = BACKUP_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    write_manifest(threads, files, backup_dir / "archived_threads_manifest.csv")

    with connect_state(readonly=True) as source:
        dest = sqlite3.connect(backup_dir / "state_5.sqlite")
        try:
            source.backup(dest)
        finally:
            dest.close()

    for path in (SESSION_INDEX, CODEX_HOME / ".codex-global-state.json", CODEX_HOME / "config.toml"):
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)

    tar_path = backup_dir / "archived_sessions.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for file_path in files:
            if file_path.exists():
                tar.add(file_path, arcname=file_path.relative_to(CODEX_HOME))

    meta = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "codex_home": str(CODEX_HOME),
        "archived_thread_count": len(threads),
        "archived_file_count": len(files),
        "archived_file_bytes": sum(path.stat().st_size for path in files if path.exists()),
    }
    (backup_dir / "backup_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return backup_dir


def filter_session_index(removed_thread_ids: set[str], backup_dir: Path | None) -> int:
    if not SESSION_INDEX.exists():
        return 0
    kept_lines: list[str] = []
    removed = 0
    for line in SESSION_INDEX.read_text().splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            kept_lines.append(line)
            continue
        if data.get("id") in removed_thread_ids:
            removed += 1
            continue
        kept_lines.append(line)

    if backup_dir is not None:
        SESSION_INDEX.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""))
    return removed


def prune_database(removed_thread_ids: set[str]) -> dict[str, int | str]:
    if not removed_thread_ids:
        return {"threads_deleted": 0, "integrity_check": "ok", "foreign_key_check_rows": 0}

    placeholders = ",".join("?" for _ in removed_thread_ids)
    ids = sorted(removed_thread_ids)
    with connect_state(readonly=False) as con:
        con.execute("BEGIN IMMEDIATE")
        parent_deleted = con.execute(
            f"DELETE FROM thread_spawn_edges WHERE parent_thread_id IN ({placeholders})", ids
        ).rowcount
        child_deleted = con.execute(
            f"DELETE FROM thread_spawn_edges WHERE child_thread_id IN ({placeholders})", ids
        ).rowcount
        assigned_cleared = con.execute(
            f"UPDATE agent_job_items SET assigned_thread_id = NULL WHERE assigned_thread_id IN ({placeholders})",
            ids,
        ).rowcount
        threads_deleted = con.execute(f"DELETE FROM threads WHERE id IN ({placeholders})", ids).rowcount
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_rows = len(con.execute("PRAGMA foreign_key_check").fetchall())

    return {
        "threads_deleted": threads_deleted,
        "spawn_parent_edges_deleted": parent_deleted,
        "spawn_child_edges_deleted": child_deleted,
        "agent_job_item_assignments_cleared": assigned_cleared,
        "integrity_check": integrity,
        "foreign_key_check_rows": fk_rows,
    }


def remove_archived_files(files: list[Path]) -> int:
    removed = 0
    for file_path in files:
        if file_path.exists():
            file_path.unlink()
            removed += 1

    for root, dirnames, filenames in os.walk(ARCHIVED_DIR, topdown=False):
        path = Path(root)
        if path == ARCHIVED_DIR:
            continue
        if not dirnames and not filenames:
            try:
                path.rmdir()
            except OSError:
                pass
    return removed


def write_report(
    timestamp: str,
    mode: str,
    threads: list[ArchivedThread],
    files: list[Path],
    backup_dir: Path | None,
    db_result: dict[str, int | str] | None = None,
    session_index_removed: int = 0,
    total_bytes: int | None = None,
) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    report = REPORT_ROOT / f"codex-archived-chat-prune-{timestamp}.md"
    total_bytes = total_bytes if total_bytes is not None else sum(path.stat().st_size for path in files if path.exists())
    lines = [
        "# Codex Archived Chat Prune Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- Mode: {mode}",
        f"- Codex home: `{CODEX_HOME}`",
        f"- Archived thread candidates: {len(threads)}",
        f"- Archived transcript files: {len(files)}",
        f"- Archived transcript bytes before removal: {total_bytes}",
        f"- Backup directory: `{backup_dir}`" if backup_dir else "- Backup directory: none (dry-run)",
        f"- Session index rows removed: {session_index_removed}",
    ]
    if db_result:
        lines.extend(["", "## Database Result", ""])
        for key, value in db_result.items():
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Largest Archived Threads", ""])
    for thread in sorted(threads, key=lambda item: item.size, reverse=True)[:25]:
        title = thread.title.replace("\n", " ")[:120]
        lines.append(f"- {thread.size} bytes | `{thread.id}` | {title}")
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> int:
    global CODEX_HOME, ARCHIVED_DIR, STATE_DB, SESSION_INDEX, BACKUP_ROOT, REPORT_ROOT

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="backup and remove archived chats")
    parser.add_argument("--codex-home", default=str(CODEX_HOME), help="Codex home directory")
    parser.add_argument("--backup-root", default=None, help="backup root; defaults under Codex maintenance_backups")
    parser.add_argument("--report-dir", default=None, help="directory for Markdown reports")
    parser.add_argument("--quit-codex", action="store_true", help="ask Codex to quit before apply")
    parser.add_argument("--force-quit-codex", action="store_true", help="allow SIGKILL if Codex does not quit")
    parser.add_argument("--keep-thread", action="append", default=[], help="archived thread id to preserve")
    args = parser.parse_args()

    CODEX_HOME = Path(args.codex_home).expanduser()
    ARCHIVED_DIR = CODEX_HOME / "archived_sessions"
    STATE_DB = CODEX_HOME / "state_5.sqlite"
    SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
    BACKUP_ROOT = Path(args.backup_root).expanduser() if args.backup_root else CODEX_HOME / "maintenance_backups" / "archived-chat-prune"
    REPORT_ROOT = Path(args.report_dir).expanduser() if args.report_dir else CODEX_HOME / "maintenance_reports"

    keep_threads = DEFAULT_KEEP_THREADS | set(args.keep_thread)
    timestamp = utc_timestamp()
    threads = archived_threads(keep_threads)
    files = archived_files_on_disk(keep_threads)
    archived_bytes = sum(path.stat().st_size for path in files if path.exists())

    running, processes = codex_is_running()
    quit_actions: list[str] = []
    if args.apply and running and args.quit_codex:
        quit_actions = quit_codex(args.force_quit_codex)
        running, processes = codex_is_running()

    if args.apply and running:
        print("Refusing to apply because Codex is running.")
        print("Close Codex completely, then rerun with --apply.")
        for process in processes[:8]:
            print(process)
        return 2

    if not args.apply:
        report = write_report(timestamp, "dry-run", threads, files, backup_dir=None, total_bytes=archived_bytes)
        print("mode=dry-run")
        print(f"archived_threads={len(threads)}")
        print(f"archived_files={len(files)}")
        print(f"bytes={archived_bytes}")
        print(f"codex_running={'yes' if running else 'no'}")
        print(f"report={report}")
        print(f"Report written to {report}")
        return 0

    backup_dir = create_backup(threads, files, timestamp)
    removed_ids = {thread.id for thread in threads}
    db_result = prune_database(removed_ids)
    if quit_actions:
        db_result["quit_actions"] = "; ".join(quit_actions)
    session_index_removed = filter_session_index(removed_ids, backup_dir)
    files_removed = remove_archived_files(files)
    db_result["archived_files_removed"] = files_removed
    report = write_report(
        timestamp,
        "apply",
        threads,
        files,
        backup_dir=backup_dir,
        db_result=db_result,
        session_index_removed=session_index_removed,
        total_bytes=archived_bytes,
    )

    print("mode=apply")
    print(f"backup={backup_dir}")
    print(f"report={report}")
    print(f"Backup written to {backup_dir}")
    print(f"Report written to {report}")
    for key, value in db_result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
