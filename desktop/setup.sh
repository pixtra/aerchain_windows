#!/usr/bin/env bash
# Aerchain Kill-the-Quote (Groq-only build) — one-time setup. Idempotent: safe to re-run.
# Installs: python venv + deps, Tesseract (OCR), Groq key, and builds the database.
# There is no local model in this build — answers come only from Groq cloud.
set -euo pipefail

# Double-click safety: on failure, keep the window open so the error can be read.
trap 'ec=$?; case $ec in 0|130|143) ;; *) [ -t 0 ] && { echo; echo "Stopped with an error (exit $ec). Press Enter to close."; read -r _; };; esac' EXIT

ROOT="$(cd "$(dirname "$0")" && pwd)"

ok()   { printf '  \e[32m[ok]\e[0m %s\n' "$*"; }
step() { printf '\e[1m%s\e[0m\n' "$*"; }
warn() { printf '  \e[33m[warn]\e[0m %s\n' "$*"; }

# --- 1. python ---------------------------------------------------------------
step "1/5  Python"
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.10+ and re-run."; exit 1
fi
PYV="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$(printf '%s\n3.10\n' "$PYV" | sort -V | head -1)" != "3.10" ]; then
  echo "ERROR: python $PYV too old (need 3.10+)."; exit 1
fi
ok "python $PYV"

# --- 2. venv + deps ----------------------------------------------------------
step "2/5  Python environment"
if ! python3 -c "import ensurepip" 2>/dev/null; then
  echo "  python3-venv missing - trying to install it…"
  if sudo -n true 2>/dev/null && command -v apt-get >/dev/null; then
    sudo -n apt-get install -y -q python3-venv >/dev/null 2>&1 \
      || { echo "ERROR: couldn't install python3-venv. Run: sudo apt install python3-venv"; exit 1; }
  else
    echo "ERROR: python3 -m venv is unavailable. On Ubuntu/Debian run: sudo apt install python3-venv"
    exit 1
  fi
fi
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
ok "dependencies installed"

# --- 3. tesseract (real OCR) -------------------------------------------------
step "3/5  OCR engine (Tesseract)"
if command -v tesseract >/dev/null; then
  ok "$(tesseract --version 2>/dev/null | head -1)"
elif sudo -n true 2>/dev/null && command -v apt-get >/dev/null; then
  sudo -n apt-get install -y -q tesseract-ocr >/dev/null 2>&1 \
    && ok "tesseract installed" \
    || warn "apt install failed — image OCR will use degraded mode."
else
  warn "tesseract not found and no passwordless sudo."
  warn "  For real image OCR run:  sudo apt install tesseract-ocr"
  warn "  Continuing — everything else works."
fi

# --- 4. Groq API key (required — this build answers only through Groq) ----
step "4/5  Groq API key"
[ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; echo "  created .env"; }
if grep -Eq "^KTQ_GROQ_KEYS=.{5,}|^KTQ_LLM_KEY=.{5,}" "$ROOT/.env" 2>/dev/null; then
  ok "Groq key already configured (add more anytime in Settings)"
else
  KEY="${GROQ_API_KEY:-}"
  if [ -z "$KEY" ] && [ -t 0 ]; then
    echo "  This build answers ONLY through Groq (free at console.groq.com/keys)."
    printf '  Paste a gsk-… key (Enter to skip for now): '
    IFS= read -rs KEY || true
    echo ""
  fi
  if [ -n "$KEY" ]; then
    CODE="$(curl -s -m 15 -o /dev/null -w "%{http_code}" \
      https://api.groq.com/openai/v1/models -H "Authorization: Bearer $KEY" || echo 000)"
    if [ "$CODE" != "200" ]; then
      warn "key rejected by Groq (HTTP $CODE) — not saved. Add one later in Settings."
      KEY=""
    fi
  fi
  if [ -n "$KEY" ]; then
    {
      echo "KTQ_GROQ_KEYS=$KEY"
      echo "KTQ_LLM_URL=https://api.groq.com/openai/v1"
      echo "KTQ_LLM_MODEL=openai/gpt-oss-120b"
    } >> "$ROOT/.env"
    ok "Groq key saved"
  else
    warn "no key — AerBot will report unconfigured until you add one in Settings."
  fi
fi

# --- 5. database -------------------------------------------------------------
step "5/5  Database"
if [ ! -f "$ROOT/data/aerchain.db" ]; then
  (cd "$ROOT" && .venv/bin/python -m app.pipeline | tail -4)
else
  ok "database present (re-seed anytime from the dashboard)"
fi

# --- 7. optional shared access password (empty = open, no login) -------------
if ! grep -q "^KTQ_APP_PASSWORD=" "$ROOT/.env" 2>/dev/null; then
  if [ -t 0 ]; then
    printf '  Shared access password for browsers (Enter to skip, stays open): '
    IFS= read -rs _pw || true
    echo ""
    _pw="${_pw#"${_pw%%[![:space:]]*}"}"
    _pw="${_pw%"${_pw##*[![:space:]]}"}"
    if [ -n "$_pw" ]; then
      if [ "${#_pw}" -lt 4 ]; then
        echo "  too short (min 4) — skipping; set one later in Settings."
      else
        printf 'KTQ_APP_PASSWORD=%s\n' "$_pw" >> "$ROOT/.env"
        ok "access password set (change anytime in Settings)"
      fi
    else
      echo "  no password — app stays open (set one later in Settings)."
    fi
  fi
fi

echo ""
echo -e "\e[1;32mSetup complete.\e[0m  Start the app with:  ./run.sh"
# Double-click launchers (absolute paths baked in — no shell tricks, so they
# validate clean and work on GNOME/KDE/XFCE). Trusted automatically if gio exists.
APP_ROOT="$(cd "$ROOT/.." && pwd)"
cat > "$APP_ROOT/Aerchain-Web.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Aerchain Web
Comment=Start the Aerchain web app (opens your browser)
Terminal=true
Exec="$APP_ROOT/web/run.sh"
Categories=Office;
Keywords=procurement;rfx;
EOF
cat > "$APP_ROOT/Aerchain-Desktop.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Aerchain Desktop
Comment=Start Aerchain in its own window (no browser needed)
Terminal=true
Exec="$APP_ROOT/desktop/desktop.sh"
Categories=Office;
Keywords=procurement;rfx;
EOF
chmod +x "$APP_ROOT/Aerchain-Web.desktop" "$APP_ROOT/Aerchain-Desktop.desktop"
if command -v gio >/dev/null 2>&1; then
  gio set "$APP_ROOT/Aerchain-Web.desktop" metadata::trusted true 2>/dev/null || true
  gio set "$APP_ROOT/Aerchain-Desktop.desktop" metadata::trusted true 2>/dev/null || true
fi
echo "  double-click icons ready: Aerchain-Web.desktop, Aerchain-Desktop.desktop"
