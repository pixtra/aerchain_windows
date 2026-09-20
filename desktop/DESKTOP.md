# Aerchain desktop app (pywebview + Qt)

Native OS window around the same backend — no browser needed.

## Run
```bash
./desktop.sh        # first run creates .venv + installs everything
```
Close the window to stop everything. Needs on the machine: Python 3.10+,
and a Groq key pasted in Settings on first run (free at console.groq.com/keys).
No Ollama, no model download, no Tesseract required for Q&A (Tesseract only
matters for photo/scan uploads).

## Notes
- Backend serves on 127.0.0.1, random free port — LAN/tunnel sharing does not
  apply here; use `run.sh` + `share.sh` from the web layout for that.
- Own database (`data/aerchain.db`), built on first launch; fully separate
  from any other copy.
- `DESKTOP_TEST=1 ./desktop.sh` opens and auto-closes (smoke test).
- Single-file `.exe`/binary via PyInstaller is not built yet — say the word
  and it's the next step (large bundle: Qt WebEngine + model stay external).
