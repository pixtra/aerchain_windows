# Aerchain app — one project, three ways to run

| Mode | Where | How |
|---|---|---|
| Local web | `web/` | `cd web && ./run.sh` → http://localhost:8000/ |
| Global link | `web/` | `./run.sh` first, then `./share.sh` (Ctrl-C closes) |
| Desktop | `desktop/` | `cd desktop && ./desktop.sh` (native window, no browser) |

`web/` and `desktop/` are independent copies: separate databases, uploads,
drafts and conditions. They share only Ollama (one model server) and system
Tesseract. Each copy builds its own `.venv` via its `setup.sh`.

## For non-technical clients (double-click, no terminal)

1. Open the `aerchain_app` folder, double-click **`Aerchain-Web.desktop`**
   (browser app) or **`Aerchain-Desktop.desktop`** (own window).
2. First launch opens a terminal and runs setup itself (Python env, model,
   database) — just wait for the browser/window.
3. If Linux asks, choose **Run / Run in Terminal** (or right-click →
   Allow Launching once). If a step fails, the window stays open showing
   the exact error instead of vanishing.
