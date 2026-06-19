#!/usr/bin/env python3
import os
import sys
import glob
import json
import sqlite3
import time
import subprocess
import platform

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

def clean_database(db_path):
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
        
        tables_to_clear = [
            "part", "message", "session_message", "session_input",
            "session_share", "session_context_epoch", "todo", "session",
            "event", "event_sequence"
        ]
        
        for table in tables_to_clear:
            try:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}';")
                if cursor.fetchone():
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

def main():
    print_banner()
    quit_opencode()
    app_support, db_path = get_paths()
    db_dir = os.path.dirname(db_path)
    
    clean_database(db_path)
    clean_json_caches(app_support)
    clean_logs(app_support, db_dir)
    delete_diffs_and_outputs(db_dir)
    print("=" * 60)
    print("      OpenCode history cleaned successfully!      ")
    print("=" * 60)
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
