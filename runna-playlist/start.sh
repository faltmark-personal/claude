#!/bin/bash
# macOS: double-click to start. First run installs everything (needs Python 3.10+ from python.org).
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3)
if [ -z "$PY" ]; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close."; exit 1
fi
if [ ! -x .venv/bin/runna-playlist ]; then
  echo "First run: setting things up (about a minute)..."
  "$PY" -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e '.[ytmusic]' || {
    read -r -p "Setup failed (see above). Press Enter to close."; exit 1; }
fi
exec .venv/bin/runna-playlist
