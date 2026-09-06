#!/bin/bash
cd "$(dirname "$0")"
if [ "$#" -eq 0 ]; then
    python3 clear_opencode_history.py clean
else
    python3 clear_opencode_history.py "$@"
fi
