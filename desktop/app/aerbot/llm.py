"""LLM provider client — Groq-only build.

One provider, N keys: every saved Groq key becomes a chain link, tried in
listed order with automatic failover on 429/5xx/timeouts. 401/403 fail fast
so bad keys surface instead of silently burning the next key.
"""
from __future__ import annotations

import json
import os
import re as _re
import threading as _threading
from contextlib import contextmanager as _cm
from dataclasses import dataclass, field

import httpx

GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"
TIMEOUT = 120  # Groq is fast; fail over quickly instead of hanging

_MODEL_NAME_RE = _re.compile(r"^[A-Za-z0-9._\-/:]{1,80}$")


def _env_path():
    import pathlib
    override = os.environ.get("KTQ_ENV_FILE")
    if override:
        return pathlib.Path(override)
    return pathlib.Path(__file__).resolve().parent.parent.parent / ".env"


def _load_env_file() -> None:
    """Load KEY=VALUE lines from a project-root .env (never committed).
    Existing shell exports win; a key present in both is not overwritten."""
    import os as _os
    path = _env_path()
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not _os.environ.get(key):
            _os.environ[key] = value
            _FILE_OWNED.add(key)


_FILE_OWNED: set[str] = set()

_load_env_file()

# Keys this module owns: re-synced from .env whenever the file changes, so a
# key saved through one server process (or by hand) is picked up by all
# running processes without a restart. Never add secrets outside this list.
_MANAGED_KEYS = ("KTQ_GROQ_KEYS", "KTQ_LLM_URL", "KTQ_LLM_KEY",
                 "KTQ_LLM_MODEL", "KTQ_OCR_LANG", "KTQ_APP_PASSWORD")
_ENV_MTIME: float | None = None


def _maybe_reload_env() -> None:
    """If .env changed on disk since we last read it, re-apply managed keys —
    but ONLY file-owned ones (taken from this file on a previous load) or
    keys absent from the process env. Explicit shell exports, Docker -e flags,
    and test monkeypatches always win."""
    global _ENV_MTIME
    try:
        mtime = _env_path().stat().st_mtime
    except OSError:
        return
    if _ENV_MTIME is not None and mtime <= _ENV_MTIME:
        return
    _ENV_MTIME = mtime
    try:
        lines = _env_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in _MANAGED_KEYS and (key in _FILE_OWNED or key not in os.environ):
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
            _FILE_OWNED.add(key)


