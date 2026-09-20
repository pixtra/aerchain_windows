#!/usr/bin/env bash
# Share the GROQ build with someone far away: public HTTPS link via Cloudflare.
# Usage: ./share.sh [PORT]   (default 8136; the groq app must run via ./run.sh)
# Refuses to share any other build (e.g. the main app) — sharing the wrong
# copy is worse than sharing nothing.
# Ctrl-C closes the link. Anyone with the link can use the app — no login.
set -euo pipefail

# Double-click safety: on failure, keep the window open so the error can be read.
trap 'ec=$?; case $ec in 0|130|143) ;; *) [ -t 0 ] && { echo; echo "Stopped with an error (exit $ec). Press Enter to close."; read -r _; };; esac' EXIT

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-${PORT:-8136}}"
BIN="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"
export PATH="$HOME/.local/bin:$PATH"

die() { echo "ERROR: $*"; exit 1; }

is_groq_build() {  # $1 = port; true only if the groq-only build answers there
  curl -s -m 3 "http://127.0.0.1:$1/api/health" 2>/dev/null | grep -q "groq-only"
}

if ! is_groq_build "$PORT"; then
  if curl -s -m 3 "http://127.0.0.1:$PORT/api/settings/provider" 2>/dev/null \
      | grep -q "Local model"; then
    die "port $PORT serves the MAIN app (it has a Local model), not the groq build. Start the groq app (./run.sh 8136) and share that: ./share.sh 8136"
  fi
  for p in 8136 8137 8000 8001 8002; do
    if [ "$p" != "$PORT" ] && is_groq_build "$p"; then
      die "no groq app on :$PORT — but one answers on :$p. Run: ./share.sh $p"
    fi
  done
  die "no groq app on :$PORT — start it first: ./run.sh $PORT"
fi

if [ ! -x "$BIN" ]; then
  echo "Fetching cloudflared (one time, no root)…"
  mkdir -p "$HOME/.local/bin"
  VER="$(curl -s -m 20 https://api.github.com/repos/cloudflare/cloudflared/releases/latest \
    | grep -o '"tag_name": "[^"]*"' | head -1 | cut -d'"' -f4)"
  [ -n "$VER" ] || die "couldn't resolve cloudflared version (offline?)"
  curl -sL -o "$BIN" "https://github.com/cloudflare/cloudflared/releases/download/$VER/cloudflared-linux-amd64"
  chmod +x "$BIN"
fi

LOG="$ROOT/.run/share-$PORT.log"
mkdir -p "$ROOT/.run"
echo "Opening public link for http://localhost:$PORT … (Ctrl-C to close)"
"$BIN" tunnel --no-autoupdate --url "http://localhost:$PORT" >"$LOG" 2>&1 </dev/null &
TUNPID=$!
if [ -z "${TUNPID:-}" ]; then die "could not start tunnel (see $LOG)"; fi
cleanup() { kill "$TUNPID" 2>/dev/null; echo; echo "Link closed."; }
trap cleanup INT TERM

URL=""
for _ in $(seq 1 30); do
  URL="$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "Tunnel didn't come up — see $LOG"; kill "$TUNPID" 2>/dev/null; exit 1; }

echo ""
echo -e "\e[1;32mShare this link → $URL\e[0m"
echo -e "\e[1;33mWarning: no login — anyone with the link can view, upload, and factory-reset. Close it when the demo ends.\e[0m"
wait "$TUNPID"
