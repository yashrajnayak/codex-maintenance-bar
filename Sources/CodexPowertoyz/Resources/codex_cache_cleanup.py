#!/usr/bin/env python3
"""Audit and clean high-confidence Codex cache artifacts.

Default mode is read-only. Apply mode moves candidates into a timestamped
folder under macOS Trash instead of hard-deleting them.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


UTC = timezone.utc
DEFAULT_CODEX_HOME = Path("~/.codex").expanduser()
SCRIPT_VERSION = "0.1.0"


@dataclass(frozen=True)
class Candidate:
    path: Path
    category: str
    reason: str
    recommended_action: str
    risk: str
    size_bytes: int = 0


@dataclass(frozen=True)
class MoveResult:
    candidate: Candidate
    trash_path: Path | None
    status: str
    error: str = ""


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
        if path.is_file() or path.is_symlink():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total = 0
        for root, _dirnames, filenames in os.walk(path):
            for filename in filenames:
                try:
                    total += (Path(root) / filename).stat().st_size
                except OSError:
                    pass
        return total


def sqlite_uri(path: Path, mode: str = "ro") -> str:
    return f"file:{quote(str(path), safe='/')}?mode={mode}"


def sqlite_table_columns(path: Path, table: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        conn = sqlite3.connect(sqlite_uri(path), uri=True)
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        conn.close()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


def find_state_db(codex_home: Path) -> Path | None:
    preferred = codex_home / "state_5.sqlite"
    if {"id"}.issubset(sqlite_table_columns(preferred, "threads")):
        return preferred
    candidates = sorted(codex_home.glob("state_*.sqlite"), key=lambda path: path_size(path), reverse=True)
    for candidate in candidates:
        if {"id"}.issubset(sqlite_table_columns(candidate, "threads")):
            return candidate
    return None


def thread_ids(codex_home: Path) -> set[str]:
    state_db = find_state_db(codex_home)
    if not state_db:
        return set()
    try:
        conn = sqlite3.connect(sqlite_uri(state_db), uri=True)
        rows = conn.execute("select id from threads").fetchall()
        conn.close()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows}


def child_dirs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted([child for child in path.iterdir() if child.is_dir()], key=lambda child: child.name)


def newest_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda path: (path.stat().st_mtime, path.name))


def add_candidate(
    candidates: list[Candidate],
    path: Path,
    category: str,
    reason: str,
    recommended_action: str,
    risk: str,
) -> None:
    candidates.append(
        Candidate(
            path=path,
            category=category,
            reason=reason,
            recommended_action=recommended_action,
            risk=risk,
            size_bytes=path_size(path),
        )
    )


def old_general_maintenance_backups(codex_home: Path) -> list[Candidate]:
    root = codex_home / "maintenance_backups"
    backups = [path for path in child_dirs(root) if path.name != "archived-chat-prune"]
    keep = newest_path(backups)
    candidates: list[Candidate] = []
    for path in backups:
        if path == keep:
            continue
        add_candidate(
            candidates,
            path,
            "old_maintenance_backup",
            "Older Codex maintenance backup/restore snapshot; a newer general backup exists.",
            "Move to Trash if the older rollback point is no longer needed.",
            "medium: removes an older restore point",
        )
    return candidates


def old_archived_chat_prune_backups(codex_home: Path) -> list[Candidate]:
    root = codex_home / "maintenance_backups" / "archived-chat-prune"
    backups = child_dirs(root)
    keep = newest_path(backups)
    candidates: list[Candidate] = []
    for path in backups:
        if path == keep:
            continue
        add_candidate(
            candidates,
            path,
            "old_archived_chat_prune_backup",
            "Older archived-chat-prune restore snapshot; a newer prune backup exists.",
            "Move to Trash if the older archived-chat rollback copy is no longer needed.",
            "medium-high: removes an older restore point for pruned archived chats",
        )
    return candidates


def old_rotated_log_archives(codex_home: Path) -> list[Candidate]:
    root = codex_home / "maintenance_archives" / "logs"
    archives = child_dirs(root)
    keep = newest_path(archives)
    candidates: list[Candidate] = []
    for path in archives:
        if path == keep:
            continue
        add_candidate(
            candidates,
            path,
            "old_rotated_log_archive",
            "Older rotated Codex log database archive; a newer log archive exists.",
            "Move to Trash if historical logs are not needed.",
            "low-medium",
        )
    return candidates


def rebuildable_tmp_cache(codex_home: Path) -> list[Candidate]:
    root = codex_home / ".tmp"
    candidates: list[Candidate] = []
    if not root.exists():
        return candidates
    for path in sorted(root.iterdir(), key=lambda child: child.name):
        add_candidate(
            candidates,
            path,
            "rebuildable_codex_tmp",
            "Codex temporary/plugin-marketplace cache; rebuildable by Codex.",
            "Move to Trash; Codex can recreate it if needed.",
            "low-medium while Codex is closed",
        )
    return candidates


def orphan_generated_images(codex_home: Path) -> list[Candidate]:
    root = codex_home / "generated_images"
    ids = thread_ids(codex_home)
    candidates: list[Candidate] = []
    if not root.exists() or not ids:
        return candidates
    for path in child_dirs(root):
        if path.name in ids:
            continue
        add_candidate(
            candidates,
            path,
            "orphan_generated_images",
            "Generated image folder has no matching thread row in the current state database.",
            "Move to Trash after confirming final images were copied into project output folders.",
            "low-medium",
        )
    return candidates


def collect_candidates(codex_home: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    candidates.extend(old_general_maintenance_backups(codex_home))
    candidates.extend(old_archived_chat_prune_backups(codex_home))
    candidates.extend(old_rotated_log_archives(codex_home))
    candidates.extend(rebuildable_tmp_cache(codex_home))
    candidates.extend(orphan_generated_images(codex_home))

    seen: set[Path] = set()
    unique: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: str(item.path)):
        if candidate.path in seen:
            continue
        seen.add(candidate.path)
        unique.append(candidate)
    return sorted(unique, key=lambda item: item.size_bytes, reverse=True)


def destination_for(trash_root: Path, source: Path) -> Path:
    relative = Path(*source.parts[1:]) if source.is_absolute() else source
    dest = trash_root / relative
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    for counter in range(1, 10_000):
        candidate = dest.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find non-conflicting destination for {dest}")


def move_candidates(candidates: list[Candidate], trash_root: Path) -> list[MoveResult]:
    trash_root.mkdir(parents=True, exist_ok=True)
    results: list[MoveResult] = []
    for candidate in sorted(candidates, key=lambda item: len(item.path.parts), reverse=True):
        if not candidate.path.exists():
            results.append(MoveResult(candidate, None, "missing_before_move"))
            continue
        try:
            dest = destination_for(trash_root, candidate.path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidate.path), str(dest))
            if candidate.path.exists() or not dest.exists():
                results.append(MoveResult(candidate, dest, "verification_failed"))
            else:
                results.append(MoveResult(candidate, dest, "moved_to_trash"))
        except Exception as exc:
            results.append(MoveResult(candidate, None, "failed", repr(exc)))
    return results


def write_manifest(
    candidates: list[Candidate],
    results: list[MoveResult],
    report_dir: Path,
    timestamp: str,
    apply: bool,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest = report_dir / f"codex-cache-cleanup-{timestamp}.csv"
    by_path = {result.candidate.path: result for result in results}
    with manifest.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "action",
                "status",
                "category",
                "size_bytes",
                "path",
                "trash_path",
                "reason",
                "recommended_action",
                "risk",
                "error",
            ],
        )
        writer.writeheader()
        for candidate in candidates:
            result = by_path.get(candidate.path)
            writer.writerow(
                {
                    "action": "move_to_trash" if apply else "would_move_to_trash",
                    "status": result.status if result else "candidate",
                    "category": candidate.category,
                    "size_bytes": candidate.size_bytes,
                    "path": str(candidate.path),
                    "trash_path": str(result.trash_path) if result and result.trash_path else "",
                    "reason": candidate.reason,
                    "recommended_action": candidate.recommended_action,
                    "risk": candidate.risk,
                    "error": result.error if result else "",
                }
            )
    return manifest


def write_report(
    codex_home: Path,
    candidates: list[Candidate],
    results: list[MoveResult],
    manifest: Path,
    report_dir: Path,
    timestamp: str,
    apply: bool,
    trash_root: Path | None,
) -> Path:
    total = sum(candidate.size_bytes for candidate in candidates)
    moved = [result for result in results if result.status == "moved_to_trash"]
    failed = [result for result in results if result.status in {"failed", "verification_failed"}]
    missing = [result for result in results if result.status == "missing_before_move"]
    moved_total = sum(result.candidate.size_bytes for result in moved)

    by_category: dict[str, tuple[int, int]] = {}
    source = [result.candidate for result in moved] if apply else candidates
    for candidate in source:
        count, size = by_category.get(candidate.category, (0, 0))
        by_category[candidate.category] = (count + 1, size + candidate.size_bytes)

    report = report_dir / f"codex-cache-cleanup-{timestamp}.md"
    lines = [
        "# Codex Cache Cleanup Report",
        "",
        f"- Generated: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
        f"- Script version: `{SCRIPT_VERSION}`",
        f"- Mode: `{'apply' if apply else 'dry-run'}`",
        f"- Codex home: `{codex_home}`",
        f"- Manifest: `{manifest}`",
        f"- Candidate count: `{len(candidates)}`",
        f"- Candidate bytes: `{human_bytes(total)}`",
    ]
    if apply:
        lines.extend(
            [
                f"- Trash folder: `{trash_root}`",
                f"- Moved: `{len(moved)}` paths, `{human_bytes(moved_total)}`",
                f"- Failed: `{len(failed)}`",
                f"- Already missing: `{len(missing)}`",
            ]
        )
    lines.extend(["", "## By Category", ""])
    if by_category:
        for category, (count, size) in sorted(by_category.items(), key=lambda item: -item[1][1]):
            lines.append(f"- {category}: {count} path(s), {human_bytes(size)}")
    else:
        lines.append("- No candidates.")

    lines.extend(["", "## Largest Candidates", ""])
    for candidate in sorted(candidates, key=lambda item: item.size_bytes, reverse=True)[:30]:
        lines.append(f"- {human_bytes(candidate.size_bytes)} | {candidate.category} | `{candidate.path}`")
        lines.append(f"  - {candidate.reason}")

    if failed:
        lines.extend(["", "## Failures", ""])
        for result in failed:
            lines.append(f"- `{result.candidate.path}`: {result.status} {result.error}")

    if apply:
        lines.extend(
            [
                "",
                "## Restore",
                "",
                "Moved files are staged under the Trash folder above with original paths preserved under it. To restore an item, move its `trash_path` from the manifest back to `path`.",
            ]
        )
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and clean high-confidence Codex cache artifacts.")
    parser.add_argument("--apply", action="store_true", help="move candidates to Trash")
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME), help="Codex home directory")
    parser.add_argument("--report-dir", default=None, help="directory for reports and manifests")
    parser.add_argument("--trash-root", default=None, help="override Trash staging folder for apply mode")
    args = parser.parse_args()

    codex_home = Path(args.codex_home).expanduser()
    report_dir = Path(args.report_dir).expanduser() if args.report_dir else codex_home / "maintenance_reports"
    timestamp = now_stamp()
    trash_root = (
        Path(args.trash_root).expanduser()
        if args.trash_root
        else Path.home() / ".Trash" / f"Codex-high-confidence-cleanup-{timestamp}"
    )

    candidates = collect_candidates(codex_home)
    results = move_candidates(candidates, trash_root) if args.apply else []
    manifest = write_manifest(candidates, results, report_dir, timestamp, args.apply)
    report = write_report(codex_home, candidates, results, manifest, report_dir, timestamp, args.apply, trash_root)

    moved = [result for result in results if result.status == "moved_to_trash"]
    failed = [result for result in results if result.status in {"failed", "verification_failed"}]
    total = sum(candidate.size_bytes for candidate in candidates)
    moved_total = sum(result.candidate.size_bytes for result in moved)

    print(f"mode={'apply' if args.apply else 'dry-run'}")
    print(f"candidates={len(candidates)}")
    print(f"bytes={total}")
    if args.apply:
        print(f"moved={len(moved)}")
        print(f"moved_bytes={moved_total}")
        print(f"failed={len(failed)}")
        print(f"trash={trash_root}")
    print(f"manifest={manifest}")
    print(f"Report written to {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
