#!/usr/bin/env python3
"""Audit and optionally clean up local Codex state.

Default mode is read-only. Use --apply only after quitting Codex.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


UTC = timezone.utc
SCRIPT_VERSION = "0.2.0"
PROJECT_HEADER_RE = re.compile(r'^\[projects\."(?P<path>(?:\\.|[^"])*)"\]\s*$')
WINDOWS_EXTENDED_PATH_RE = re.compile(r"\\\\\?\\([A-Za-z]:\\)")
WINDOWS_DRIVE_RE = re.compile(r"[A-Za-z]:\\")
REQUIRED_THREAD_COLUMNS = {"id", "title", "rollout_path", "cwd", "archived"}
REQUIRED_LOG_COLUMNS = {"id", "ts", "level", "target"}


@dataclass
class ThreadRow:
    id: str
    title: str
    rollout_path: Path
    cwd: str
    archived: bool
    updated_ms: int
    tokens_used: int
    size_bytes: int = 0
    pinned: bool = False


@dataclass
class Audit:
    codex_home: Path
    workspace_root: Path
    codex_running: bool
    state_db: Path | None = None
    logs_db: Path | None = None
    codex_processes: list[str] = field(default_factory=list)
    size_map: dict[str, int] = field(default_factory=dict)
    state_counts: dict[str, int] = field(default_factory=dict)
    log_count: int | None = None
    active_threads: list[ThreadRow] = field(default_factory=list)
    archive_candidates: list[ThreadRow] = field(default_factory=list)
    pinned_thread_ids: set[str] = field(default_factory=set)
    missing_project_paths: list[str] = field(default_factory=list)
    temp_project_paths: list[str] = field(default_factory=list)
    stale_workspaces: list[tuple[Path, int]] = field(default_factory=list)
    weird_path_hits: list[str] = field(default_factory=list)
    background_processes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def human_bytes(size: int | None) -> str:
    if size is None:
        return "n/a"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        out = subprocess.check_output(["du", "-sk", str(path)], text=True, stderr=subprocess.DEVNULL)
        return int(out.split()[0]) * 1024
    except Exception:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                pass
        return total


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() else 0
    except OSError:
        return 0


def sqlite_uri(path: Path, mode: str = "ro") -> str:
    return f"file:{quote(str(path), safe='/')}?mode={mode}"


def connect_sqlite(path: Path, read_only: bool = True) -> sqlite3.Connection:
    if read_only:
        return sqlite3.connect(sqlite_uri(path, "ro"), uri=True)
    return sqlite3.connect(path)


def sqlite_table_columns(path: Path, table: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        conn = connect_sqlite(path, read_only=True)
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        conn.close()
    except Exception:
        return set()
    return {str(row[1]) for row in rows}


def find_sqlite_db(codex_home: Path, pattern: str, table: str, required_columns: set[str]) -> Path | None:
    candidates = sorted(codex_home.glob(pattern), key=lambda path: file_size(path), reverse=True)
    for candidate in candidates:
        columns = sqlite_table_columns(candidate, table)
        if required_columns.issubset(columns):
            return candidate
    return None


def find_state_db(codex_home: Path) -> Path | None:
    preferred = codex_home / "state_5.sqlite"
    if REQUIRED_THREAD_COLUMNS.issubset(sqlite_table_columns(preferred, "threads")):
        return preferred
    return find_sqlite_db(codex_home, "state_*.sqlite", "threads", REQUIRED_THREAD_COLUMNS)


def find_logs_db(codex_home: Path) -> Path | None:
    preferred = codex_home / "logs_2.sqlite"
    if REQUIRED_LOG_COLUMNS.issubset(sqlite_table_columns(preferred, "logs")):
        return preferred
    return find_sqlite_db(codex_home, "logs_*.sqlite", "logs", REQUIRED_LOG_COLUMNS)


def ms_to_iso(ms: int) -> str:
    if not ms:
        return "unknown"
    if ms < 10_000_000_000:
        dt = datetime.fromtimestamp(ms, UTC)
    else:
        dt = datetime.fromtimestamp(ms / 1000, UTC)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def run_ps() -> list[str]:
    try:
        out = subprocess.check_output(["ps", "-axo", "pid,args"], text=True)
    except Exception:
        return []
    return [line.strip() for line in out.splitlines()[1:] if line.strip()]


def codex_process_entries() -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    current_pid = os.getpid()
    for line in run_ps():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        args = parts[1]
        if pid == current_pid:
            continue
        if "Codex.app/Contents" in args or "codex app-server" in args:
            entries.append((pid, args))
    return entries


def codex_process_lines() -> list[str]:
    return [f"{pid} {args}" for pid, args in codex_process_entries()]


def wait_for_codex_exit(timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not codex_process_entries():
            return True
        time.sleep(2)
    return not codex_process_entries()


def terminate_process(pid: int, force: bool = False) -> None:
    if sys.platform == "win32":
        cmd = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            cmd.append("/F")
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def quit_codex_before_cleanup(timeout_seconds: int, force_kill: bool = False) -> list[str]:
    actions: list[str] = []
    if not codex_process_entries():
        actions.append("Codex was not running.")
        return actions

    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Codex" to quit'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            actions.append("Asked Codex.app to quit gracefully.")
        except Exception as exc:
            actions.append(f"Could not ask Codex.app to quit gracefully: {exc}")
    else:
        actions.append("Graceful app quit is only implemented for macOS; using process termination.")

    if wait_for_codex_exit(timeout_seconds):
        actions.append("Codex exited cleanly.")
        return actions

    remaining = codex_process_entries()
    for pid, _ in remaining:
        try:
            terminate_process(pid, force=False)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            actions.append(f"Could not terminate Codex process {pid}: {exc}")
    actions.append(f"Sent SIGTERM to {len(remaining)} remaining Codex process(es).")

    if wait_for_codex_exit(15):
        actions.append("Codex exited after SIGTERM.")
        return actions

    if not force_kill:
        actions.append("Codex is still running after SIGTERM; use --force-quit-codex to allow SIGKILL/taskkill /F.")
        return actions

    remaining = codex_process_entries()
    for pid, _ in remaining:
        try:
            terminate_process(pid, force=True)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            actions.append(f"Could not force-kill Codex process {pid}: {exc}")
    actions.append(f"Sent SIGKILL to {len(remaining)} remaining Codex process(es).")

    if wait_for_codex_exit(5):
        actions.append("Codex exited after SIGKILL.")
    else:
        actions.append("Some Codex processes are still running after SIGKILL.")
    return actions


def background_process_lines() -> list[str]:
    terms = re.compile(r"\b(node|npm|pnpm|yarn|bun|vite|next|webpack|turbo|tsx|uvicorn|django|rails)\b", re.I)
    matches = []
    for line in run_ps():
        if terms.search(line) and "codex_weekly_maintenance.py" not in line:
            matches.append(line)
    return matches[:30]


def read_threads(codex_home: Path, audit: Audit) -> list[ThreadRow]:
    db = audit.state_db or find_state_db(codex_home)
    if not db:
        audit.errors.append(f"No supported Codex state database found under {codex_home}")
        return []
    try:
        conn = connect_sqlite(db, read_only=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select
                id,
                title,
                rollout_path,
                cwd,
                archived,
                coalesce(updated_at_ms, updated_at) as updated_ms,
                tokens_used
            from threads
            order by coalesce(updated_at_ms, updated_at) desc
            """
        ).fetchall()
        counts = conn.execute("select archived, count(*) from threads group by archived").fetchall()
        audit.state_counts = {("archived" if row[0] else "active"): int(row[1]) for row in counts}
        conn.close()
    except Exception as exc:
        audit.errors.append(f"Could not read state database: {exc}")
        return []

    threads: list[ThreadRow] = []
    for row in rows:
        rollout = Path(row["rollout_path"]) if row["rollout_path"] else Path()
        threads.append(
            ThreadRow(
                id=row["id"],
                title=row["title"] or "(untitled)",
                rollout_path=rollout,
                cwd=row["cwd"] or "",
                archived=bool(row["archived"]),
                updated_ms=int(row["updated_ms"] or 0),
                tokens_used=int(row["tokens_used"] or 0),
                size_bytes=file_size(rollout),
            )
        )
    return threads


