"""
Dynamic service health checks for Hessenbot.
Each service is probed at most once per TTL window (default 60 s).
In standalone/slave mode the result drives graceful "offline" responses
instead of blanket feature disabling.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

import requests

from modules.log import logger

_lock = threading.Lock()
_cache: Dict[str, Tuple[bool, float]] = {}
_TTL: int = 60  # seconds; overridden by set_ttl()

# Built-in service URLs — extended at runtime via register_service()
_SERVICE_URLS: Dict[str, str] = {
    "dwd":      "https://www.dwd.de",
    "nina":     "https://nina.api.bund.dev",
    "wx":       "https://api.open-meteo.com",
    "blitz":    "https://data.blitzortung.org",
    "news":     "https://newsapi.org",
    "wiki":     "https://en.wikipedia.org",
    "internet": "https://1.1.1.1",
}

# Maps bot command keyword → service name for automatic guard lookup
COMMAND_SERVICE_MAP: Dict[str, str] = {
    "wx":       "wx",
    "blitz":    "blitz",
    "nina":     "nina",
    "warning":  "nina",
    "wiki":     "wiki",
    "latest":   "news",
    "readnews": "news",
    "metar":    "wx",
    "satpass":  "internet",
    "solar":    "internet",
    "hfcond":   "internet",
    "dx":       "internet",
    "rlist":    "internet",
}


def register_service(name: str, url: str) -> None:
    """Register or update a service URL (e.g. 'master', 'ollama')."""
    with _lock:
        _SERVICE_URLS[name] = url


def unregister_service(name: str) -> None:
    with _lock:
        _SERVICE_URLS.pop(name, None)
        _cache.pop(name, None)


def set_ttl(seconds: int) -> None:
    global _TTL
    _TTL = max(10, seconds)


def _probe(url: str, timeout: int = 4) -> bool:
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


def service_available(name: str, force: bool = False) -> bool:
    """
    Returns True if the named service is reachable.
    Result is cached for _TTL seconds unless force=True.
    """
    with _lock:
        if not force:
            cached = _cache.get(name)
            if cached and time.time() - cached[1] < _TTL:
                return cached[0]
        url = _SERVICE_URLS.get(name)

    if not url:
        logger.debug(f"ServiceHealth: unknown service '{name}'")
        return False

    result = _probe(url)
    with _lock:
        _cache[name] = (result, time.time())

    if not result:
        logger.warning(f"ServiceHealth: '{name}' not reachable ({url})")
    return result


def command_available(cmd: str) -> Optional[bool]:
    """
    Returns None if no service guard exists for cmd (always allow).
    Returns True/False based on the mapped service check.
    """
    svc = COMMAND_SERVICE_MAP.get(cmd)
    if svc is None:
        return None
    return service_available(svc)


def offline_response(service_name: str) -> str:
    """Standard offline message for users."""
    return f"⚠️ {service_name} nicht erreichbar — bitte später erneut versuchen."


def all_status() -> Dict[str, bool]:
    """Current availability of all registered services (uses cache)."""
    with _lock:
        names = list(_SERVICE_URLS.keys())
    return {name: service_available(name) for name in names}


def invalidate(name: Optional[str] = None) -> None:
    """Invalidate cache for one service or all (name=None)."""
    with _lock:
        if name:
            _cache.pop(name, None)
        else:
            _cache.clear()
