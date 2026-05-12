#!/usr/bin/env python3
"""Conservative cleanup for Codex workspace-local generated artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("~/Documents/Codex").expanduser()
CODEX_HOME = Path("~/.codex").expanduser()
REPORT_ROOT = CODEX_HOME / "maintenance_reports"
EXCLUDED_WORKSPACES: set[Path] = set()
INCLUDE_DERIVED_PAGE_RENDERS = False

REGENERABLE_DIR_NAMES = {
    ".build",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
SYSTEM_FILE_NAMES = {".DS_Store", "Thumbs.db"}
TEMP_SUFFIXES = {".tmp", ".bak", ".orig"}
VERSION_RE = re.compile(r"(?i)([-_ ]?v\d+|\s+\(\d+\)|[-_ ]copy)$")


@dataclass(frozen=True)
class Candidate:
    path: Path
    kind: str
    reason: str
    keep_path: Path | None = None
    size: int = 0
    sha256: str = ""


def is_excluded(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path
    return any(resolved == ex or ex in resolved.parents for ex in EXCLUDED_WORKSPACES)


def is_inside_ignored_tree(path: Path) -> bool:
    ignored_names = {".git", "node_modules"}
    return any(part in ignored_names for part in path.parts)


def sqlite_uri(path: Path, mode: str = "ro") -> str:
    return f"file:{path}?mode={mode}"


def thread_workspace_exclusions(codex_home: Path, keep_threads: set[str], exclude_active: bool) -> set[Path]:
    state_db = codex_home / "state_5.sqlite"
    if not state_db.exists():
        return set()

    clauses = []
    params: list[str] = []
    if exclude_active:
        clauses.append("archived = 0")
    if keep_threads:
        clauses.append(f"id in ({','.join('?' for _ in keep_threads)})")
        params.extend(sorted(keep_threads))
    if not clauses:
        return set()

    try:
        con = sqlite3.connect(sqlite_uri(state_db), uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"select cwd, rollout_path from threads where {' or '.join(clauses)}", params
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return set()

    exclusions: set[Path] = set()
    for row in rows:
        for value in (row["cwd"], row["rollout_path"]):
            if not value:
                continue
            path = Path(value).expanduser()
            if path.is_file():
                path = path.parent
            try:
                path = path.resolve()
            except FileNotFoundError:
                pass
            if path == ROOT or ROOT in path.parents:
                exclusions.add(path)
    return exclusions


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def tree_size(path: Path) -> int:
    total = 0
    if path.is_file() or path.is_symlink():
        return file_size(path)
    for root, dirnames, filenames in os.walk(path):
        dir_path = Path(root)
        if is_excluded(dir_path):
            dirnames[:] = []
            continue
        for name in filenames:
            child = dir_path / name
            total += file_size(child)
    return total


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_key(path: Path) -> tuple[int, float, str]:
    stem = path.stem
    match = re.search(r"(?i)(?:^|[-_ ]+)v(\d+)(?:$|[-_ ])", stem)
    version = int(match.group(1)) if match else 0
    return (version, path.stat().st_mtime, path.name)


def normalized_version_name(path: Path) -> str:
    stem = path.stem
    prev = None
    while prev != stem:
        prev = stem
        stem = VERSION_RE.sub("", stem)
    return f"{stem}{path.suffix}".lower()


def collect_regenerable_dirs() -> list[Candidate]:
    candidates: list[Candidate] = []
    for root, dirnames, _filenames in os.walk(ROOT):
        root_path = Path(root)
        if is_excluded(root_path):
            dirnames[:] = []
            continue
        if is_inside_ignored_tree(root_path):
            dirnames[:] = []
            continue

        remove_names = [name for name in dirnames if name in REGENERABLE_DIR_NAMES]
        for name in remove_names:
            path = root_path / name
            reason = "regenerable build/dependency/cache directory"
            candidates.append(Candidate(path, "regenerable_dir", reason, size=tree_size(path)))
            dirnames.remove(name)
    return candidates


def collect_system_files() -> list[Candidate]:
    candidates: list[Candidate] = []
    for root, dirnames, filenames in os.walk(ROOT):
        root_path = Path(root)
        if is_excluded(root_path):
            dirnames[:] = []
            continue
        if is_inside_ignored_tree(root_path):
            dirnames[:] = []
            continue
        for filename in filenames:
            path = root_path / filename
            if filename in SYSTEM_FILE_NAMES or path.suffix in TEMP_SUFFIXES:
                candidates.append(
                    Candidate(path, "system_or_temp_file", "system/temp artifact", size=file_size(path))
                )
    return candidates


def collect_derived_page_dirs() -> list[Candidate]:
    if not INCLUDE_DERIVED_PAGE_RENDERS:
        return []
    candidates: list[Candidate] = []
    for parent in ROOT.rglob("*"):
        if is_excluded(parent) or not parent.is_dir():
            continue
        final_docs = [
            path
            for path in parent.iterdir()
            if path.is_file() and path.suffix.lower() in {".pdf", ".pptx"}
        ]
        if not final_docs:
            continue
        keep = max(final_docs, key=lambda path: path.stat().st_mtime)
        for name in ("pages_png", "pages_cmyk_jpeg", "pages_jpeg", "page_renders", "rendered_pages"):
            path = parent / name
            if path.exists():
                candidates.append(
                    Candidate(
                        path,
                        "derived_page_render_dir",
                        "derived per-page renders superseded by final PDF/PPTX",
                        keep_path=keep,
                        size=tree_size(path),
                    )
                )
    return candidates


def collect_exact_version_duplicates() -> list[Candidate]:
    candidates: list[Candidate] = []
    for root, dirnames, filenames in os.walk(ROOT):
        root_path = Path(root)
        if is_excluded(root_path):
            dirnames[:] = []
            continue
        if is_inside_ignored_tree(root_path):
            dirnames[:] = []
            continue
        if any(part in REGENERABLE_DIR_NAMES for part in root_path.parts):
            dirnames[:] = []
            continue

        groups: dict[str, list[Path]] = {}
        has_version_marker: dict[str, bool] = {}
        for filename in filenames:
            path = root_path / filename
            if path.name in SYSTEM_FILE_NAMES or path.suffix in TEMP_SUFFIXES:
                continue
            normalized = normalized_version_name(path)
            groups.setdefault(normalized, []).append(path)
            has_version_marker[normalized] = has_version_marker.get(normalized, False) or (
                normalized != path.name.lower()
            )

        for normalized, paths in groups.items():
            if len(paths) < 2:
                continue
            if not has_version_marker.get(normalized, False):
                continue
            hashes: dict[str, list[Path]] = {}
            for path in paths:
                try:
                    digest = sha256(path)
                except OSError:
                    continue
                hashes.setdefault(digest, []).append(path)
            for digest, same_files in hashes.items():
                if len(same_files) < 2:
                    continue
                keep = max(same_files, key=latest_key)
                for path in same_files:
                    if path == keep:
                        continue
                    candidates.append(
                        Candidate(
                            path,
                            "exact_version_duplicate",
                            "exact duplicate of newer versioned file",
                            keep_path=keep,
                            size=file_size(path),
                            sha256=digest,
                        )
                    )
    return candidates


def collect_candidates() -> list[Candidate]:
    candidates = []
    candidates.extend(collect_regenerable_dirs())
    candidates.extend(collect_system_files())
    candidates.extend(collect_derived_page_dirs())
    candidates.extend(collect_exact_version_duplicates())

    seen: set[Path] = set()
    unique: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda c: str(c.path)):
        if candidate.path in seen:
            continue
        if is_excluded(candidate.path):
            continue
        seen.add(candidate.path)
        unique.append(candidate)
    return unique


def write_manifest(candidates: list[Candidate], timestamp: str, apply: bool) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = REPORT_ROOT / f"codex-artifact-cleanup-{timestamp}.csv"
    with manifest.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "action",
                "kind",
                "size_bytes",
                "path",
                "keep_path",
                "sha256",
                "reason",
            ],
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "action": "removed" if apply else "would_remove",
                    "kind": candidate.kind,
                    "size_bytes": candidate.size,
                    "path": str(candidate.path),
                    "keep_path": str(candidate.keep_path) if candidate.keep_path else "",
                    "sha256": candidate.sha256,
                    "reason": candidate.reason,
                }
            )
    return manifest


def write_summary(candidates: list[Candidate], manifest: Path, timestamp: str, apply: bool) -> Path:
    total = sum(candidate.size for candidate in candidates)
    by_kind: dict[str, tuple[int, int]] = {}
    for candidate in candidates:
        count, size = by_kind.get(candidate.kind, (0, 0))
        by_kind[candidate.kind] = (count + 1, size + candidate.size)

    summary = REPORT_ROOT / f"codex-artifact-cleanup-{timestamp}.md"
    lines = [
        "# Codex Artifact Cleanup Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- Mode: {'apply' if apply else 'dry-run'}",
        f"- Root: `{ROOT}`",
        f"- Excluded workspaces: {len(EXCLUDED_WORKSPACES)}",
        f"- Manifest: `{manifest}`",
        f"- Candidate count: {len(candidates)}",
        f"- Candidate bytes: {total}",
        "",
        "## By Kind",
        "",
    ]
    for kind, (count, size) in sorted(by_kind.items()):
        lines.append(f"- {kind}: {count} item(s), {size} bytes")
    lines.extend(["", "## Largest Items", ""])
    for candidate in sorted(candidates, key=lambda c: c.size, reverse=True)[:25]:
        lines.append(f"- {candidate.size} bytes | {candidate.kind} | `{candidate.path}`")
    summary.write_text("\n".join(lines) + "\n")
    return summary


def remove_candidates(candidates: list[Candidate]) -> None:
    for candidate in sorted(candidates, key=lambda c: len(c.path.parts), reverse=True):
        if candidate.path.is_dir() and not candidate.path.is_symlink():
            shutil.rmtree(candidate.path)
        else:
            try:
                candidate.path.unlink()
            except FileNotFoundError:
                pass


def main() -> int:
    global ROOT, CODEX_HOME, REPORT_ROOT, EXCLUDED_WORKSPACES, INCLUDE_DERIVED_PAGE_RENDERS

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="remove selected artifacts")
    parser.add_argument("--workspace-root", default=str(ROOT), help="Codex workspace root")
    parser.add_argument("--codex-home", default=str(CODEX_HOME), help="Codex home directory")
    parser.add_argument("--report-dir", default=None, help="directory for reports and manifests")
    parser.add_argument("--keep-workspace", action="append", default=[], help="workspace path to exclude")
    parser.add_argument("--keep-thread", action="append", default=[], help="thread id whose workspace should be excluded")
    parser.add_argument(
        "--include-active-workspaces",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="exclude active thread workspaces from cleanup",
    )
    parser.add_argument(
        "--include-derived-page-renders",
        action="store_true",
        help="remove generated page-render directories when a final PDF/PPTX exists in the same folder",
    )
    args = parser.parse_args()

    ROOT = Path(args.workspace_root).expanduser()
    CODEX_HOME = Path(args.codex_home).expanduser()
    REPORT_ROOT = Path(args.report_dir).expanduser() if args.report_dir else CODEX_HOME / "maintenance_reports"
    INCLUDE_DERIVED_PAGE_RENDERS = args.include_derived_page_renders

    explicit_keeps = {Path(path).expanduser() for path in args.keep_workspace}
    thread_keeps = thread_workspace_exclusions(CODEX_HOME, set(args.keep_thread), args.include_active_workspaces)
    EXCLUDED_WORKSPACES = explicit_keeps | thread_keeps

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidates = collect_candidates()
    manifest = write_manifest(candidates, timestamp, args.apply)
    summary = write_summary(candidates, manifest, timestamp, args.apply)
    if args.apply:
        remove_candidates(candidates)

    total = sum(candidate.size for candidate in candidates)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    print(f"candidates={len(candidates)}")
    print(f"bytes={total}")
    print(f"manifest={manifest}")
    print(f"summary={summary}")
    print(f"Report written to {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
