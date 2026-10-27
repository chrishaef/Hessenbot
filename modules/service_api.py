#!/usr/bin/env python3
"""Service-API für externe Dienste (DM-Versand / whoami).

Token wird als SHA-256-Hash in config.ini gespeichert; Klartext nur einmal
nach dem Generieren im Admin-UI. Optionaler Env-Override HESSENBOT_API_TOKEN
(Klartext) hat Vorrang. Request-Audit in Speicher + logs/service_api.log.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from modules.paths import path_in_repo

_TOKEN_BYTES = 32
_LOG_MEMORY = 200
_MAX_TEXT_LEN = 500

_lock = threading.RLock()
_enabled: bool = False
_token_hash: str = ""
_env_token: str = ""
_log_path: str = ""
_log_buf: Deque[Dict[str, Any]] = deque(maxlen=_LOG_MEMORY)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _safe_compare(a: str, b: str) -> bool:
    """Timing-sicher; bei unterschiedlicher Länge False (kein ValueError unter Py&lt;3.12)."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    if len(a) != len(b):
        return False
    try:
        return hmac.compare_digest(a, b)
    except (TypeError, ValueError):
        return False


def configure(
    *,
    enabled: bool,
    token_hash: str = "",
    env_token: str = "",
    log_dir: Optional[str] = None,
) -> None:
    """Runtime-State aus Settings / Start setzen."""
    global _enabled, _token_hash, _env_token, _log_path
    with _lock:
        _enabled = bool(enabled)
        _token_hash = (token_hash or "").strip().lower()
        _env_token = (env_token or "").strip()
        base = path_in_repo(log_dir) if log_dir else path_in_repo("logs")
        os.makedirs(base, exist_ok=True)
        _log_path = os.path.join(base, "service_api.log")


def is_enabled() -> bool:
    with _lock:
        return _enabled


def has_credential() -> bool:
    with _lock:
        return bool(_env_token) or bool(_token_hash)


def is_active() -> bool:
    """API antwortet nur, wenn eingeschaltet und ein Token (Hash oder Env) existiert."""
    with _lock:
        return _enabled and (bool(_env_token) or bool(_token_hash))


def token_source() -> str:
    with _lock:
        if _env_token:
            return "env"
        if _token_hash:
            return "config"
        return "none"


def status_snapshot() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled,
            "active": _enabled and (bool(_env_token) or bool(_token_hash)),
            "has_token": bool(_env_token) or bool(_token_hash),
            "token_source": token_source(),
            "token_fingerprint": (_token_hash[:8] if _token_hash else ""),
            "env_override": bool(_env_token),
            "max_text_len": _MAX_TEXT_LEN,
            "rate_limit": "30 per minute",
        }


def extract_bearer_or_header(authorization: str, x_api_token: str) -> str:
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (x_api_token or "").strip()


def verify_token(supplied: str) -> bool:
    supplied = (supplied or "").strip()
    if not supplied:
        return False
    with _lock:
        if not _enabled:
            return False
        if _env_token:
            return _safe_compare(supplied, _env_token)
        if not _token_hash:
            return False
        return _safe_compare(hash_token(supplied), _token_hash)


def auth_error_payload() -> Tuple[Dict[str, Any], int]:
    """JSON-Body + HTTP-Status für fehlgeschlagene Auth."""
    with _lock:
        if not _enabled or (not _env_token and not _token_hash):
            return {"ok": False, "error": "api_disabled"}, 503
        return {"ok": False, "error": "unauthorized"}, 401


def generate_token() -> str:
    """Neuen Token erzeugen, Hash speichern (Config + Runtime), Klartext zurückgeben."""
    plain = secrets.token_urlsafe(_TOKEN_BYTES)
    digest = hash_token(plain)
    with _lock:
        global _token_hash
        _token_hash = digest
    _persist_config(token_hash=digest, clear_plaintext=True)
    return plain


def revoke_token() -> None:
    with _lock:
        global _token_hash
        _token_hash = ""
    _persist_config(token_hash="", clear_plaintext=True)


def set_enabled(enabled: bool) -> None:
    with _lock:
        global _enabled
        _enabled = bool(enabled)
    _persist_config(enabled=bool(enabled))


def max_text_len() -> int:
    return _MAX_TEXT_LEN


def _persist_config(
    *,
    enabled: Optional[bool] = None,
    token_hash: Optional[str] = None,
    clear_plaintext: bool = False,
) -> None:
    try:
        import modules.settings as st
    except Exception:
        return
    if "webAdmin" not in st.config:
        return
    changed = False
    if enabled is not None:
        st.config["webAdmin"]["api_enabled"] = "True" if enabled else "False"
        st.web_admin_api_enabled = bool(enabled)
        changed = True
    if token_hash is not None:
        st.config["webAdmin"]["api_token_hash"] = token_hash
        st.web_admin_api_token_hash = token_hash
        changed = True
    if clear_plaintext and st.config["webAdmin"].get("api_token"):
        st.config["webAdmin"]["api_token"] = ""
        if hasattr(st, "web_admin_api_token"):
            st.web_admin_api_token = ""
        changed = True
    if not changed:
        return
    try:
        with open(st.config_file, "w", encoding="utf-8") as fh:
            st.config.write(fh)
    except OSError:
        pass


def log_request(
    *,
    endpoint: str,
    method: str,
    status: int,
    client_ip: str = "",
    error: str = "",
    dest_node_id: str = "",
    detail: str = "",
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "method": method,
        "endpoint": endpoint,
        "status": int(status),
        "ip": (client_ip or "")[:64],
        "error": (error or "")[:80],
        "dest": (dest_node_id or "")[:32],
        "detail": (detail or "")[:120],
    }
    with _lock:
        _log_buf.appendleft(entry)
        path = _log_path
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def recent_logs(limit: int = 100) -> List[Dict[str, Any]]:
    n = max(1, min(int(limit), _LOG_MEMORY))
    with _lock:
        return list(_log_buf)[:n]


def clear_memory_logs() -> int:
    with _lock:
        n = len(_log_buf)
        _log_buf.clear()
        return n


def migrate_plaintext_token_if_needed(config) -> bool:
    """Einmalig: Klartext api_token → api_token_hash, Klartext leeren. True wenn geschrieben."""
    if "webAdmin" not in config:
        return False
    wa = config["webAdmin"]
    plain = (wa.get("api_token") or "").strip()
    existing_hash = (wa.get("api_token_hash") or "").strip()
    changed = False
    if "api_enabled" not in wa:
        # Legacy: Token gesetzt = war „an“; sonst aus
        wa["api_enabled"] = "True" if (plain or existing_hash) else "False"
        changed = True
    if "api_token_hash" not in wa:
        wa["api_token_hash"] = ""
        changed = True
    if plain and not existing_hash:
        wa["api_token_hash"] = hash_token(plain)
        wa["api_token"] = ""
        changed = True
    return changed
