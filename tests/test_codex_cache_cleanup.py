import csv
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Sources/CodexPowertoyz/Resources/codex_cache_cleanup.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_cache_cleanup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["codex_cache_cleanup"] = module
    spec.loader.exec_module(module)
    return module


def touch_file(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class CodexCacheCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.codex_home = self.root / ".codex"
        self.codex_home.mkdir()
        self._create_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def _set_mtime(self, path: Path, offset: int) -> None:
        ts = time.time() + offset
        os.utime(path, (ts, ts))

    def _create_fixture(self):
        old_backup = self.codex_home / "maintenance_backups" / "20260501T000000Z"
        new_backup = self.codex_home / "maintenance_backups" / "20260502T000000Z"
        old_prune = self.codex_home / "maintenance_backups" / "archived-chat-prune" / "20260501T000000Z"
        new_prune = self.codex_home / "maintenance_backups" / "archived-chat-prune" / "20260502T000000Z"
        old_logs = self.codex_home / "maintenance_archives" / "logs" / "20260501T000000Z"
        new_logs = self.codex_home / "maintenance_archives" / "logs" / "20260502T000000Z"
        for index, path in enumerate([old_backup, new_backup, old_prune, new_prune, old_logs, new_logs]):
            touch_file(path / "payload.txt", f"payload-{index}")
            self._set_mtime(path, index)

        touch_file(self.codex_home / ".tmp" / "plugins" / "cache.txt", "cache")
        touch_file(self.codex_home / ".tmp" / "plugins.sha", "sha")

        touch_file(self.codex_home / "generated_images" / "known-thread" / "image.png", "known")
        touch_file(self.codex_home / "generated_images" / "orphan-thread" / "image.png", "orphan")

        con = sqlite3.connect(self.codex_home / "state_5.sqlite")
        con.execute("create table threads (id text primary key)")
        con.execute("insert into threads (id) values (?)", ("known-thread",))
        con.commit()
        con.close()

    def test_collects_only_high_confidence_candidates(self):
        module = load_module()
        candidates = module.collect_candidates(self.codex_home)
        categories = [candidate.category for candidate in candidates]
        paths = {candidate.path for candidate in candidates}

        self.assertEqual(categories.count("old_maintenance_backup"), 1)
        self.assertEqual(categories.count("old_archived_chat_prune_backup"), 1)
        self.assertEqual(categories.count("old_rotated_log_archive"), 1)
        self.assertEqual(categories.count("rebuildable_codex_tmp"), 2)
        self.assertEqual(categories.count("orphan_generated_images"), 1)
        self.assertIn(self.codex_home / "generated_images" / "orphan-thread", paths)
        self.assertNotIn(self.codex_home / "generated_images" / "known-thread", paths)
        self.assertNotIn(self.codex_home / "maintenance_backups" / "20260502T000000Z", paths)
        self.assertNotIn(
            self.codex_home / "maintenance_backups" / "archived-chat-prune" / "20260502T000000Z",
            paths,
        )
        self.assertNotIn(self.codex_home / "maintenance_archives" / "logs" / "20260502T000000Z", paths)

    def test_apply_moves_candidates_to_trash_and_reports_results(self):
        module = load_module()
        report_dir = self.root / "reports"
        trash_root = self.root / "Trash" / "Codex-high-confidence-cleanup-test"
        candidates = module.collect_candidates(self.codex_home)

        results = module.move_candidates(candidates, trash_root)
        manifest = module.write_manifest(candidates, results, report_dir, "test", apply=True)
        report = module.write_report(
            self.codex_home,
            candidates,
            results,
            manifest,
            report_dir,
            "test",
            apply=True,
            trash_root=trash_root,
        )

        self.assertEqual([result.status for result in results], ["moved_to_trash"] * len(candidates))
        for result in results:
            self.assertFalse(result.candidate.path.exists())
            self.assertIsNotNone(result.trash_path)
            self.assertTrue(result.trash_path.exists())
            self.assertTrue(trash_root in result.trash_path.parents)

        with manifest.open() as manifest_file:
            rows = list(csv.DictReader(manifest_file))
        self.assertEqual(len(rows), len(candidates))
        self.assertTrue(all(row["action"] == "move_to_trash" for row in rows))
        self.assertTrue(all(row["status"] == "moved_to_trash" for row in rows))
        self.assertIn("Moved: `6` paths", report.read_text())


if __name__ == "__main__":
    unittest.main()
