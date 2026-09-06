@echo off
cd /d "%~dp0"
if "%~1"=="" (
    python clear_opencode_history.py clean
) else (
    python clear_opencode_history.py %*
)
