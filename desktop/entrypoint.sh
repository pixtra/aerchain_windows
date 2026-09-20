#!/usr/bin/env bash
# Container boot (Groq-only build): config -> database -> app. No local model.
set -euo pipefail

PORT="${PORT:-8000}"

[ -f /app/.env ] || cp /app/.env.example /app/.env
if [ -n "${GROQ_API_KEY:-}" ] && ! grep -Eq "^KTQ_GROQ_KEYS=.{5,}" /app/.env; then
  {
    echo "KTQ_GROQ_KEYS=$GROQ_API_KEY"
    echo "KTQ_LLM_URL=https://api.groq.com/openai/v1"
    echo "KTQ_LLM_MODEL=openai/gpt-oss-120b"
  } >> /app/.env
  echo "Groq key saved from GROQ_API_KEY"
fi
if ! grep -Eq "^KTQ_GROQ_KEYS=.{5,}|^KTQ_LLM_KEY=.{5,}" /app/.env; then
  echo "WARNING: no Groq key saved — AerBot answers 503 until a key is added."
fi

if [ ! -f /app/data/aerchain.db ]; then
  echo "building database…"
  python -m app.pipeline | tail -3
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --log-level warning
