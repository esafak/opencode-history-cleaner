#!/usr/bin/env python3
import os
import sys
import glob
import json
import sqlite3
import time
import subprocess
import platform
import argparse
import re
from urllib.parse import quote

RETENTION_UNITS = {
    "d": 24 * 60 * 60 * 1000,
    "w": 7 * 24 * 60 * 60 * 1000,
    "m": 30 * 24 * 60 * 60 * 1000,
}

def print_banner():
    print("=" * 60)
    print("      OpenCode Chat History Cleaner & Database Optimizer      ")
    print("=" * 60)

def quit_opencode():
    print("[*] Closing OpenCode application gracefully...")
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["osascript", "-e", 'quit app "OpenCode"'], capture_output=True, text=True)
        elif system == "Windows":
            subprocess.run(["taskkill", "/IM", "OpenCode.exe", "/F"], capture_output=True, text=True)
        elif system == "Linux":
            subprocess.run(["pkill", "-f", "opencode"], capture_output=True, text=True)
        
        time.sleep(3)
        print("[+] Application quit command sent.")
    except Exception as e:
        print(f"[-] Error closing OpenCode: {e}")

def get_paths():
    system = platform.system()
    if system == "Darwin":
        app_support = os.path.expanduser("~/Library/Application Support/ai.opencode.desktop")
        db_path = os.path.expanduser("~/.local/share/opencode/opencode.db")
    elif system == "Windows":
        app_support = os.path.expandvars(r"%APPDATA%\ai.opencode.desktop")
        db_path1 = os.path.expandvars(r"%LOCALAPPDATA%\opencode\opencode.db")
        db_path2 = os.path.expanduser(r"~/.local/share/opencode/opencode.db")
        db_path = db_path1 if os.path.exists(db_path1) else db_path2
    else: # Linux
        app_support = os.path.expanduser("~/.config/ai.opencode.desktop")
        db_path = os.path.expanduser("~/.local/share/opencode/opencode.db")
        
    return app_support, db_path

def parse_retention(value):
    """Return a retention duration in milliseconds, or raise ValueError."""
    match = re.fullmatch(r"([1-9][0-9]*)([dwm])", value.strip().lower())
    if not match:
        raise ValueError("retention must be a positive duration such as 30d, 4w, or 5m")
    amount, unit = match.groups()
    return int(amount) * RETENTION_UNITS[unit]


def retention_cutoff(value, now=None):
    """Return the oldest session timestamp to retain (OpenCode uses ms)."""
    return int((time.time() if now is None else now) * 1000) - parse_retention(value)