def extract_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(extract_strings(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(extract_strings(item))
        return out
    return []


def find_pinned_thread_ids(codex_home: Path) -> set[str]:
    state_path = codex_home / ".codex-global-state.json"
    if not state_path.exists():
        return set()
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        return set()
    ids: set[str] = set()
    id_re = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")

    def visit(key_path: str, value: Any) -> None:
        lowered = key_path.lower()
        if any(word in lowered for word in ("pin", "pinned", "star", "favorite", "favourite")):
            for text in extract_strings(value):
                ids.update(id_re.findall(text))
        if isinstance(value, dict):
            for key, child in value.items():
                visit(f"{key_path}.{key}" if key_path else str(key), child)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(f"{key_path}.{i}", child)

    visit("", state)
    return ids


def config_project_paths(config_path: Path) -> list[str]:
    if not config_path.exists():
        return []
    paths = []
    for line in config_path.read_text().splitlines():
        match = PROJECT_HEADER_RE.match(line)
        if match:
            paths.append(match.group("path").replace('\\"', '"').replace("\\\\", "\\"))
    return paths


def stale_workspace_candidates(workspace_root: Path, days: int, current_path: Path) -> list[tuple[Path, int]]:
    if not workspace_root.exists():
        return []
    cutoff = datetime.now(UTC).timestamp() - days * 86400
    candidates: list[tuple[Path, int]] = []
    archive_names = {"_archived_workspaces", "archived_worktrees", "archived-worktrees"}
    for child in workspace_root.iterdir():
        if child.name in archive_names or child.name.startswith("."):
            continue
        try:
            resolved_child = child.resolve()
            resolved_current = current_path.resolve()
            if resolved_child == resolved_current or resolved_current.is_relative_to(resolved_child):
                continue
        except Exception:
            pass
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            candidates.append((child, path_size(child)))
    return sorted(candidates, key=lambda item: item[1], reverse=True)


def scan_json_weird_paths(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    hits: list[str] = []

    def visit(key_path: str, value: Any) -> None:
        if "prompt-history" in key_path:
            return
        if isinstance(value, str):
            if WINDOWS_EXTENDED_PATH_RE.search(value) or "\\\\?\\" in value:
                hits.append(f"{path}:{key_path}: extended Windows path")
            elif WINDOWS_DRIVE_RE.search(value) and os.name != "nt":
                hits.append(f"{path}:{key_path}: Windows drive path")
            return
        if isinstance(value, dict):
            for key, child in value.items():
                visit(f"{key_path}.{key}" if key_path else str(key), child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(f"{key_path}.{index}", child)

    visit("", data)
    return hits


def scan_weird_paths(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        if path.suffix == ".json":
            hits.extend(scan_json_weird_paths(path))
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if WINDOWS_EXTENDED_PATH_RE.search(line) or "\\\\?\\" in line:
                hits.append(f"{path}:{i}: extended Windows path")
            elif WINDOWS_DRIVE_RE.search(line) and os.name != "nt":
                hits.append(f"{path}:{i}: Windows drive path")
    return hits


def audit_state(args: argparse.Namespace) -> Audit:
    codex_home = Path(args.codex_home).expanduser() if args.codex_home else Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    workspace_root = Path(args.workspace_root).expanduser() if args.workspace_root else Path("~/Documents/Codex").expanduser()
    audit = Audit(
        codex_home=codex_home,
        workspace_root=workspace_root,
        codex_running=bool(codex_process_lines()),
    )
    audit.state_db = find_state_db(codex_home)
    audit.logs_db = find_logs_db(codex_home)
    audit.codex_processes = codex_process_lines()

    state_wal = Path(str(audit.state_db) + "-wal") if audit.state_db else None
    logs_wal = Path(str(audit.logs_db) + "-wal") if audit.logs_db else None
    size_targets = [
        codex_home,
        codex_home / "sessions",
        codex_home / "archived_sessions",
        codex_home / "log",
        audit.logs_db,
        logs_wal,
        audit.state_db,
        state_wal,
        codex_home / ".tmp",
        codex_home / "skills",
        codex_home / "plugins",
        codex_home / "memories",
        codex_home / "automations",
        workspace_root,
        workspace_root / "_archived_workspaces",
    ]
    audit.size_map = {str(path): path_size(path) for path in size_targets if path and path.exists()}

    threads = read_threads(codex_home, audit)
    pinned = find_pinned_thread_ids(codex_home).union(set(args.keep_thread or []))
    audit.pinned_thread_ids = pinned
    title_patterns = [re.compile(pattern, re.I) for pattern in args.keep_title_regex or []]
    cutoff_ms = int((datetime.now(UTC).timestamp() - args.archive_days * 86400) * 1000)
    for thread in threads:
        thread.pinned = thread.id in pinned or any(pattern.search(thread.title) for pattern in title_patterns)
    audit.active_threads = [thread for thread in threads if not thread.archived]
    audit.archive_candidates = [
        thread for thread in audit.active_threads if thread.updated_ms < cutoff_ms and not thread.pinned
    ]
    audit.archive_candidates.sort(key=lambda thread: thread.size_bytes, reverse=True)

    config_path = codex_home / "config.toml"
    projects = config_project_paths(config_path)
    audit.missing_project_paths = sorted(path for path in projects if not Path(path).exists())
    temp_roots = [codex_home / ".tmp", Path("/tmp"), Path("/private/tmp"), Path("/var/folders")]
    audit.temp_project_paths = sorted(
        path for path in projects if any(str(Path(path)).startswith(str(root)) for root in temp_roots)
    )
    audit.stale_workspaces = stale_workspace_candidates(workspace_root, args.worktree_days, Path.cwd())
    audit.weird_path_hits = scan_weird_paths(
        [config_path, codex_home / ".codex-global-state.json"]
    )
    audit.background_processes = background_process_lines()

    logs_db = audit.logs_db
    if logs_db and logs_db.exists():
        try:
            conn = connect_sqlite(logs_db, read_only=True)
            audit.log_count = int(conn.execute("select count(*) from logs").fetchone()[0])
            conn.close()
        except Exception as exc:
            audit.errors.append(f"Could not read logs database: {exc}")
    return audit


def top_threads(threads: list[ThreadRow], limit: int = 10) -> list[ThreadRow]:
    return sorted(threads, key=lambda thread: thread.size_bytes, reverse=True)[:limit]


def extract_user_messages(jsonl_path: Path, limit: int = 6) -> list[str]:
    if not jsonl_path.exists():
        return []
    messages: list[str] = []
    last_seen = None
    try:
        with jsonl_path.open() as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                payload = item.get("payload", {})
                text = None
                if payload.get("type") == "message" and payload.get("role") == "user":
                    parts = []
                    for content in payload.get("content", []):
                        if isinstance(content, dict) and content.get("type") == "input_text":
                            parts.append(content.get("text", ""))
                    text = "\n".join(part for part in parts if part)
                elif item.get("type") == "event_msg" and payload.get("type") == "user_message":
                    text = payload.get("message")
                if text and text != last_seen:
                    messages.append(text.strip())
                    last_seen = text
                    if len(messages) > limit:
                        messages = messages[-limit:]
    except Exception:
        return []
    return messages[-limit:]


def write_handoff(thread: ThreadRow, handoff_dir: Path) -> Path:
    handoff_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", thread.title.strip())[:70].strip("-") or "thread"
    path = handoff_dir / f"{thread.id}-{safe_title}.md"
    messages = extract_user_messages(thread.rollout_path)
    prompt = (
        "Resume this Codex task from the handoff below. Read the referenced workspace files if they still exist, "
        "then continue in a fresh chat instead of loading the old full transcript."
    )
    lines = [
        f"# Codex Handoff: {thread.title}",
        "",
        f"- Thread ID: `{thread.id}`",
        f"- Last updated: `{ms_to_iso(thread.updated_ms)}`",
        f"- Previous workspace: `{thread.cwd}`",
        f"- Archived transcript: `{thread.rollout_path}`",
        f"- Approx transcript size: `{human_bytes(thread.size_bytes)}`",
        "",
        "## Reactivation Prompt",
        "",
        prompt,
        "",
        "## Recent User Messages",
        "",
    ]
    if messages:
        for message in messages:
            lines.append("```text")
            lines.append(message[:4000])
            lines.append("```")
            lines.append("")
    else:
        lines.append("_No user messages could be extracted from the transcript._")
        lines.append("")
    path.write_text("\n".join(lines))
    return path


def backup_sqlite(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    try:
        source = connect_sqlite(src, read_only=True)
        target = sqlite3.connect(dest)
        source.backup(target)
        target.close()
        source.close()
    except Exception:
        shutil.copy2(src, dest)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(src) + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, Path(str(dest) + suffix))


def copy_path(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class MaintenanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    def __enter__(self) -> "MaintenanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as handle:
                    json.dump({"pid": os.getpid(), "created_at": datetime.now(UTC).isoformat()}, handle)
                self.acquired = True
                return self
            except FileExistsError:
                stale = False
                try:
                    data = json.loads(self.path.read_text())
                    stale = not process_exists(int(data.get("pid", -1)))
                except Exception:
                    stale = True
                if stale:
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                raise SystemExit(f"Another Codex maintenance run appears active: {self.path}")

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def lock_path_for(args: argparse.Namespace, codex_home: Path) -> Path:
    if getattr(args, "lock_path", None):
        return Path(args.lock_path).expanduser()
    return codex_home / "maintenance.lock"


def write_manifest(backup_root: Path, manifest: dict[str, Any]) -> None:
    (backup_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def make_backup(audit: Audit, candidates: list[ThreadRow]) -> Path:
    backup_root = audit.codex_home / "maintenance_backups" / now_stamp()
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "script_version": SCRIPT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "codex_home": str(audit.codex_home),
        "workspace_root": str(audit.workspace_root),
        "state_db": str(audit.state_db) if audit.state_db else None,
        "logs_db": str(audit.logs_db) if audit.logs_db else None,
        "copied_files": [],
        "copied_directories": [],
        "candidate_sessions": [],
        "session_moves": [],
        "workspace_moves": [],
        "rotated_logs": [],
        "config_pruned": False,
    }

    for name in (
        "config.toml",
        ".codex-global-state.json",
        ".codex-global-state.json.bak",
        "session_index.jsonl",
        "models_cache.json",
    ):
        copy_path(audit.codex_home / name, backup_root / name)
        if (audit.codex_home / name).exists():
            manifest["copied_files"].append(name)

    for dirname in ("memories", "skills", "plugins", "automations"):
        copy_path(audit.codex_home / dirname, backup_root / dirname)
        if (audit.codex_home / dirname).exists():
            manifest["copied_directories"].append(dirname)

    if audit.state_db:
        backup_sqlite(audit.state_db, backup_root / audit.state_db.name)
        manifest["copied_files"].append(audit.state_db.name)
    if audit.logs_db:
        backup_sqlite(audit.logs_db, backup_root / audit.logs_db.name)
        manifest["copied_files"].append(audit.logs_db.name)

    sessions_dir = backup_root / "sessions_to_archive"
    for thread in candidates:
        if thread.rollout_path.exists():
            copy_path(thread.rollout_path, sessions_dir / thread.rollout_path.name)
            manifest["candidate_sessions"].append(
                {
                    "id": thread.id,
                    "title": thread.title,
                    "original_path": str(thread.rollout_path),
                    "backup_path": str(sessions_dir / thread.rollout_path.name),
                    "size_bytes": thread.size_bytes,
                    "updated_ms": thread.updated_ms,
                }
            )

    write_manifest(backup_root, manifest)
    return backup_root


def load_manifest(backup_root: Path) -> dict[str, Any]:
    manifest_path = backup_root / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Backup is missing manifest.json: {backup_root}")
    return json.loads(manifest_path.read_text())


def destination_without_overwrite(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    counter = 2
    while True:
        candidate = dest.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def archive_sessions(
    audit: Audit,
    candidates: list[ThreadRow],
    handoff_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    actions: list[str] = []
    if not candidates:
        return actions
    if not audit.state_db:
        actions.append("Skipped session archiving because no supported state database was found.")
        return actions
    db = audit.state_db
    archive_dir = audit.codex_home / "archived_sessions"
    archive_dir.mkdir(parents=True, exist_ok=True)
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    conn = connect_sqlite(db, read_only=False)
    try:
        for thread in candidates:
            if not thread.rollout_path.exists():
                actions.append(f"Skipped missing transcript for {thread.id}: {thread.rollout_path}")
                continue
            handoff = write_handoff(thread, handoff_dir)
            dest = destination_without_overwrite(archive_dir / thread.rollout_path.name)
            shutil.move(str(thread.rollout_path), str(dest))
            conn.execute(
                "update threads set archived = 1, archived_at = ?, rollout_path = ? where id = ?",
                (now_ms, str(dest), thread.id),
            )
            if manifest is not None:
                manifest["session_moves"].append(
                    {
                        "id": thread.id,
                        "title": thread.title,
                        "original_path": str(thread.rollout_path),
                        "archived_path": str(dest),
                        "handoff_path": str(handoff),
                    }
                )
            actions.append(f"Archived {thread.id} -> {dest} with handoff {handoff}")
        conn.commit()
    finally:
        conn.close()
    return actions


def split_toml_sections(text: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, list[str]]] = []
    current_header: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("[") and line.rstrip().endswith("]"):
            if current_lines or current_header is not None:
                sections.append((current_header, current_lines))
            current_header = line.rstrip("\n")
            current_lines = [line]
        else:
            current_lines.append(line)
    sections.append((current_header, current_lines))
    return [(header, "".join(lines)) for header, lines in sections]


def normalize_and_prune_config(audit: Audit, manifest: dict[str, Any] | None = None) -> list[str]:
    config_path = audit.codex_home / "config.toml"
    if not config_path.exists():
        return []
    original = config_path.read_text()
    normalized = WINDOWS_EXTENDED_PATH_RE.sub(r"\1", original)
    actions: list[str] = []
    if normalized != original:
        actions.append("Normalized extended Windows path prefixes in config.toml")

    sections = split_toml_sections(normalized)
    kept: list[str] = []
    removed: list[str] = []
    temp_roots = [audit.codex_home / ".tmp", Path("/tmp"), Path("/private/tmp"), Path("/var/folders")]
    for header, body in sections:
        match = PROJECT_HEADER_RE.match(header or "")
        if not match:
            kept.append(body)
            continue
        project_path = match.group("path").replace('\\"', '"').replace("\\\\", "\\")
        path = Path(project_path)
        is_temp = any(str(path).startswith(str(root)) for root in temp_roots)
        if not path.exists() or is_temp:
            removed.append(project_path)
            continue
        kept.append(body)
    updated = "".join(kept)
    if updated != original:
        config_path.write_text(updated)
        if manifest is not None:
            manifest["config_pruned"] = True
            manifest["removed_project_paths"] = removed
    if removed:
        actions.append(f"Removed {len(removed)} dead/temp project entries from config.toml")
    return actions


def move_stale_workspaces(
    audit: Audit,
    candidates: list[tuple[Path, int]],
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    if not candidates:
        return []
    dest_root = audit.workspace_root / "_archived_workspaces" / now_stamp()
    dest_root.mkdir(parents=True, exist_ok=True)
    actions = []
    for path, size in candidates:
        if not path.exists():
            continue
        dest = destination_without_overwrite(dest_root / path.name)
        shutil.move(str(path), str(dest))
        if manifest is not None:
            manifest["workspace_moves"].append(
                {"original_path": str(path), "archived_path": str(dest), "size_bytes": size}
            )
        actions.append(f"Moved stale workspace {path} ({human_bytes(size)}) -> {dest}")
    return actions


def rotate_large_logs(
    audit: Audit,
    threshold_bytes: int,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    if not audit.logs_db:
        return []
    logs = [
        audit.logs_db,
        Path(str(audit.logs_db) + "-wal"),
        Path(str(audit.logs_db) + "-shm"),
    ]
    total = sum(file_size(path) for path in logs)
    if total < threshold_bytes:
        return []
    dest_root = audit.codex_home / "maintenance_archives" / "logs" / now_stamp()
    dest_root.mkdir(parents=True, exist_ok=True)
    actions = []
    for path in logs:
        if path.exists():
            dest = destination_without_overwrite(dest_root / path.name)
            shutil.move(str(path), str(dest))
            if manifest is not None:
                manifest["rotated_logs"].append({"original_path": str(path), "archived_path": str(dest)})
            actions.append(f"Rotated log file {path} -> {dest}")
    return actions


def render_report(audit: Audit, args: argparse.Namespace, actions: list[str] | None = None) -> str:
    actions = actions or []
    mode = "restore" if getattr(args, "restore_backup", None) else ("apply" if args.apply else "audit")
    lines = [
        "# Codex Weekly Maintenance Report",
        "",
        f"- Generated: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- Mode: `{mode}`",
        f"- Codex home: `{audit.codex_home}`",
        f"- Workspace root: `{audit.workspace_root}`",
        f"- State database: `{audit.state_db or 'not found'}`",
        f"- Logs database: `{audit.logs_db or 'not found'}`",
        f"- Codex running: `{'yes' if audit.codex_running else 'no'}`",
        "",
        "## Size Hotspots",
        "",
    ]
    for path, size in sorted(audit.size_map.items(), key=lambda item: item[1], reverse=True)[:16]:
        lines.append(f"- `{path}`: {human_bytes(size)}")

    lines.extend(["", "## Thread State", ""])
    active = audit.state_counts.get("active", 0)
    archived = audit.state_counts.get("archived", 0)
    lines.append(f"- Active threads in DB: `{active}`")
    lines.append(f"- Archived threads in DB: `{archived}`")
    lines.append(f"- Pinned thread ids detected: `{len(audit.pinned_thread_ids)}`")
    if audit.log_count is not None:
        lines.append(f"- Rows in logs database: `{audit.log_count}`")

    lines.extend(["", "## Largest Active Chats", ""])
    for thread in top_threads(audit.active_threads, 12):
        lines.append(
            f"- {human_bytes(thread.size_bytes)} | `{ms_to_iso(thread.updated_ms)}` | `{thread.id}` | {thread.title[:120]}"
        )

    lines.extend(["", f"## Archive Candidates Older Than {args.archive_days} Days", ""])
    if audit.archive_candidates:
        total = sum(thread.size_bytes for thread in audit.archive_candidates)
        lines.append(f"- Candidate count: `{len(audit.archive_candidates)}`")
        lines.append(f"- Candidate transcript size: `{human_bytes(total)}`")
        for thread in audit.archive_candidates[:20]:
            lines.append(
                f"- {human_bytes(thread.size_bytes)} | `{ms_to_iso(thread.updated_ms)}` | `{thread.id}` | {thread.title[:120]}"
            )
    else:
        lines.append("- No archive candidates found.")

    lines.extend(["", "## Config And Paths", ""])
    lines.append(f"- Missing project paths in config: `{len(audit.missing_project_paths)}`")
    for path in audit.missing_project_paths[:20]:
        lines.append(f"- Missing: `{path}`")
    lines.append(f"- Temp project paths in config: `{len(audit.temp_project_paths)}`")
    lines.append(f"- Weird Windows path hits: `{len(audit.weird_path_hits)}`")
    for hit in audit.weird_path_hits[:20]:
        lines.append(f"- {hit}")

    lines.extend(["", f"## Stale Workspaces Older Than {args.worktree_days} Days", ""])
    if audit.stale_workspaces:
        total = sum(size for _, size in audit.stale_workspaces)
        lines.append(f"- Candidate count: `{len(audit.stale_workspaces)}`")
        lines.append(f"- Candidate size: `{human_bytes(total)}`")
        for path, size in audit.stale_workspaces[:20]:
            lines.append(f"- {human_bytes(size)} | `{path}`")
    else:
        lines.append("- No stale workspace candidates found.")

    lines.extend(["", "## Background Processes", ""])
    if audit.background_processes:
        for process in audit.background_processes[:20]:
            lines.append(f"- `{process}`")
    else:
        lines.append("- No obvious heavy Node/dev-server processes found.")

    if audit.codex_processes:
        lines.extend(["", "## Codex Processes", ""])
        for process in audit.codex_processes[:12]:
            lines.append(f"- `{process}`")

    if actions:
        lines.extend(["", "## Actions Taken", ""])
        for action in actions:
            lines.append(f"- {action}")

    if audit.errors:
        lines.extend(["", "## Errors", ""])
        for error in audit.errors:
            lines.append(f"- {error}")

    lines.extend(
        [
            "",
            "## Weekly Usage",
            "",
            "Audit only:",
            "",
            "```sh",
            f"python3 {Path(__file__).resolve()} --write-report",
            "```",
            "",
            "Apply after quitting Codex:",
            "",
            "```sh",
            f"python3 {Path(__file__).resolve()} --apply --write-report",
            "```",
            "",
            "Apply and close Codex first:",
            "",
            "```sh",
            f"python3 {Path(__file__).resolve()} --quit-codex --force-quit-codex --apply --write-report",
            "```",
            "",
            "Restore a backup:",
            "",
            "```sh",
            f"python3 {Path(__file__).resolve()} --quit-codex --restore-backup /path/to/maintenance_backups/YYYYMMDDTHHMMSSZ",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(report: str, args: argparse.Namespace, codex_home: Path) -> Path:
    report_dir = Path(args.report_dir).expanduser() if args.report_dir else codex_home / "maintenance_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"codex-maintenance-{now_stamp()}.md"
    path.write_text(report)
    return path


def apply_cleanup(args: argparse.Namespace, audit: Audit) -> list[str]:
    actions: list[str] = []
    if args.quit_codex:
        actions.extend(quit_codex_before_cleanup(args.codex_quit_timeout, args.force_quit_codex))
        audit = audit_state(args)

    if audit.codex_running:
        raise SystemExit("Codex is running. Quit Codex before running with --apply.")

    candidates = [] if args.skip_session_archive else audit.archive_candidates
    backup_path = make_backup(audit, candidates)
    manifest = load_manifest(backup_path)
    actions.append(f"Backup written to {backup_path}")

    handoff_dir = backup_path / "handoffs"
    if not args.skip_session_archive:
        actions.extend(archive_sessions(audit, candidates, handoff_dir, manifest))
    if not args.skip_config_prune:
        actions.extend(normalize_and_prune_config(audit, manifest))
    if not args.skip_workspaces:
        actions.extend(move_stale_workspaces(audit, audit.stale_workspaces, manifest))
    if not args.skip_logs:
        actions.extend(rotate_large_logs(audit, args.log_mb * 1024 * 1024, manifest))
    write_manifest(backup_path, manifest)
    if len(actions) == 1:
        actions.append("No cleanup candidates needed changes.")
    return actions


def stash_existing(dest: Path, backup_root: Path) -> None:
    if not dest.exists():
        return
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(dest).strip("/")) or dest.name
    stash_dir = backup_root / "restore_overwritten"
    stash_dir.mkdir(parents=True, exist_ok=True)
    stash_dest = destination_without_overwrite(stash_dir / safe_name)
    shutil.move(str(dest), str(stash_dest))


def restore_copy(src: Path, dest: Path, backup_root: Path) -> None:
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    stash_existing(dest, backup_root)
    copy_path(src, dest)


def restore_backup(args: argparse.Namespace) -> list[str]:
    backup_root = Path(args.restore_backup).expanduser()
    manifest = load_manifest(backup_root)
    target_codex_home = (
        Path(args.codex_home).expanduser()
        if args.codex_home
        else Path(manifest.get("codex_home") or Path.home() / ".codex").expanduser()
    )
    target_workspace_root = (
        Path(args.workspace_root).expanduser()
        if args.workspace_root
        else Path(manifest.get("workspace_root") or Path.home() / "Documents" / "Codex").expanduser()
    )
    args.codex_home = str(target_codex_home)
    args.workspace_root = str(target_workspace_root)

    audit = audit_state(args)
    actions: list[str] = []
    if args.quit_codex:
        actions.extend(quit_codex_before_cleanup(args.codex_quit_timeout, args.force_quit_codex))
        audit = audit_state(args)
    if audit.codex_running:
        raise SystemExit("Codex is running. Quit Codex before restoring a backup.")

    for name in manifest.get("copied_files", []):
        src = backup_root / name
        dest = target_codex_home / name
        restore_copy(src, dest, backup_root)
        actions.append(f"Restored file {dest}")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(src) + suffix)
            if sidecar.exists():
                restore_copy(sidecar, Path(str(dest) + suffix), backup_root)
                actions.append(f"Restored file {dest}{suffix}")

    for dirname in manifest.get("copied_directories", []):
        src = backup_root / dirname
        dest = target_codex_home / dirname
        restore_copy(src, dest, backup_root)
        actions.append(f"Restored directory {dest}")

    for session in manifest.get("candidate_sessions", []):
        src = Path(session.get("backup_path", ""))
        dest = Path(session.get("original_path", ""))
        if src.exists() and dest:
            restore_copy(src, dest, backup_root)
            actions.append(f"Restored session transcript {dest}")

    for move in manifest.get("workspace_moves", []):
        archived = Path(move.get("archived_path", ""))
        original = Path(move.get("original_path", ""))
        if archived.exists() and original and not original.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived), str(original))
            actions.append(f"Moved workspace back to {original}")

    for move in manifest.get("rotated_logs", []):
        archived = Path(move.get("archived_path", ""))
        original = Path(move.get("original_path", ""))
        if archived.exists() and original:
            restore_copy(archived, original, backup_root)
            actions.append(f"Restored rotated log {original}")

    if not actions:
        actions.append("No restorable files were found in the backup manifest.")
    return actions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and optionally clean up local Codex state.")
    parser.add_argument("--apply", action="store_true", help="make changes; refuses to run while Codex is open")
    parser.add_argument("--backup-only", action="store_true", help="write a backup and exit")
    parser.add_argument("--write-report", action="store_true", help="write a Markdown report")
    parser.add_argument("--report-dir", help="directory for Markdown reports")
    parser.add_argument("--codex-home", help="Codex home directory; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("--workspace-root", help="Codex workspace/worktree root; defaults to ~/Documents/Codex")
    parser.add_argument("--archive-days", type=int, default=10, help="archive active chats older than this many days")
    parser.add_argument("--worktree-days", type=int, default=14, help="move workspace folders older than this many days")
    parser.add_argument("--log-mb", type=int, default=100, help="rotate logs_2 sqlite files above this many MB")
    parser.add_argument("--quit-codex", action="store_true", help="quit Codex before applying cleanup; escalates to SIGTERM if needed")
    parser.add_argument("--force-quit-codex", action="store_true", help="allow SIGKILL/taskkill /F if Codex does not exit after SIGTERM")
    parser.add_argument("--codex-quit-timeout", type=int, default=60, help="seconds to wait for Codex to quit gracefully")
    parser.add_argument("--restore-backup", help="restore files and moved sessions from a maintenance backup directory")
    parser.add_argument("--lock-path", help="custom lockfile path for apply/restore/backup operations")
    parser.add_argument("--keep-thread", action="append", default=[], help="thread id to keep active even if old")
    parser.add_argument("--keep-title-regex", action="append", default=[], help="case-insensitive title pattern to keep active")
    parser.add_argument("--skip-session-archive", action="store_true")
    parser.add_argument("--skip-config-prune", action="store_true")
    parser.add_argument("--skip-workspaces", action="store_true")
    parser.add_argument("--skip-logs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.force_quit_codex and not args.quit_codex:
        raise SystemExit("--force-quit-codex only has an effect with --quit-codex.")

    audit = audit_state(args)
    actions: list[str] = []

    needs_lock = args.backup_only or args.apply or bool(args.restore_backup)
    if needs_lock:
        with MaintenanceLock(lock_path_for(args, audit.codex_home)):
            if args.restore_backup:
                actions.extend(restore_backup(args))
                audit = audit_state(args)
            if args.backup_only:
                backup_path = make_backup(audit, audit.archive_candidates)
                actions.append(f"Backup written to {backup_path}")
            if args.apply:
                actions.extend(apply_cleanup(args, audit))
                audit = audit_state(args)

    report = render_report(audit, args, actions)
    print(report)
    if args.write_report:
        report_path = write_report(report, args, audit.codex_home)
        print(f"Report written to {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
