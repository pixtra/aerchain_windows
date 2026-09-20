#!/usr/bin/env bash
# Pack Aerchain for another computer: code + scripts + docs, no secrets,
# no junk. Recipient extracts and runs ./setup.sh && ./run.sh.
# Usage: ./package.sh [output-dir]   (default: /tmp)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-/tmp}"
VER="$(date +%Y%m%d)"
TARBALL="$OUT/aerchain-ktq-$VER.tar.gz"

cd "$ROOT"
tar -czf "$TARBALL" \
  --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=.git --exclude=.run \
  --exclude=data/aerchain.db --exclude=data/uploads --exclude=data/*.log \
  --exclude=.env --exclude=tmp --exclude=/tmp \
  app static scripts data docs requirements.txt README.md DEPLOY.md \
  setup.sh run.sh share.sh package.sh Dockerfile .dockerignore \
  docker-compose.yml Caddyfile.example entrypoint.sh .env.example \
  tests 2>/dev/null || tar -czf "$TARBALL" \
  --exclude=.venv --exclude=__pycache__ --exclude=.run \
  --exclude=data/aerchain.db --exclude=data/uploads --exclude=data/*.log \
  --exclude=.env \
  app static requirements.txt README.md setup.sh run.sh share.sh

echo "Packed: $TARBALL"
du -h "$TARBALL"
echo "--- recipient needs: python 3.10+, ~8GB free disk, internet (model+packages), optional sudo for Tesseract ---"
echo "--- recipient runs:  tar xzf $(basename "$TARBALL") && cd aerchain-ktq && ./setup.sh && ./run.sh ---"
