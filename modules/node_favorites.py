"""Admin NodeDB favorites: persistent set of node numbers (data/node_favorites.json)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any, Iterable, List, Set

from modules.log import logger
from modules.paths import ensure_parent_dir, path_in_repo

FAVORITES_PATH = "data/node_favorites.json"

_lock = threading.Lock()
_favorites: Set[int] = set()
_loaded = False


def _path() -> str:
    return path_in_repo(FAVORITES_PATH)


def _coerce(values: Iterable[Any]) -> Set[int]:
    out: Set[int] = set()
    for v in values:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.add(n)
    return out


def _load_locked() -> None:
    global _favorites, _loaded
    _loaded = True
    try:
        with open(_path(), encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            _favorites = set()
            return
        data = json.loads(text)
    except FileNotFoundError:
        _favorites = set()
        return
    except Exception as exc:
        logger.error(f"NodeFavorites: load error: {exc}")
        _favorites = set()
        return
    raw = data.get("favorites") if isinstance(data, dict) else data
    _favorites = _coerce(raw) if isinstance(raw, list) else set()


def _save_locked() -> bool:
    path = _path()
    tmp_path = ""
    try:
        ensure_parent_dir(path)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".node_favorites.", suffix=".tmp", dir=os.path.dirname(path) or "."
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"favorites": sorted(_favorites)}, f)
        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        logger.error(f"NodeFavorites: save error: {exc}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def list_favorites() -> List[int]:
    with _lock:
        if not _loaded:
            _load_locked()
        return sorted(_favorites)


def favorites_set() -> Set[int]:
    with _lock:
        if not _loaded:
            _load_locked()
        return set(_favorites)


def is_favorite(node_num: int) -> bool:
    with _lock:
        if not _loaded:
            _load_locked()
        return int(node_num) in _favorites


def set_favorite(node_num: int, value: bool) -> bool:
    """Set favorite state and persist. Returns False if the node number is invalid or saving failed."""
    try:
        num = int(node_num)
    except (TypeError, ValueError):
        return False
    if num <= 0:
        return False
    with _lock:
        if not _loaded:
            _load_locked()
        before = set(_favorites)
        if value:
            _favorites.add(num)
        else:
            _favorites.discard(num)
        if _favorites == before:
            return True
        if _save_locked():
            return True
        _favorites.clear()
        _favorites.update(before)
        return False


def reset_for_tests() -> None:
    global _favorites, _loaded
    with _lock:
        _favorites = set()
        _loaded = False