def clean_database(db_path, retain=None):
    if not os.path.exists(db_path):
        print(f"[-] Database not found at {db_path}")
        return
        
    print(f"[*] Opening database at {db_path}...")
    conn = None
    try:
        initial_size = os.path.getsize(db_path)
        print(f"[*] Before cleanup: {format_bytes(initial_size)}")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        if retain:
            cutoff = retention_cutoff(retain)
            if _table_exists(cursor, "session"):
                # Retain a complete session family: recent sessions, their
                # ancestors, and all descendants of every retained session.
                cursor.execute(
                    """CREATE TEMP TABLE retained_sessions AS
                       WITH RECURSIVE
                       ancestors(id) AS (
                           SELECT id FROM session WHERE time_updated >= ?
                           UNION
                           SELECT s.parent_id
                           FROM session s
                           JOIN ancestors a ON s.id = a.id
                           WHERE s.parent_id IS NOT NULL
                       ),
                       family(id) AS (
                           SELECT id FROM ancestors
                           UNION
                           SELECT s.id
                           FROM session s
                           JOIN family f ON s.parent_id = f.id
                       )
                       SELECT id FROM family""",
                    (cutoff,),
                )
                cursor.execute(
                    """CREATE TEMP TABLE bygone_sessions AS
                       SELECT id FROM session
                       WHERE time_updated < ?
                         AND id NOT IN (SELECT id FROM retained_sessions)""",
                    (cutoff,),
                )
                removed_sessions = cursor.execute(
                    "SELECT COUNT(*) FROM bygone_sessions"
                ).fetchone()[0]
                retained_sessions = cursor.execute(
                    "SELECT COUNT(*) FROM retained_sessions"
                ).fetchone()[0]

                removed_aggregates = 0
                removed_events = 0
                if _table_exists(cursor, "event_sequence"):
                    removed_aggregates = cursor.execute(
                        """SELECT COUNT(*) FROM event_sequence
                           WHERE aggregate_id IN (SELECT id FROM bygone_sessions)"""
                    ).fetchone()[0]
                    has_event_table = _table_exists(cursor, "event")
                    cascades_events = has_event_table and _event_sequence_cascades(cursor)
                    if has_event_table:
                        removed_events = cursor.execute(
                            """SELECT COUNT(*) FROM event
                               WHERE aggregate_id IN (SELECT id FROM bygone_sessions)"""
                        ).fetchone()[0]
                    if has_event_table and not cascades_events:
                        # Compatible fallback for databases created without
                        # OpenCode's event -> event_sequence cascade.
                        cursor.execute(
                            """DELETE FROM event
                               WHERE aggregate_id IN (SELECT id FROM bygone_sessions)"""
                        )
                    cursor.execute(
                        """DELETE FROM event_sequence
                           WHERE aggregate_id IN (SELECT id FROM bygone_sessions)"""
                    )
                    if has_event_table and cascades_events:
                        remaining_events = cursor.execute(
                            """SELECT COUNT(*) FROM event
                               WHERE aggregate_id IN (SELECT id FROM bygone_sessions)"""
                        ).fetchone()[0]
                        if remaining_events:
                            raise sqlite3.IntegrityError(
                                "event cascade did not remove all expired events"
                            )
                    print(
                        f"[+] Removed {removed_aggregates} event aggregate(s) "
                        f"and {removed_events} event(s) for expired sessions."
                    )
                else:
                    if _table_exists(cursor, "event"):
                        print(
                            "[*] Event table has no event_sequence table; "
                            "event cleanup skipped."
                        )
                    else:
                        print("[*] Event tables not present; event cleanup skipped.")

                cursor.execute(
                    "DELETE FROM session WHERE id IN (SELECT id FROM bygone_sessions)"
                )
                print(
                    f"[+] Removed {removed_sessions} expired session(s); "
                    f"retained {retained_sessions} session(s)."
                )
                cursor.execute("DROP TABLE bygone_sessions")
                cursor.execute("DROP TABLE retained_sessions")
            else:
                print(
                    "[-] Database does not contain a session table; "
                    "retention cleanup skipped."
                )
            tables_to_clear = []
        else:
            tables_to_clear = [
                "event", "event_sequence", "part", "message", "session_message", "session_input",
                "session_share", "session_context_epoch", "todo", "session",
            ]
        
        for table in tables_to_clear:
            try:
                if _table_exists(cursor, table):
                    cursor.execute(f"DELETE FROM `{table}`;")
                    print(f"[+] Cleared table: {table}")
            except Exception as e:
                print(f"[-] Error clearing table {table}: {e}")
                
        conn.commit()
        
        print("[*] Optimizing and shrinking database (VACUUM)...")
        cursor.execute("VACUUM;")
        conn.close()
        
        final_size = os.path.getsize(db_path)
        print(f"[+] Database cleaned and optimized. After cleanup: {format_bytes(final_size)}")
        
    except Exception as e:
        if conn is not None:
            conn.close()
        print(f"[-] Database error: {e}")


def format_fraction(part, total):
    percentage = 0.0 if total == 0 else part * 100 / total
    return f"{part:,}/{total:,} ({percentage:.1f}%)"


