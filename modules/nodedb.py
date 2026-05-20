"""
Persistent node registry for Hessenbot.

Stores longName, shortName, publicKey (PKI) and last-seen timestamp per node.
Survives bot restarts and interface reconnects.

Cleanup policy: only drop entries older than NODE_DB_MAX_AGE_DAYS when the
total number of entries exceeds NODE_DB_MIN_SIZE (1000).
"""

import base64
import json
import time

from modules.log import logger
from modules.paths import ensure_parent_dir, path_in_repo

NODE_DB_PATH = "data/nodedb.json"
NODE_DB_MIN_SIZE = 1000
NODE_DB_MAX_AGE_DAYS = 60

_nodedb: dict = {}      # str(node_id_int) -> entry dict
_dirty: bool = False    # needs save


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _path() -> str:
    return path_in_repo(NODE_DB_PATH)


def _to_str(value) -> str:
    """Normalise publicKey to a printable string (base64 if bytes)."""
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode("ascii")
    return str(value) if value is not None else ""


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------

def load_nodedb() -> None:
    global _nodedb
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _nodedb = data
            logger.debug(f"NodeDB: loaded {len(_nodedb)} entries from {_path()}")
        else:
            _nodedb = {}
    except FileNotFoundError:
        _nodedb = {}
        logger.debug("NodeDB: no file yet, starting fresh")
    except Exception as exc:
        logger.error(f"NodeDB: load error: {exc}")
        _nodedb = {}


def save_nodedb() -> bool:
    global _dirty
    if not _dirty:
        return True
    try:
        path = _path()
        ensure_parent_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_nodedb, f, ensure_ascii=False)
        _dirty = False
        logger.debug(f"NodeDB: saved {len(_nodedb)} entries")
        return True
    except Exception as exc:
        logger.error(f"NodeDB: save error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Update / Query
# ---------------------------------------------------------------------------

def update_node(node_id: int, *,
                long_name: str = None,
                short_name: str = None,
                public_key=None) -> None:
    """Create or refresh a node entry.  Only supplied kwargs are written."""
    global _dirty
    key = str(int(node_id))
    now = time.time()
    entry = _nodedb.setdefault(key, {"firstSeen": now})
    entry["lastSeen"] = now

    if long_name is not None:
        entry["longName"] = long_name
    if short_name is not None:
        entry["shortName"] = short_name
    if public_key is not None:
        pk_str = _to_str(public_key)
        if pk_str and entry.get("publicKey") != pk_str:
            entry["publicKey"] = pk_str
            logger.debug(f"NodeDB: PKI key stored/updated for node {key}")
    _dirty = True


def get_node_long_name(node_id: int) -> str:
    return _nodedb.get(str(int(node_id)), {}).get("longName", "")


def get_node_short_name(node_id: int) -> str:
    return _nodedb.get(str(int(node_id)), {}).get("shortName", "")


def get_node_pubkey(node_id: int) -> str:
    """Return cached public key string, or '' if unknown."""
    return _nodedb.get(str(int(node_id)), {}).get("publicKey", "")


def get_node(node_id: int) -> dict:
    return dict(_nodedb.get(str(int(node_id)), {}))


# ---------------------------------------------------------------------------
# Bulk populate from a live Meshtastic interface
# ---------------------------------------------------------------------------

def populate_from_interface(interface) -> int:
    """Walk interface.nodes and populate the DB.  Returns number of new/updated entries."""
    if interface is None:
        return 0
    nodes = getattr(interface, "nodes", None)
    if not nodes:
        return 0
    count = 0
    for node in nodes.values():
        try:
            nid = node.get("num")
            if not nid:
                continue
            user = node.get("user") or {}
            update_node(
                nid,
                long_name=user.get("longName") or None,
                short_name=user.get("shortName") or None,
                public_key=user.get("publicKey") or None,
            )
            count += 1
        except Exception as exc:
            logger.debug(f"NodeDB: populate_from_interface entry error: {exc}")
    if count:
        logger.debug(f"NodeDB: populated {count} entries from interface")
    return count


# ---------------------------------------------------------------------------
# TTL Cleanup
# ---------------------------------------------------------------------------

def cleanup_nodedb() -> int:
    """Remove entries older than NODE_DB_MAX_AGE_DAYS, but only if total > NODE_DB_MIN_SIZE."""
    global _dirty
    if len(_nodedb) <= NODE_DB_MIN_SIZE:
        return 0
    cutoff = time.time() - NODE_DB_MAX_AGE_DAYS * 86400
    stale = [k for k, v in _nodedb.items() if v.get("lastSeen", 0) < cutoff]
    if not stale:
        return 0
    for k in stale:
        del _nodedb[k]
    _dirty = True
    logger.info(f"NodeDB: removed {len(stale)} entries older than {NODE_DB_MAX_AGE_DAYS} days "
                f"({len(_nodedb)} remaining)")
    return len(stale)
