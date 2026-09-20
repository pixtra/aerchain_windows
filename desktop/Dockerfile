# Aerchain Kill-the-Quote (Groq-only build) — container deploy (Fly.io / Render / Railway / VPS).
# Vercel-style serverless does NOT work here (SQLite writes, Tesseract binary).
# No local model: the image stays small and answers come from Groq cloud —
# pass GROQ_API_KEY (or mount a .env with KTQ_GROQ_KEYS). ~512MB–1GB RAM suffices.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY scripts/ ./scripts/
COPY setup.sh run.sh ./
COPY .env.example ./

# persistent state lives here — mount a volume on it (data/aerchain.db,
# data/uploads, .env)
VOLUME ["/app/data"]
RUN mkdir -p /app/data /app/.run

EXPOSE 8000
COPY entrypoint.sh ./
ENTRYPOINT ["./entrypoint.sh"]
