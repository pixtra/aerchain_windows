# Persistent hosting — survives your laptop dying

Goal: the demo lives on a small VPS (or Fly.io/Render/Railway) with a login
in front, reachable 24/7. Groq-only: ~1GB RAM, no model download, no Ollama.

## 0. What you need
- A VPS with Ubuntu 24.04 + Docker (Hetzner CX22 / DigitalOcean $5–6 droplet
  is enough for Groq mode), or a Fly.io/Render/Railway account.
- A free Groq key (console.groq.com/keys) — same one as local, or a fresh one
  you can revoke later. Never commit it.
- (Optional, recommended) A domain/subdomain for HTTPS + login.

## 1. Ship the code (no secrets, no junk)
From this machine, copy everything **except** `.venv/`, `data/*.db`,
`data/uploads/*`, `.run/`, `.env`:
```bash
rsync -av --exclude .venv --exclude 'data/*.db' --exclude 'data/uploads/*' \
  --exclude .run --exclude .env ./ user@vps:~/aerchain-ktq/
```

## 2. Start it (Groq mode)
On the VPS:
```bash
cd ~/aerchain-ktq
export GROQ_API_KEY=gsk-...        # your key, stays on the server
docker compose up -d --build
sleep 20 && curl -s http://localhost:8000/api/health
```
First boot builds the golden DB automatically. The app is now permanent —
laptop on, off, or on fire, it keeps serving.

## 3. Put a login + HTTPS in front (do not skip for public links)
```bash
export MY_DOMAIN=demo.yourdomain.com DEMO_USER=buyer
export DEMO_HASH='$(caddy hash-password)'   # run inside caddy container; paste result
cp Caddyfile.example Caddyfile
docker run -d --name caddy -p 80:80 -p 443:443 \
  -v $PWD/Caddyfile:/etc/caddy/Caddyfile -v caddy-data:/data \
  --link aerchain-ktq-app-1:app caddy:2-alpine
```
Share `https://demo.yourdomain.com` + the buyer username/password. Close the
tunnel on your laptop — it's redundant now.

## 4. Operate
- Update: `git pull` (or re-rsync) → `docker compose up -d --build`.
- Logs: `docker compose logs -f app`.
- Pristine demo: Settings → Factory reset in the UI.
- Revoke: delete the Groq key at console.groq.com/keys; `/api/aerbot/*`
  returns 503 with guidance until a working key is saved.
- Backup: the `aerchain-data` volume holds DB + uploads (`docker run --rm
  -v aerchain-data:/d -v $PWD:/b ubuntu tar czf /b/backup.tgz /d`).

## Why not cheaper hosting
Vercel/Netlify-style serverless can't run this (read-only FS kills SQLite,
no Tesseract binary, 10–60s timeouts vs model answers). It needs a
real machine; the smallest one that fits is fine.
