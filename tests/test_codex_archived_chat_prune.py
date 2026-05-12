import importlib.util
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Sources/CodexPowertoyz/Resources/codex_archived_chat_prune.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_archived_chat_prune", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["codex_archived_chat_prune"] = module
    spec.loader.exec_module(module)
    return module


class ArchivedChatPruneTests(unittest.TestCase):
    def test_bare_app_server_process_is_killable(self):
        module = load_module()

        self.assertTrue(module.is_codex_process_command("codex app-server"))
        self.assertTrue(module.is_codex_process_command("/Applications/Codex.app/Contents/MacOS/Codex"))
        self.assertTrue(
            module.is_codex_process_command(
                "/Applications/Codex.app/Contents/Resources/codex app-server --analytics-default-enabled"
            )
        )
        self.assertFalse(
            module.is_codex_process_command(
                "/Users/example/Applications/codex-powertoyz.app/Contents/MacOS/codex-powertoyz"
            )
        )

    def test_apply_prunes_archived_thread_files_and_state(self):
        module = load_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / "codex"
            archived_dir = codex_home / "archived_sessions"
            archived_dir.mkdir(parents=True)
            transcript = archived_dir / "session-archived-thread.jsonl"
            transcript.write_text('{"event":"ok"}\n')

            state_db = codex_home / "state_5.sqlite"
            con = sqlite3.connect(state_db)
            con.executescript(
                """
                CREATE TABLE threads (
                    id TEXT PRIMARY KEY,
                    rollout_path TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    title TEXT NOT NULL,
                    sandbox_policy TEXT NOT NULL,
                    approval_mode TEXT NOT NULL,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    has_user_event INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    archived_at INTEGER
                );
                CREATE TABLE thread_spawn_edges (
                    parent_thread_id TEXT NOT NULL,
                    child_thread_id TEXT NOT NULL PRIMARY KEY,
                    status TEXT NOT NULL
                );
                CREATE TABLE agent_jobs (id TEXT PRIMARY KEY);
                CREATE TABLE agent_job_items (
                    job_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    row_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_thread_id TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (job_id, item_id),
                    FOREIGN KEY(job_id) REFERENCES agent_jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE thread_dynamic_tools (
                    thread_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    input_schema TEXT NOT NULL,
                    PRIMARY KEY(thread_id, position),
                    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
                );
                CREATE TABLE stage1_outputs (
                    thread_id TEXT PRIMARY KEY,
                    source_updated_at INTEGER NOT NULL,
                    raw_memory TEXT NOT NULL,
                    rollout_summary TEXT NOT NULL,
                    generated_at INTEGER NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
                );
                """
            )
            now = int(time.time())
            con.execute(
                """
                INSERT INTO threads
                (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode, archived, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "archived-thread",
                    str(transcript),
                    now,
                    now,
                    "desktop",
                    "openai",
                    "/tmp",
                    "Archived test",
                    "default",
                    "never",
                    1,
                    now,
                ),
            )
            con.execute(
                """
                INSERT INTO threads
                (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, sandbox_policy, approval_mode, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "active-thread",
                    str(archived_dir / "active.jsonl"),
                    now,
                    now,
                    "desktop",
                    "openai",
                    "/tmp",
                    "Active test",
                    "default",
                    "never",
                    0,
                ),
            )
            con.execute("INSERT INTO agent_jobs (id) VALUES (?)", ("job",))
            con.execute(
                """
                INSERT INTO agent_job_items
                (job_id, item_id, row_index, row_json, status, assigned_thread_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("job", "item", 0, "{}", "pending", "archived-thread", now, now),
            )
            con.commit()
            con.close()

            session_index = codex_home / "session_index.jsonl"
            session_index.write_text(
                json.dumps({"id": "archived-thread"}) + "\n" + json.dumps({"id": "active-thread"}) + "\n"
            )

            module.CODEX_HOME = codex_home
            module.ARCHIVED_DIR = archived_dir
            module.STATE_DB = state_db
            module.SESSION_INDEX = session_index
            module.BACKUP_ROOT = codex_home / "backups"
            module.REPORT_ROOT = codex_home / "reports"

            threads = module.archived_threads(set())
            files = module.archived_files_on_disk(set())
            backup = module.create_backup(threads, files, "test")
            db_result = module.prune_database({thread.id for thread in threads})
            session_index_removed = module.filter_session_index({thread.id for thread in threads}, backup)
            files_removed = module.remove_archived_files(files)

            con = sqlite3.connect(state_db)
            remaining_threads = con.execute("SELECT id, archived FROM threads ORDER BY id").fetchall()
            assigned_threads = con.execute("SELECT assigned_thread_id FROM agent_job_items").fetchall()
            foreign_key_rows = con.execute("PRAGMA foreign_key_check").fetchall()

            self.assertEqual(threads[0].id, "archived-thread")
            self.assertEqual(db_result["threads_deleted"], 1)
            self.assertEqual(session_index_removed, 1)
            self.assertEqual(files_removed, 1)
            self.assertEqual(remaining_threads, [("active-thread", 0)])
            self.assertEqual(assigned_threads, [(None,)])
            self.assertEqual(foreign_key_rows, [])
            self.assertFalse(transcript.exists())


if __name__ == "__main__":
    unittest.main()
