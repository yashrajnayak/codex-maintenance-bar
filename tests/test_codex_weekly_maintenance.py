import importlib.util
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "codex_weekly_maintenance.py"
SPEC = importlib.util.spec_from_file_location("codex_weekly_maintenance", SCRIPT)
maintenance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = maintenance
SPEC.loader.exec_module(maintenance)


def make_args(codex_home: Path, workspace_root: Path, **overrides):
    defaults = {
        "apply": False,
        "backup_only": False,
        "write_report": False,
        "report_dir": None,
        "codex_home": str(codex_home),
        "workspace_root": str(workspace_root),
        "archive_days": 10,
        "worktree_days": 14,
        "log_mb": 100,
        "quit_codex": False,
        "force_quit_codex": False,
        "codex_quit_timeout": 1,
        "restore_backup": None,
        "lock_path": None,
        "keep_thread": [],
        "keep_title_regex": [],
        "skip_session_archive": False,
        "skip_config_prune": False,
        "skip_workspaces": True,
        "skip_logs": True,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


class CodexMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.codex_home = self.root / ".codex"
        self.workspace_root = self.root / "CodexWorkspaces"
        self.codex_home.mkdir()
        self.workspace_root.mkdir()
        (self.codex_home / "sessions" / "2026" / "04" / "01").mkdir(parents=True)
        (self.codex_home / "sessions" / "2026" / "05" / "01").mkdir(parents=True)
        (self.codex_home / "archived_sessions").mkdir()
        (self.codex_home / "skills").mkdir()
        (self.codex_home / "plugins").mkdir()
        (self.codex_home / "memories").mkdir()
        self.good_project = self.workspace_root / "current"
        self.good_project.mkdir()
        self.missing_project = self.workspace_root / "missing"

        self.old_session = self.codex_home / "sessions/2026/04/01/rollout-old.jsonl"
        self.recent_session = self.codex_home / "sessions/2026/05/01/rollout-recent.jsonl"
        self.old_session.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Old important task"},
                }
            )
            + "\n"
        )
        self.recent_session.write_text(
            json.dumps(
                {
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Recent task"}],
                    }
                }
            )
            + "\n"
        )
        self._create_state_db(self.codex_home / "state_6.sqlite")
        self._create_logs_db(self.codex_home / "logs_3.sqlite")
        (self.codex_home / "config.toml").write_text(
            f'[projects."{self.good_project}"]\ntrust_level = "trusted"\n\n'
            f'[projects."{self.missing_project}"]\ntrust_level = "trusted"\n'
        )
        (self.codex_home / ".codex-global-state.json").write_text("{}")
        (self.codex_home / "session_index.jsonl").write_text("")

        self.original_process_lines = maintenance.codex_process_lines
        self.original_process_entries = maintenance.codex_process_entries
        self.original_background_processes = maintenance.background_process_lines
        maintenance.codex_process_lines = lambda: []
        maintenance.codex_process_entries = lambda: []
        maintenance.background_process_lines = lambda: []

    def tearDown(self):
        maintenance.codex_process_lines = self.original_process_lines
        maintenance.codex_process_entries = self.original_process_entries
        maintenance.background_process_lines = self.original_background_processes
        self.tmp.cleanup()

    def _create_state_db(self, path: Path):
        conn = sqlite3.connect(path)
        conn.execute(
            """
            create table threads (
                id text primary key,
                title text,
                rollout_path text,
                cwd text,
                archived integer default 0,
                archived_at integer,
                updated_at integer,
                updated_at_ms integer,
                tokens_used integer default 0
            )
            """
        )
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - 20 * 86400 * 1000
        conn.execute(
            "insert into threads values (?, ?, ?, ?, 0, null, ?, ?, ?)",
            ("old-thread", "Old thread", str(self.old_session), str(self.good_project), old_ms, old_ms, 100),
        )
        conn.execute(
            "insert into threads values (?, ?, ?, ?, 0, null, ?, ?, ?)",
            ("recent-thread", "Recent thread", str(self.recent_session), str(self.good_project), now_ms, now_ms, 10),
        )
        conn.commit()
        conn.close()

    def _create_logs_db(self, path: Path):
        conn = sqlite3.connect(path)
        conn.execute(
            """
            create table logs (
                id integer primary key,
                ts integer not null,
                ts_nanos integer not null default 0,
                level text not null,
                target text not null
            )
            """
        )
        conn.execute("insert into logs (ts, level, target) values (1, 'INFO', 'test')")
        conn.commit()
        conn.close()

    def test_audit_detects_schema_and_archive_candidate(self):
        args = make_args(self.codex_home, self.workspace_root)
        audit = maintenance.audit_state(args)

        self.assertEqual(audit.state_db.name, "state_6.sqlite")
        self.assertEqual(audit.logs_db.name, "logs_3.sqlite")
        self.assertEqual(audit.state_counts["active"], 2)
        self.assertEqual([thread.id for thread in audit.archive_candidates], ["old-thread"])

    def test_apply_archives_session_prunes_config_and_writes_manifest(self):
        args = make_args(self.codex_home, self.workspace_root)
        audit = maintenance.audit_state(args)
        actions = maintenance.apply_cleanup(args, audit)

        self.assertTrue(any("Backup written" in action for action in actions))
        self.assertFalse(self.old_session.exists())
        archived = list((self.codex_home / "archived_sessions").glob("rollout-old*.jsonl"))
        self.assertEqual(len(archived), 1)
        self.assertNotIn(str(self.missing_project), (self.codex_home / "config.toml").read_text())

        conn = sqlite3.connect(self.codex_home / "state_6.sqlite")
        archived_flag, rollout_path = conn.execute(
            "select archived, rollout_path from threads where id = 'old-thread'"
        ).fetchone()
        conn.close()
        self.assertEqual(archived_flag, 1)
        self.assertEqual(Path(rollout_path), archived[0])

        backups = list((self.codex_home / "maintenance_backups").iterdir())
        self.assertEqual(len(backups), 1)
        manifest = json.loads((backups[0] / "manifest.json").read_text())
        self.assertEqual(manifest["session_moves"][0]["id"], "old-thread")
        self.assertTrue(manifest["config_pruned"])

    def test_restore_backup_restores_previous_state(self):
        args = make_args(self.codex_home, self.workspace_root)
        audit = maintenance.audit_state(args)
        maintenance.apply_cleanup(args, audit)
        backup_root = next((self.codex_home / "maintenance_backups").iterdir())

        restore_args = make_args(self.codex_home, self.workspace_root, restore_backup=str(backup_root))
        maintenance.restore_backup(restore_args)

        self.assertTrue(self.old_session.exists())
        self.assertIn(str(self.missing_project), (self.codex_home / "config.toml").read_text())
        conn = sqlite3.connect(self.codex_home / "state_6.sqlite")
        archived_flag, rollout_path = conn.execute(
            "select archived, rollout_path from threads where id = 'old-thread'"
        ).fetchone()
        conn.close()
        self.assertEqual(archived_flag, 0)
        self.assertEqual(Path(rollout_path), self.old_session)

    def test_lock_rejects_active_pid(self):
        lock_path = self.codex_home / "maintenance.lock"
        lock_path.write_text(json.dumps({"pid": maintenance.os.getpid()}))
        with self.assertRaises(SystemExit):
            with maintenance.MaintenanceLock(lock_path):
                pass


if __name__ == "__main__":
    unittest.main()
