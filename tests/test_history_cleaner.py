import contextlib
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clear_opencode_history as cleaner


FIXTURE = ROOT / "tests" / "opencode.db"
HISTORY_TABLES = (
    "part",
    "message",
    "session_message",
    "session_input",
    "session_share",
    "session_context_epoch",
    "todo",
    "session",
    "event",
    "event_sequence",
)
PRESERVED_TABLES = (
    "workspace",
    "project_directory",
    "permission",
    "account_state",
    "project",
    "account",
    "control_account",
    "credential",
    "migration",
    "data_migration",
)


def fixture_checksum():
    return hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def backup_fixture(destination):
    """Create a writable, isolated snapshot without touching the fixture."""
    source_uri = (
        "file:" + quote(str(FIXTURE.resolve())) + "?mode=ro&immutable=1"
    )
    source = sqlite3.connect(source_uri, uri=True)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def seed_database(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        INSERT INTO project
          (id, worktree, vcs, name, icon_url, icon_url_override, icon_color,
           time_created, time_updated, time_initialized, sandboxes, commands)
        VALUES
          ('project-under-test', '/tmp/project-under-test', 'git', 'Test Project',
           NULL, NULL, NULL, 1, 1, NULL, '{}', '{}');
        INSERT INTO workspace
          (id, type, name, branch, directory, extra, project_id, time_used)
        VALUES
          ('workspace-under-test', 'directory', 'Test Workspace', 'main',
           '/tmp/project-under-test', '{}', 'project-under-test', 1);
        INSERT INTO project_directory
          (project_id, directory, type, strategy, time_created)
        VALUES ('project-under-test', '/tmp/project-under-test', 'root', 'none', 1);
        INSERT INTO permission
          (id, project_id, action, resource, time_created, time_updated)
        VALUES ('permission-under-test', 'project-under-test', 'read', '*', 1, 1);
        INSERT INTO account
          (id, email, url, access_token, refresh_token, token_expiry,
           time_created, time_updated)
        VALUES ('account-under-test', 'test@example.com', 'https://example.com',
                'access-token', 'refresh-token', NULL, 1, 1);
        INSERT INTO account_state (id, active_account_id, active_org_id)
        VALUES (1, 'account-under-test', NULL);
        INSERT INTO control_account
          (email, url, access_token, refresh_token, token_expiry, active,
           time_created, time_updated)
        VALUES ('control@example.com', 'https://example.com', 'control-access',
                'control-refresh', NULL, 1, 1, 1);
        INSERT INTO credential
          (id, integration_id, label, value, connector_id, method_id, active,
           time_created, time_updated)
        VALUES ('credential-under-test', NULL, 'test credential', 'secret',
                NULL, NULL, 1, 1, 1);
        INSERT INTO migration (id, time_completed)
        VALUES ('test-migration', 1);
        INSERT INTO data_migration (name, time_completed)
        VALUES ('test-data-migration', 1);
        INSERT INTO session
          (id, project_id, workspace_id, parent_id, slug, directory, path,
           title, version, share_url, summary_additions, summary_deletions,
           summary_files, summary_diffs, metadata, cost, tokens_input,
           tokens_output, tokens_reasoning, tokens_cache_read,
           tokens_cache_write, revert, permission, agent, model, time_created,
           time_updated, time_compacting, time_archived)
        VALUES
          ('session-under-test', 'project-under-test', 'workspace-under-test',
           NULL, 'test-session', '/tmp/project-under-test', NULL,
           'Test Session', '1', NULL, 1, 2, 1, 'diff', 'metadata', 0, 3, 4,
           5, 6, 7, NULL, NULL, 'agent', 'model', 1, 1, NULL, NULL);
        INSERT INTO message
          (id, session_id, time_created, time_updated, data)
        VALUES ('message-under-test', 'session-under-test', 1, 1, 'message data');
        INSERT INTO part
          (id, message_id, session_id, time_created, time_updated, data)
        VALUES ('part-under-test', 'message-under-test', 'session-under-test',
                1, 1, 'part data');
        INSERT INTO session_message
          (id, session_id, type, seq, time_created, time_updated, data)
        VALUES ('session-message-under-test', 'session-under-test', 'user', 1,
                1, 1, 'session message data');
        INSERT INTO session_input
          (id, session_id, prompt, delivery, admitted_seq, promoted_seq,
           time_created)
        VALUES ('session-input-under-test', 'session-under-test', 'prompt',
                'direct', 1, NULL, 1);
        INSERT INTO session_share
          (session_id, id, secret, url, time_created, time_updated)
        VALUES ('session-under-test', 'share-under-test', 'secret',
                'https://example.com/share', 1, 1);
        INSERT INTO session_context_epoch
          (session_id, baseline, snapshot, baseline_seq)
        VALUES ('session-under-test', 'baseline', 'snapshot', 1);
        INSERT INTO todo
          (session_id, content, status, priority, position, time_created,
           time_updated)
        VALUES ('session-under-test', 'todo item', 'pending', 'high', 0, 1, 1);
        INSERT INTO event_sequence (aggregate_id, seq, owner_id)
        VALUES ('aggregate-under-test', 1, 'owner-under-test');
        INSERT INTO event
          (id, aggregate_id, seq, type, data)
        VALUES ('event-under-test', 'aggregate-under-test', 1, 'test', '{}');
        """
    )
    conn.commit()
    conn.close()


class IsolatedDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_digest = fixture_checksum()

    @classmethod
    def tearDownClass(cls):
        if cls.fixture_digest != fixture_checksum():
            raise AssertionError("tests/opencode.db was modified by the test suite")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "opencode.db")
        backup_fixture(self.db_path)
        seed_database(self.db_path)
        self.assertNotIn(os.path.realpath(self.db_path), {
            os.path.realpath(str(FIXTURE)),
            os.path.realpath(cleaner.get_paths()[1]),
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def counts(self, tables):
        conn = sqlite3.connect(self.db_path)
        try:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]
                for table in tables
            }
        finally:
            conn.close()

    def test_database_cleanup_removes_history_and_preserves_other_tables(self):
        before = self.counts(PRESERVED_TABLES)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cleaner.clean_database(self.db_path)

        text = output.getvalue()
        self.assertIn(f"Opening database at {self.db_path}", text)
        self.assertIn("Database cleaned and optimized", text)
        self.assertEqual(
            {table: 0 for table in HISTORY_TABLES}, self.counts(HISTORY_TABLES)
        )
        self.assertEqual(before, self.counts(PRESERVED_TABLES))

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
            self.assertTrue(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' "
                    "AND name='session_project_idx'"
                ).fetchone()
            )
        finally:
            conn.close()

    def test_database_cleanup_handles_missing_database_and_tables(self):
        missing = os.path.join(self.temp_dir.name, "missing.db")
        cleaner.clean_database(missing)
        self.assertFalse(os.path.exists(missing))

        sparse = os.path.join(self.temp_dir.name, "sparse.db")
        sqlite3.connect(sparse).close()
        cleaner.clean_database(sparse)
        self.assertTrue(os.path.exists(sparse))

    def test_database_cleanup_retains_recent_sessions_and_cascades_old_history(self):
        now = 2_000_000
        retention_ms = 24 * 60 * 60 * 1000
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO session "
            "(id, project_id, slug, directory, title, version, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("recent-session", "project-under-test", "recent", "/tmp/project-under-test",
             "Recent", "1", now * 1000 - retention_ms // 2, now * 1000 - retention_ms // 2),
        )
        conn.execute(
            "INSERT INTO session "
            "(id, project_id, slug, directory, title, version, parent_id, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("recent-child", "project-under-test", "child", "/tmp/project-under-test",
             "Child", "1", "old-parent", 1, now * 1000 - retention_ms // 2),
        )
        conn.execute(
            "INSERT INTO session "
            "(id, project_id, slug, directory, title, version, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("old-parent", "project-under-test", "parent", "/tmp/project-under-test",
             "Parent", "1", 1, 1),
        )
        conn.execute(
            "INSERT INTO session_message "
            "(id, session_id, type, seq, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("recent-message", "recent-session", "user", 1, 1, 1, "recent data"),
        )
        conn.commit()
        conn.close()

        with mock.patch.object(cleaner.time, "time", return_value=now):
            cleaner.clean_database(self.db_path, "1d")

        conn = sqlite3.connect(self.db_path)
        try:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM session WHERE id='session-under-test'"
                ).fetchone()
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT 1 FROM session WHERE id='recent-session'"
                ).fetchone()
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT 1 FROM session WHERE id='old-parent'"
                ).fetchone()
            )
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM session_message WHERE id='session-message-under-test'"
                ).fetchone()
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT 1 FROM session_message WHERE id='recent-message'"
                ).fetchone()
            )
        finally:
            conn.close()

    def test_retention_parser_accepts_days_weeks_months_and_rejects_invalid(self):
        self.assertEqual(cleaner.parse_retention("30d"), 30 * 24 * 60 * 60 * 1000)
        self.assertEqual(cleaner.parse_retention("4W"), 4 * 7 * 24 * 60 * 60 * 1000)
        self.assertEqual(cleaner.parse_retention("5m"), 5 * 30 * 24 * 60 * 60 * 1000)
        for value in ("0d", "-1d", "30", "30x", "1.5d", ""):
            with self.assertRaises(ValueError):
                cleaner.parse_retention(value)

    def test_cli_retention_is_available_for_clean_and_database_only(self):
        args = cleaner.build_parser().parse_args(["clean", "--retain", "30d"])
        self.assertEqual(args.retain, "30d")
        args = cleaner.build_parser().parse_args(["database", "--retain", "4w"])
        self.assertEqual(args.retain, "4w")
        with self.assertRaises(SystemExit):
            cleaner.build_parser().parse_args(["stats", "--retain", "30d"])

    def test_show_stats_is_read_only_and_reports_projects(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO project "
            "(id, worktree, name, time_created, time_updated, sandboxes) "
            "VALUES (?, ?, ?, 1, 1, '{}')",
            ("project-two", "/tmp/project-two", "Second Project"),
        )
        conn.execute(
            "INSERT INTO session "
            "(id, project_id, slug, directory, title, version, time_created, "
            "time_updated) VALUES (?, ?, ?, ?, ?, ?, 1, 1)",
            ("session-two", "project-two", "second", "/tmp/project-two", "Second", "1"),
        )
        conn.commit()
        conn.close()
        before = fixture_checksum_for(self.db_path)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cleaner.show_stats(self.db_path)

        text = output.getvalue()
        self.assertIn("Test Project", text)
        self.assertIn("Second Project", text)
        self.assertIn("TOTAL", text)
        self.assertIn("2", text)
        self.assertRegex(text, r"\d+\.\d+ (?:B|KB|MB|GB|TB)")
        self.assertEqual(before, fixture_checksum_for(self.db_path))

    def test_show_stats_handles_missing_and_incompatible_databases(self):
        missing = os.path.join(self.temp_dir.name, "missing-stats.db")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cleaner.show_stats(missing)
        self.assertIn("Database not found", output.getvalue())
        self.assertFalse(os.path.exists(missing))

        empty = os.path.join(self.temp_dir.name, "empty.db")
        sqlite3.connect(empty).close()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cleaner.show_stats(empty)
        self.assertIn("does not contain a session table", output.getvalue())

    def test_cli_database_path_is_explicit_and_safe(self):
        live_path = os.path.join(self.temp_dir.name, "live-must-not-change.db")
        with mock.patch.object(
            cleaner, "get_paths", return_value=(self.temp_dir.name, live_path)
        ):
            result = cleaner.main(
                ["database", "--db-path", self.db_path, "--yes", "--no-pause"]
            )
        self.assertEqual(0, result)
        self.assertFalse(os.path.exists(live_path))
        self.assertEqual(
            {table: 0 for table in HISTORY_TABLES}, self.counts(HISTORY_TABLES)
        )

        with self.assertRaises(SystemExit):
            cleaner.build_parser().parse_args(["clean", "--db-path", self.db_path])

    def test_confirmation_denial_does_not_clean(self):
        before = self.counts(HISTORY_TABLES)
        with mock.patch("builtins.input", return_value="no"):
            result = cleaner.main(["database", "--db-path", self.db_path])
        self.assertEqual(0, result)
        self.assertEqual(before, self.counts(HISTORY_TABLES))

    def test_main_routes_help_stats_and_denial_safely(self):
        help_output = io.StringIO()
        with contextlib.redirect_stdout(help_output):
            result = cleaner.main([])
        self.assertEqual(0, result)
        self.assertIn("database", help_output.getvalue())

        stats_output = io.StringIO()
        with contextlib.redirect_stdout(stats_output):
            result = cleaner.main(["stats", "--db-path", self.db_path])
        self.assertEqual(0, result)
        self.assertIn("Test Project", stats_output.getvalue())

        with mock.patch("builtins.input", return_value="no"), mock.patch.object(
            cleaner, "clean_json_caches"
        ) as clean_caches:
            result = cleaner.main(["caches"])
        self.assertEqual(0, result)
        clean_caches.assert_not_called()


def fixture_checksum_for(path):
    digest = hashlib.sha256()
    with open(path, "rb") as database:
        for chunk in iter(lambda: database.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
