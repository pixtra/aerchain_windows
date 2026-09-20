#!/usr/bin/env python3
"""Aerchain desktop app — native OS window around the local backend.

Starts the FastAPI backend on 127.0.0.1 (ephemeral free port) in a thread,
then opens it in a pywebview window. No browser needed. Answers come from
Groq cloud (keys in Settings). Close the window to stop everything.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
# own database: never touch any other copy's DB (must precede app imports,
# since database.py resolves DB_PATH at import time)
os.environ.setdefault("AERCHAIN_DB", os.path.join(ROOT, "data", "aerchain.db"))

APP_TITLE = "Aerchain · Kill-the-Quote"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_db():
    db = os.path.join(ROOT, "data", "aerchain.db")
    if os.path.exists(db):
        return
    print("Building database (first run)…", flush=True)
    from app import pipeline
    pipeline.refresh()


def serve(port: int):
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=port,
                log_level="warning")


def wait_up(port: int, timeout: int = 60) -> bool:
    import urllib.request
    url = f"http://127.0.0.1:{port}/api/health"
    for _ in range(timeout * 2):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    port = int(os.environ.get("PORT", "0")) or free_port()
    ensure_db()
    t = threading.Thread(target=serve, args=(port,), daemon=True)
    t.start()
    if not wait_up(port):
        print("Backend failed to start.", flush=True)
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"Aerchain desktop → {url}", flush=True)
    try:
        import webview
    except ImportError:
        print("pywebview not installed. Run: .venv/bin/pip install pywebview",
              flush=True)
        return 1
    if os.environ.get("DESKTOP_TEST") == "1":
        # headless smoke test: open and close automatically
        def _close():
            time.sleep(6)
            try:
                for w in webview.windows:
                    w.destroy()
            except Exception:
                pass
        threading.Thread(target=_close, daemon=True).start()
    webview.create_window(APP_TITLE, url, width=1440, height=900,
                          min_size=(1100, 700))
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