def preview_database(db_path, retain=None, command="database"):
    """Report database rows that cleanup would remove without changing the DB."""
    if not os.path.exists(db_path):
        print(f"[-] Database not found at {db_path}")
        return

    print(f"[*] Previewing database cleanup for {db_path} (read-only)...")
    if command == "clean":
        print("[*] clean --dry-run previews database cleanup only; caches, logs, and outputs are not evaluated.")
    uri = "file:" + quote(os.path.abspath(db_path)) + "?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()
        if retain and _table_exists(cursor, "session"):
            cutoff = retention_cutoff(retain)
            cursor.execute(
                """WITH RECURSIVE
                   ancestors(id) AS (
                       SELECT id FROM session WHERE time_updated >= ?
                       UNION
                       SELECT s.parent_id
                       FROM session s
                       JOIN ancestors a ON s.id = a.id
                       WHERE s.parent_id IS NOT NULL
                   ),
                   family(id) AS (
                       SELECT id FROM ancestors
                       UNION
                       SELECT s.id
                       FROM session s
                       JOIN family f ON s.parent_id = f.id
                   )
                   SELECT COUNT(*) FROM session
                   WHERE time_updated < ?
                     AND id NOT IN (SELECT id FROM family)""",
                (cutoff, cutoff),
            )
            expired_sessions = cursor.fetchone()[0]
            cursor.execute(
                """WITH RECURSIVE
                   ancestors(id) AS (
                       SELECT id FROM session WHERE time_updated >= ?
                       UNION
                       SELECT s.parent_id
                       FROM session s
                       JOIN ancestors a ON s.id = a.id
                       WHERE s.parent_id IS NOT NULL
                   ),
                   family(id) AS (
                       SELECT id FROM ancestors
                       UNION
                       SELECT s.id
                       FROM session s
                       JOIN family f ON s.parent_id = f.id
                   )
                   SELECT COUNT(*) FROM family""",
                (cutoff,),
            )
            retained_sessions = cursor.fetchone()[0]
            total_sessions = cursor.execute("SELECT COUNT(*) FROM session").fetchone()[0]
            session_filter = """WITH RECURSIVE
                ancestors(id) AS (
                    SELECT id FROM session WHERE time_updated >= ?
                    UNION
                    SELECT s.parent_id FROM session s
                    JOIN ancestors a ON s.id = a.id
                    WHERE s.parent_id IS NOT NULL
                ),
                family(id) AS (
                    SELECT id FROM ancestors
                    UNION
                    SELECT s.id FROM session s
                    JOIN family f ON s.parent_id = f.id
                )
                SELECT id FROM session
                WHERE time_updated < ?
                  AND id NOT IN (SELECT id FROM family)"""
            params = (cutoff, cutoff)
            print(
                f"[+] Would retain {retained_sessions} session(s) and remove "
                f"{format_fraction(expired_sessions, total_sessions)} expired session(s)."
            )
            if _table_exists(cursor, "event_sequence"):
                total_aggregates = cursor.execute(
                    "SELECT COUNT(*) FROM event_sequence"
                ).fetchone()[0]
                cursor.execute(
                    f"""WITH expired(id) AS ({session_filter})
                        SELECT COUNT(*) FROM event_sequence
                        WHERE aggregate_id IN (SELECT id FROM expired)""",
                    params,
                )
                removed_aggregates = cursor.fetchone()[0]
                print(
                    "[+] Would remove "
                    f"{format_fraction(removed_aggregates, total_aggregates)} "
                    "event aggregate(s)."
                )
                if _table_exists(cursor, "event"):
                    total_events = cursor.execute("SELECT COUNT(*) FROM event").fetchone()[0]
                    cursor.execute(
                        f"""WITH expired(id) AS ({session_filter})
                            SELECT COUNT(*) FROM event
                            WHERE aggregate_id IN (SELECT id FROM expired)""",
                        params,
                    )
                    removed_events = cursor.fetchone()[0]
                    print(
                        "[+] Would remove "
                        f"{format_fraction(removed_events, total_events)} "
                        "event(s) via cascade."
                    )
            else:
                if _table_exists(cursor, "event"):
                    print(
                        "[*] Event table has no event_sequence table; "
                        "event cleanup would be skipped."
                    )
                else:
                    print("[*] Event tables not present; event cleanup would be skipped.")
        elif retain:
            print("[-] Database does not contain a session table; retention would be skipped.")
        else:
            tables = (
                "event", "event_sequence", "part", "message", "session_message",
                "session_input", "session_share", "session_context_epoch", "todo", "session",
            )
            for table in tables:
                if _table_exists(cursor, table):
                    count = cursor.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]
                    print(f"[+] Would remove {count:,} row(s) from {table}.")
        conn.close()
        conn = None
        print("[*] Dry run complete; no changes were made.")
    except Exception as e:
        print(f"[-] Database preview error: {e}")
    finally:
        if conn is not None:
            conn.close()


def vacuum_database(db_path):
    """Reclaim unused SQLite pages without changing any rows."""
    if not os.path.exists(db_path):
        print(f"[-] Database not found at {db_path}")
        return

    print(f"[*] Opening database at {db_path}...")
    try:
        initial_size = os.path.getsize(db_path)
        print(f"[*] Before vacuum: {format_bytes(initial_size)}")
        conn = sqlite3.connect(db_path)
        try:
            print("[*] Vacuuming database without deleting data (VACUUM)...")
            conn.execute("VACUUM;")
        finally:
            conn.close()
        final_size = os.path.getsize(db_path)
        print(f"[+] Database vacuumed. After vacuum: {format_bytes(final_size)}")
    except Exception as e:
        print(f"[-] Database vacuum error: {e}")


