#!/usr/bin/env bash
# Double-clickable launcher (also: ./desktop.sh). First run sets up venv.
set -euo pipefail

# Double-click safety: on failure, keep the window open so the error can be read.
trap 'ec=$?; case $ec in 0|130|143) ;; *) [ -t 0 ] && { echo; echo "Stopped with an error (exit $ec). Press Enter to close."; read -r _; };; esac' EXIT

ROOT="$(cd "$(dirname "$0")" && pwd)"
if ! python3 -c "import ensurepip" 2>/dev/null; then
  echo "python3-venv missing. On Ubuntu/Debian run: sudo apt install python3-venv"
  exit 1
fi
[ -x "$ROOT/.venv/bin/python" ] || {
  echo "First run: creating environment…"
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
}
exec "$ROOT/.venv/bin/python" "$ROOT/desktop.py" "$@"