class ModelNotConfigured(Exception):
    """Raised when no Groq key is available."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


def _strip_nones(node):
    """Recursively drop None values from tool schemas (strict backends 400
    on e.g. "default": null)."""
    if isinstance(node, dict):
        return {k: _strip_nones(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_strip_nones(v) for v in node]
    return node


def _openai_tool_schema(tools):
    return [{"type": "function",
             "function": {"name": t["name"], "description": t.get("description", ""),
                           "parameters": _strip_nones(t.get("parameters") or
                                                      {"type": "object",
                                                       "properties": {}})}} for t in tools]


def _call_openai(cfg: dict, messages, system, tools) -> ChatResponse:
    payload = {"model": cfg["model"], "temperature": 0.1,
               "messages": ([{"role": "system", "content": system}] + messages)}
    if tools:  # some OpenAI-compatible hosts 400 on empty tools arrays
        payload["tools"] = _openai_tool_schema(tools)
        payload["tool_choice"] = "auto"
    headers = {"Content-Type": "application/json"}
    if cfg.get("key"):
        headers["Authorization"] = f"Bearer {cfg['key']}"
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(cfg["url"] + "/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
    calls = []
    for tc in msg.get("tool_calls") or []:
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except (json.JSONDecodeError, KeyError, TypeError):
            args = {}
        calls.append(ToolCall(id=tc.get("id") or f"call-{len(calls)}",
                              name=tc["function"]["name"], arguments=args))
    return ChatResponse(content=msg.get("content"), tool_calls=calls)


def save_env_values(updates: dict, path=None) -> None:
    """Persist keys to .env preserving comments and other entries."""
    with _env_locked():
        _write_env_values(updates, path)


def _write_env_values(updates: dict, path=None) -> None:
    path = path or _env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen, out = set(), []
    for ln in lines:
        s = ln.strip()
        key = s.split("=", 1)[0].strip() if s and not s.startswith("#") and "=" in s else ""
        if key and key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(ln)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


@_cm
def _env_locked():
    """Cross-process mutex for .env read-modify-write (atomic mkdir lock,
    portable: POSIX + Windows). Stale locks (>10s, e.g. crashed writer)
    are reclaimed."""
    import shutil
    import time as _t
    lockdir = str(_env_path()) + ".lockdir"
    for _ in range(200):
        try:
            os.mkdir(lockdir)
            break
        except FileExistsError:
            try:
                if _t.time() - os.stat(lockdir).st_mtime > 10:
                    shutil.rmtree(lockdir, ignore_errors=True)
                    continue
            except OSError:
                pass
            _t.sleep(0.05)
    else:
        raise TimeoutError("env lock busy")
    try:
        yield
    finally:
        shutil.rmtree(lockdir, ignore_errors=True)


def _pool_from_file() -> list[str]:
    """Read the persisted key pool straight from .env (not process env)."""
    try:
        lines = _env_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    vals: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        vals[key.strip()] = value.strip().strip('"').strip("'")
    pool = [k.strip() for k in vals.get("KTQ_GROQ_KEYS", "").split(",") if k.strip()]
    if "groq" in vals.get("KTQ_LLM_URL", "") and vals.get("KTQ_LLM_KEY"):
        pool.append(vals["KTQ_LLM_KEY"].strip())
    seen, out = set(), []
    for k in pool:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _groq_keys() -> list[str]:
    """All configured Groq keys, in priority order: the pool first, then the
    legacy single-key slot. Deduped."""
    keys: list[str] = []
    pool = os.environ.get("KTQ_GROQ_KEYS", "")
    keys += [k.strip() for k in pool.split(",") if k.strip()]
    url = os.environ.get("KTQ_LLM_URL", "")
    if "groq" in url and os.environ.get("KTQ_LLM_KEY"):
        keys.append(os.environ["KTQ_LLM_KEY"].strip())
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _mask_key(key: str) -> str:
    return ("…" + key[-4:]) if len(key) > 8 else "…(short)"


def _key_hint(key: str) -> str:
    """What the UI may show: key family + last 4, never the secret.
    Real Groq keys start with gsk_ (older ones gsk-)."""
    fam = "gsk-" if key.startswith("gsk") else "key-"
    return fam + _mask_key(key)


def _valid_model_name(name: str) -> bool:
    return bool(name) and bool(_MODEL_NAME_RE.fullmatch(name)) \
        and ".." not in name and name[0] not in "./"


def validate_groq_key(key: str) -> bool:
    try:
        r = httpx.get(GROQ_URL + "/models",
                      headers={"Authorization": f"Bearer {key}"}, timeout=15)
        if r.status_code == 200:
            return True
        raise ValueError(f"Groq answered HTTP {r.status_code} "
                         f"({'bad or revoked key' if r.status_code == 401 else 'see console.groq.com/keys'})")
    except httpx.HTTPError as e:
        raise ValueError(f"could not reach Groq ({e.__class__.__name__}) — not saved")
    return False


def _groq_model() -> str:
    return os.environ.get("KTQ_LLM_MODEL") or GROQ_MODEL


def resolve_chain() -> list[tuple[str, dict]]:
    """One entry per saved Groq key, in pool order. Raises ModelNotConfigured
    when the pool is empty. .env is re-synced first, so key edits on any
    process propagate here without a restart."""
    _maybe_reload_env()
    keys = _groq_keys()
    if not keys:
        return []
    model = _groq_model()
    return [("openai", {"url": GROQ_URL, "key": key, "model": model,
                        "label": "groq", "key_index": i})
            for i, key in enumerate(keys)]


def resolve_provider() -> tuple[str, dict]:
    """First chain link, or raise ModelNotConfigured with guidance."""
    chain = resolve_chain()
    if not chain:
        raise ModelNotConfigured(
            "No Groq API key saved. Add one in Settings → Groq cloud "
            "(free at console.groq.com/keys).")
    return chain[0]


_LOUD_STATUS = (401, 403, 404)

LAST_PROVIDER = {"name": None, "fell_back": False}


def _serving_display() -> str | None:
    """Human-readable 'who answered' — always 'Groq cloud' here, with a
    fallback marker when a later pool key served the answer."""
    name = LAST_PROVIDER.get("name") or ""
    if not name:
        return None
    if LAST_PROVIDER.get("fell_back"):
        return name + " (fallback key)"
    return name
_STICKY: dict = {"name": None, "at": 0.0}
_STICKY_TTL = 120.0


def _should_fallback(exc: BaseException) -> bool:
    """Fall back across keys on rate limits, outages, network issues and
    backend quirks. Only auth/forbidden/unknown-model errors fail fast."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code not in _LOUD_STATUS
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError,
                            httpx.RemoteProtocolError, httpx.ReadError,
                            httpx.WriteError, httpx.PoolTimeout))