def _table_exists(cursor, table):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def _event_sequence_cascades(cursor):
    return any(
        row[2] == "event_sequence"
        and row[3] == "aggregate_id"
        and row[4] == "aggregate_id"
        and row[6].upper() == "CASCADE"
        for row in cursor.execute("PRAGMA foreign_key_list(event)").fetchall()
    )

def clean_json_caches(app_support):
    if not os.path.exists(app_support):
        print(f"[-] Application Support directory not found at {app_support}")
        return
        
    global_dat = os.path.join(app_support, "opencode.global.dat")
    if os.path.exists(global_dat):
        print("[*] Cleaning opencode.global.dat...")
        try:
            with open(global_dat, 'r') as f:
                data = json.load(f)
                
            data['notification'] = json.dumps({"list": []})
            data['prompt-history'] = json.dumps({"entries": []})
            
            if 'layout.page' in data:
                try:
                    layout_page = json.loads(data['layout.page'])
                    layout_page['lastProjectSession'] = {}
                    data['layout.page'] = json.dumps(layout_page)
                except:
                    pass
                    
            if 'layout' in data:
                try:
                    layout = json.loads(data['layout'])
                    layout['sessionView'] = {}
                    data['layout'] = json.dumps(layout)
                except:
                    pass
                    
            with open(global_dat, 'w') as f:
                json.dump(data, f)
            print("[+] opencode.global.dat cleaned.")
        except Exception as e:
            print(f"[-] Error cleaning global dat: {e}")
            
    workspace_pattern = os.path.join(app_support, "opencode.workspace.*.dat")
    for path in glob.glob(workspace_pattern):
        print(f"[*] Cleaning workspace file: {os.path.basename(path)}...")
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                
            keys_to_delete = [k for k in data.keys() if k.startswith('session:') or k in ('workspace:prompt', 'workspace:comments')]
            for k in keys_to_delete:
                del data[k]
                
            with open(path, 'w') as f:
                json.dump(data, f)
            print(f"[+] Cleaned {len(keys_to_delete)} keys from {os.path.basename(path)}")
        except Exception as e:
            print(f"[-] Error cleaning {os.path.basename(path)}: {e}")

def clean_logs(app_support, db_dir):
    log_dirs = [
        os.path.join(db_dir, "log"),
        os.path.join(app_support, "logs")
    ]
    
    for log_dir in log_dirs:
        if not os.path.exists(log_dir):
            continue
        print(f"[*] Truncating logs in {log_dir}...")
        for root, dirs, files in os.walk(log_dir):
            for file in files:
                if file.endswith(".log"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'w'):
                            pass
                    except Exception as e:
                        print(f"[-] Error truncating log {file}: {e}")
        print(f"[+] Logs in {os.path.basename(log_dir)} truncated.")

def delete_diffs_and_outputs(db_dir):
    target_dirs = [
        os.path.join(db_dir, "storage", "session_diff"),
        os.path.join(db_dir, "tool-output")
    ]
    
    for target_dir in target_dirs:
        if not os.path.exists(target_dir):
            continue
        print(f"[*] Deleting cached files in {target_dir}...")
        count = 0
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    count += 1
                except Exception as e:
                    print(f"[-] Error deleting file {file}: {e}")
        print(f"[+] Deleted {count} cache files from {os.path.basename(target_dir)}")

def format_bytes(size):
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(size)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024

