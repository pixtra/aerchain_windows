#!/usr/bin/env bash
# Aerchain Kill-the-Quote (Groq-only build) — daily start. Usage: ./run.sh [PORT]
# Starts the app, opens the dashboard. No local model server in this build.
# Ctrl-C stops the app server. Never uses pkill.
set -euo pipefail

# Double-click safety: on failure, keep the window open so the error can be read.
trap 'ec=$?; case $ec in 0|130|143) ;; *) [ -t 0 ] && { echo; echo "Stopped with an error (exit $ec). Press Enter to close."; read -r _; };; esac' EXIT

ROOT="$(cd "$(dirname "$0")" && pwd)"
HEADLESS="${HEADLESS:-0}"
if [ "${1:-}" = "--headless" ]; then HEADLESS=1; shift; fi
PORT="${1:-${PORT:-8136}}"
RUNDIR="$ROOT/.run"
PIDFILE="$RUNDIR/uvicorn-$PORT.pid"

die() { echo "ERROR: $*"; exit 1; }
[ -x "$ROOT/.venv/bin/python" ] || die "not set up yet — run ./setup.sh first"

health() { curl -s -m 2 "http://127.0.0.1:$PORT/api/health" 2>/dev/null | grep -q ok; }

# already running? just point at it
if health; then
  echo "Already running → http://localhost:$PORT/"
  exit 0
fi
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  die "port $PORT is taken by something else — try:  ./run.sh 8001"
fi

# stale pidfile from a crash?
if [ -f "$PIDFILE" ] && ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  rm -f "$PIDFILE"
fi

# config + database
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"
[ -f "$ROOT/data/aerchain.db" ] || { echo "Building database (first run)…"; (cd "$ROOT" && .venv/bin/python -m app.pipeline | tail -2); }

# Groq-only build: no local model server. Warn once if no key is saved.
if ! grep -Eq "^KTQ_GROQ_KEYS=.{5,}|^KTQ_LLM_KEY=.{5,}" "$ROOT/.env" 2>/dev/null; then
  echo "NOTE: no Groq key saved — AerBot will report unconfigured until you add one in Settings."
fi

# app server (direct child: $! is the real PID for trap/wait/pidfile)
mkdir -p "$RUNDIR"
echo $$ > "$RUNDIR/run-$PORT.pid"
echo "Starting Aerchain on port $PORT…"
cd "$ROOT"
if [ "$HEADLESS" = "1" ]; then
  nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
    --log-level warning >"$RUNDIR/app-$PORT.log" 2>&1 </dev/null &
else
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
    --log-level warning >"$RUNDIR/app-$PORT.log" 2>&1 &
fi
SRV=$!
echo "$SRV" > "$PIDFILE"
cleanup() { kill "$SRV" 2>/dev/null; rm -f "$PIDFILE" "$RUNDIR/run-$PORT.pid"; echo; echo "Stopped."; }
trap cleanup INT TERM

for _ in $(seq 1 20); do health && break; sleep 1; done
health || { echo "Server failed to start — see $RUNDIR/app-$PORT.log"; rm -f "$PIDFILE"; exit 1; }

URL="http://localhost:$PORT/"
LANIP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo -e "\e[1;32mAerchain is live → $URL\e[0m  (Ctrl-C to stop)"
if [ -n "$LANIP" ]; then
  echo -e "Same-network devices → \e[1mhttp://$LANIP:$PORT/\e[0m  (no login — trusted networks only)"
fi
echo "Share beyond your network (deliberate act, no login): ./share.sh $PORT"
if [ "$HEADLESS" = "1" ]; then
  echo "Headless: staying up detached (pid $SRV). Stop with: kill $SRV"
  trap - INT TERM
  exit 0
fi
command -v xdg-open >/dev/null && (xdg-open "$URL" >/dev/null 2>&1 &) || true
wait "$SRV"
