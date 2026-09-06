# OpenCode History Cleaner

A lightweight, cross-platform utility script to safely clear chat history, wipe prompt drafts, truncate log files, and optimize the local SQLite database of the **OpenCode** desktop application.

It automatically shrinks the local database size (often from gigabytes down to a few kilobytes) using SQLite's `VACUUM` process.

## 🚀 Features

- **App Shutdown**: The `clean` command gracefully terminates OpenCode before cleanup; targeted commands leave it running.
- **Database Optimization**: Clears all message/session tables (or trims old sessions with `--retain`) and executes SQLite `VACUUM` to free up disk space.
- **Cache Clean**: Wipes prompt history, drafts, scroll positions, and notifications.
- **Log Truncation**: Empties application log files to 0 bytes.
- **History Statistics**: Reports session counts and estimated stored data size by project without changing anything.
- **Cross-Platform**: Supports macOS, Windows, and Linux.

---

## 🛠️ How to Use

Running the Python script with no command is safe: it only displays the help
text and performs no cleanup. Cleanup commands ask for confirmation unless
`--yes` is supplied.

```bash
# Show help (does not change anything)
python3 clear_opencode_history.py

# Clean everything, with confirmation
python3 clear_opencode_history.py clean

# Clean everything non-interactively
python3 clear_opencode_history.py clean --yes --no-pause

# Run one operation only
python3 clear_opencode_history.py database --yes --no-pause

# Trim old sessions but retain the last 30 days
python3 clear_opencode_history.py database --retain 30d --yes --no-pause

# The same retention option can be used with the complete cleanup
python3 clear_opencode_history.py clean --retain 4w --yes --no-pause
python3 clear_opencode_history.py caches --yes --no-pause
python3 clear_opencode_history.py logs --yes --no-pause
python3 clear_opencode_history.py outputs --yes --no-pause

# Show session counts and sizes (read-only; no confirmation required)
python3 clear_opencode_history.py stats

# Test a copied database explicitly (never the default live database)
python3 clear_opencode_history.py database --db-path /tmp/opencode-test.db --yes --no-pause
```

Use `python3 clear_opencode_history.py --help` for all commands. `quit` only
closes OpenCode; `clean` closes it before cleaning. `stats` reports logical
session, message, and part payload sizes by project, plus the total database
file size; it does not modify the database.

### 🍎 macOS / Linux
1. Download `clear_opencode_history.py` and `clear_opencode_history.command` to the same folder.
2. Run `./clear_opencode_history.command clean` from Terminal to clean everything.
   * *Note: If macOS prevents execution, open Terminal and run `chmod +x clear_opencode_history.command` first.*

### 🪟 Windows
1. Make sure you have **Python 3** installed on your system.
2. Download `clear_opencode_history.py` and `clear_opencode_history.bat` to the same folder.
3. Run `clear_opencode_history.bat clean` from Command Prompt to clean everything.

---

## 🔒 Safety First
This utility **only** deletes your chat sessions, message history, logs, and prompt caches. It **preserves** your custom settings, VCS configurations, and open project directories, so you won't lose your workspace preferences.

## 🧪 Tests

The database tests use an immutable, read-only snapshot of `tests/opencode.db`
and mutate only per-test temporary copies. Run them with:

```bash
python -m unittest discover -s tests -t .
```

The `--db-path` option is accepted only by `database` (and `stats`) so a
database override cannot accidentally make `clean` operate on live cache or
log directories.

`--retain` accepts a positive number followed by `d` (days), `w` (weeks), or
`m` (months), for example `30d`, `4w`, or `5m`. Months are treated as 30 days.
Retention is based on the session's last-updated time and also keeps parent
sessions needed by retained child sessions. Without `--retain`, the `database`
operation removes all sessions as before. `clean --retain` still clears caches,
logs, and tool outputs; retention applies only to database sessions.