def show_stats(db_path):
    if not os.path.exists(db_path):
        print(f"[-] Database not found at {db_path}")
        return

    print(f"[*] Reading database statistics from {db_path}...")
    try:
        # URI mode=ro ensures this command cannot create, lock, or modify the DB.
        uri = "file:" + quote(os.path.abspath(db_path)) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "session" not in tables:
            print("[-] Database does not contain a session table.")
            conn.close()
            return

        project_join = "LEFT JOIN project p ON p.id = s.project_id" if "project" in tables else ""
        project_name = (
            "COALESCE(NULLIF(p.name, ''), p.worktree, s.project_id, '(unknown project)')"
            if "project" in tables
            else "COALESCE(s.project_id, '(unknown project)')"
        )
        message_size = (
            "COALESCE((SELECT SUM(length(CAST(m.data AS BLOB))) "
            "FROM message m WHERE m.session_id = s.id), 0)"
            if "message" in tables
            else "0"
        )
        part_size = (
            "COALESCE((SELECT SUM(length(CAST(pt.data AS BLOB))) "
            "FROM part pt WHERE pt.session_id = s.id), 0)"
            if "part" in tables
            else "0"
        )
        rows = conn.execute(
            f"""SELECT {project_name} AS project, COUNT(*) AS sessions,
                       SUM(
                           length(CAST(COALESCE(s.title, '') AS BLOB)) +
                           length(CAST(COALESCE(s.metadata, '') AS BLOB)) +
                           length(CAST(COALESCE(s.summary_diffs, '') AS BLOB)) +
                           {message_size} + {part_size}
                       ) AS bytes
                FROM session s
                {project_join}
                GROUP BY project
                ORDER BY bytes DESC, project"""
        ).fetchall()
        total_sessions = sum(row[1] for row in rows)
        total_bytes = sum(row[2] or 0 for row in rows)
        conn.close()

        print("\nProject                              Sessions       Data size")
        print("-" * 64)
        for project, sessions, size in rows:
            print(f"{project[:34]:<34} {sessions:>8}   {format_bytes(size or 0):>12}")
        print("-" * 64)
        print(f"{'TOTAL':<34} {total_sessions:>8}   {format_bytes(total_bytes):>12}")
        print(f"\nLogical size includes stored session, message, and part payloads.")
        print(f"Database file size: {format_bytes(os.path.getsize(db_path))}")
    except Exception as e:
        print(f"[-] Database statistics error: {e}")

def build_parser():
    parser = argparse.ArgumentParser(
        description="Explicitly clean OpenCode history and local caches."
    )

    def add_flags(command):
        command.add_argument(
            "--yes",
            action="store_true",
            default=argparse.SUPPRESS,
            help="skip confirmation",
        )
        command.add_argument(
            "--no-pause",
            action="store_true",
            default=argparse.SUPPRESS,
            help="accepted for compatibility; never pauses after completion",
        )
    add_flags(parser)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    command_help = {
        "clean": "quit OpenCode and run every cleanup operation",
        "database": "clear and vacuum the SQLite database",
        "vacuum": "vacuum the SQLite database without deleting data",
        "caches": "clear prompt and session JSON caches",
        "logs": "truncate OpenCode log files",
        "outputs": "delete cached session diffs and tool output",
        "stats": "show session counts and estimated data size by project",
        "quit": "quit OpenCode without cleaning",
    }

    for name, help_text in command_help.items():
        command = commands.add_parser(name, help=help_text)
        add_flags(command)
        if name in ("clean", "database"):
            command.add_argument(
                "--retain",
                metavar="DURATION",
                help="retain sessions from the last duration (for example 30d, 4w, or 5m)",
                type=retention_argument,
            )
            command.add_argument(
                "--dry-run",
                action="store_true",
                help="show what database cleanup would remove without changing anything",
            )
        if name in ("database", "vacuum", "stats"):
            command.add_argument(
                "--db-path",
                help="use this SQLite database instead of the default path",
            )
    return parser


def retention_argument(value):
    try:
        parse_retention(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return value.lower()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if getattr(args, "dry_run", False):
        _, db_path = get_paths()
        if getattr(args, "db_path", None):
            db_path = os.path.abspath(args.db_path)
        preview_database(db_path, getattr(args, "retain", None), args.command)
        return 0

    if args.command != "stats" and not getattr(args, "yes", False):
        action = {
            "clean": "quit OpenCode and perform every cleanup operation",
            "database": "clear and vacuum the SQLite database",
            "vacuum": "vacuum the SQLite database without deleting data",
            "caches": "clear prompt and session JSON caches",
            "logs": "truncate OpenCode log files",
            "outputs": "delete cached session diffs and tool output",
            "quit": "quit OpenCode",
        }[args.command]
        try:
            answer = input(f"This will {action}. Continue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nNo confirmation received -- cancelled.")
            return 1
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 0

    print_banner()
    app_support, db_path = get_paths()
    if hasattr(args, "db_path") and args.db_path:
        db_path = os.path.abspath(args.db_path)
    db_dir = os.path.dirname(db_path)

    if args.command == "stats":
        show_stats(db_path)
        return 0

    if args.command in ("clean", "quit"):
        quit_opencode()
    if args.command in ("clean", "database"):
        clean_database(db_path, getattr(args, "retain", None))
    if args.command == "vacuum":
        vacuum_database(db_path)
    if args.command in ("clean", "caches"):
        clean_json_caches(app_support)
    if args.command in ("clean", "logs"):
        clean_logs(app_support, db_dir)
    if args.command in ("clean", "outputs"):
        delete_diffs_and_outputs(db_dir)

    print("=" * 60)
    print("      OpenCode requested operation completed.      ")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