def _retry_after(exc: BaseException, attempt: int) -> float:
    """Seconds to wait before retrying: honor Groq's Retry-After header,
    else 2s/5s backoff. Caps keep slow answers bounded."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            return min(float(exc.response.headers.get("retry-after", 0)) or 0,
                       30) or (2.0 if attempt == 0 else 5.0)
        except (TypeError, ValueError):
            pass
    return 2.0 if attempt == 0 else 5.0


def _is_retriable(exc: BaseException) -> bool:
    # NOTE: Groq also emits transient 400s under load (flaky request
    # validation that succeeds on identical retry) — so 400 rides along.
    # Genuinely malformed requests still raise after 3 attempts.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (400, 408, 429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError,
                            httpx.RemoteProtocolError, httpx.ReadError,
                            httpx.WriteError, httpx.PoolTimeout))


def client_chat(system: str, messages, tools) -> ChatResponse:
    """Groq call over the key pool: first key serves until it errors, then
    retried with backoff, then the next key takes over mid-answer. Sticky per
    answer (120s TTL) so one answer never flaps between keys."""
    import time as _t
    chain = resolve_chain()
    if not chain:
        raise ModelNotConfigured(
            "No Groq API key saved. Add one in Settings → Groq cloud "
            "(free at console.groq.com/keys).")
    stick = _STICKY["name"]
    if stick and _t.time() - _STICKY["at"] < _STICKY_TTL:
        hit = [c for c in chain if f"{c[0]}:{c[1].get('model')}:{c[1].get('key_index')}" == stick]
        if hit:
            chain = hit + [c for c in chain if c not in hit]
    last_err: BaseException | None = None
    for i, (provider, cfg) in enumerate(chain):
        for attempt in range(3):
            try:
                resp = _call_openai(cfg, messages, system, tools)
                LAST_PROVIDER["name"] = "Groq cloud"
                LAST_PROVIDER["fell_back"] = i > 0
                _STICKY["name"] = f"{provider}:{cfg.get('model')}:{cfg.get('key_index')}"
                _STICKY["at"] = _t.time()
                return resp
            except Exception as e:  # noqa: BLE001 — routed below
                last_err = e
                if not _is_retriable(e) or attempt == 2:
                    break
                _t.sleep(_retry_after(e, attempt))
        if i == len(chain) - 1 or not _should_fallback(last_err):
            break
    if isinstance(last_err, httpx.HTTPStatusError) and last_err.response.status_code == 429:
        raise RuntimeError(
            f"Groq rate limit reached on all {len(chain)} key(s) — wait a minute "
            f"and retry, or add another free key in Settings → Groq cloud.") from last_err
    raise last_err  # pragma: no cover — loop always returns or raises


def provider_settings() -> dict:
    """UI-safe settings: keys are never returned, only masked hints."""
    chain = resolve_chain()
    keys = _groq_keys()
    return {"mode": "groq",
            "has_groq_key": bool(keys),
            "groq_keys": [{"index": i, "hint": _key_hint(k)}
                          for i, k in enumerate(keys)],
            "ocr_lang": os.environ.get("KTQ_OCR_LANG", "eng"),
            "chain": ["Groq cloud" + (f" #{c[1]['key_index'] + 1}" if len(chain) > 1 else "")
                      for c in chain],
            "providers": [{"label": "groq", "title": "Groq cloud",
                           "status": f"{c[1].get('model')} · key #{c[1]['key_index'] + 1}"
                           if keys else "no key saved",
                           "enabled": True, "locked": False} for c in chain] or
            [{"label": "groq", "title": "Groq cloud",
              "status": "no key saved — add one below", "enabled": True,
              "locked": False}],
            "serving": LAST_PROVIDER["name"],
            "fell_back": LAST_PROVIDER["fell_back"]}


def set_provider_settings(groq_keys_add: str | None = None,
                          groq_keys_remove: int | None = None,
                          groq_keys_order: list[int] | None = None,
                          ocr_lang: str | None = None) -> dict:
    """Groq-only settings. groq_keys_order is a permutation of current pool
    indices (from key-list drag-and-drop)."""
    updates: dict[str, str] = {}
    if ocr_lang is not None and ocr_lang.strip():
        updates["KTQ_OCR_LANG"] = "+".join(
            c for c in ocr_lang.replace(",", "+").split("+") if c.strip()) or "eng"
    with _env_locked():
        pool = _pool_from_file()
        if groq_keys_remove is not None:
            if not (0 <= groq_keys_remove < len(pool)):
                raise ValueError("unknown key index")
            pool.pop(groq_keys_remove)
            updates["KTQ_GROQ_KEYS"] = ",".join(pool)
        if groq_keys_order is not None:
            if sorted(groq_keys_order) != list(range(len(pool))):
                raise ValueError("key order must list every current index once")
            pool = [pool[i] for i in groq_keys_order]
            updates["KTQ_GROQ_KEYS"] = ",".join(pool)
        new_key = (groq_keys_add or "").strip()
        if new_key:
            if not validate_groq_key(new_key):
                raise ValueError("key rejected by Groq — not saved")
            if new_key not in pool:
                pool.append(new_key)
            updates["KTQ_GROQ_KEYS"] = ",".join(pool)
            updates["KTQ_LLM_URL"] = GROQ_URL
            updates["KTQ_LLM_MODEL"] = GROQ_MODEL
        if "KTQ_GROQ_KEYS" in updates:
            # the merged pool is now the single source of truth — clear the
            # legacy single-key slot so a removed/reordered key can't come
            # back as a ghost on the next read.
            updates["KTQ_LLM_KEY"] = ""
        _write_env_values(updates)
    for key, value in updates.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
    return provider_settings()
