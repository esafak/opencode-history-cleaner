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
    try:
        initial_size = os.path.getsize(db_path) / (1024 * 1024)
        print(f"[*] Initial database size: {initial_size:.2f} MB")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        if retain:
            cutoff = retention_cutoff(retain)
            if _table_exists(cursor, "session"):
                cursor.execute(
                    """WITH RECURSIVE retained_ancestors(id) AS (
                           SELECT id FROM session WHERE time_updated >= ?
                           UNION
                           SELECT s.parent_id
                           FROM session s
                           JOIN retained_ancestors r ON s.id = r.id
                           WHERE s.parent_id IS NOT NULL
                       )
                       DELETE FROM session
                       WHERE time_updated < ?
                         AND id NOT IN (SELECT id FROM retained_ancestors)""",
                    (cutoff, cutoff),
                )
                print(
                    f"[+] Removed sessions older than {retain} "
                    "(months are 30 days)."
                )
            else:
                print(
                    "[-] Database does not contain a session table; "
                    "retention cleanup skipped."
                )
            # Related rows use ON DELETE CASCADE. Global events are not tied to
            # sessions, so leave them untouched during a retention cleanup.
            tables_to_clear = []
        else:
            tables_to_clear = [
                "part", "message", "session_message", "session_input",
                "session_share", "session_context_epoch", "todo", "session",
                "event", "event_sequence"
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
        
        final_size = os.path.getsize(db_path) / (1024 * 1024)
        print(f"[+] Database cleaned and optimized. Final size: {final_size:.2f} MB")
        
    except Exception as e:
        print(f"[-] Database error: {e}")


def _table_exists(cursor, table):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None

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
            help="skip confirmation (combine with --no-pause for unattended use)",
        )
        command.add_argument(
            "--no-pause",
            action="store_true",
            default=argparse.SUPPRESS,
            help="do not wait for Enter when finished",
        )

    add_flags(parser)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    command_help = {
        "clean": "quit OpenCode and run every cleanup operation",
        "database": "clear and vacuum the SQLite database",
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
        if name in ("database", "stats"):
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

    if args.command != "stats" and not getattr(args, "yes", False):
        action = {
            "clean": "quit OpenCode and perform every cleanup operation",
            "database": "clear and vacuum the SQLite database",
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
    if args.command in ("clean", "caches"):
        clean_json_caches(app_support)
    if args.command in ("clean", "logs"):
        clean_logs(app_support, db_dir)
    if args.command in ("clean", "outputs"):
        delete_diffs_and_outputs(db_dir)

    print("=" * 60)
    print("      OpenCode requested operation completed.      ")
    print("=" * 60)
    if not getattr(args, "no_pause", False):
        input("\nPress Enter to exit...")
    return 0

if __name__ == "__main__":
    sys.exit(main())
