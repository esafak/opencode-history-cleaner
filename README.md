# OpenCode History Cleaner

A lightweight, cross-platform utility script to safely clear chat history, wipe prompt drafts, truncate log files, and optimize the local SQLite database of the **OpenCode** desktop application.

It automatically shrinks the local database size (often from gigabytes down to a few kilobytes) using SQLite's `VACUUM` process.

## 🚀 Features

- **App Shutdown**: Gracefully terminates OpenCode before starting the cleanup process.
- **Database Optimization**: Clears all message/session tables and executes SQLite `VACUUM` to free up disk space.
- **Cache Clean**: Wipes prompt history, drafts, scroll positions, and notifications.
- **Log Truncation**: Empties application log files to 0 bytes.
- **Cross-Platform**: Supports macOS, Windows, and Linux.

---

## 🛠️ How to Use

### 🍎 macOS / Linux
1. Download `clear_opencode_history.py` and `clear_opencode_history.command` to the same folder.
2. Double-click `clear_opencode_history.command` to execute.
   * *Note: If macOS prevents execution, open Terminal and run `chmod +x clear_opencode_history.command` first.*

### 🪟 Windows
1. Make sure you have **Python 3** installed on your system.
2. Download `clear_opencode_history.py` and `clear_opencode_history.bat` to the same folder.
3. Double-click `clear_opencode_history.bat` to execute.

---

## 🔒 Safety First
This utility **only** deletes your chat sessions, message history, logs, and prompt caches. It **preserves** your custom settings, VCS configurations, and open project directories, so you won't lose your workspace preferences.
