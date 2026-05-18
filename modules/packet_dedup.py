# Deduplicate mesh packets seen on multiple transports (e.g. MQTT + UDP from meshtasticd).
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from modules.log import logger

_lock = threading.Lock()
_seen: OrderedDict[str, float] = OrderedDict()
_stats = {"dropped": 0, "accepted": 0}


def _payload_bytes(decoded: Dict[str, Any]) -> bytes:
    payload = decoded.get("payload")
    if payload is None:
        text = decoded.get("text")
        if text is not None:
            return str(text).encode("utf-8", errors="replace")
        return b""
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    return str(payload).encode("utf-8", errors="replace")


def packet_dedup_key(packet: Dict[str, Any]) -> str:
    """Stable key for the same logical packet on MQTT, UDP, or TCP."""
    from_id = packet.get("from")
    pkt_id = packet.get("id")
    if from_id is not None and pkt_id is not None:
        return f"id:{from_id}:{pkt_id}"

    decoded = packet.get("decoded") if isinstance(packet.get("decoded"), dict) else {}
    port = decoded.get("portnum", "")
    to_id = packet.get("to", 0)
    channel = packet.get("channel", "")
    rx_time = decoded.get("rxTime") or packet.get("rxTime")
    pl = _payload_bytes(decoded)
    digest = hashlib.sha256(pl).hexdigest()[:20]
    return f"body:{from_id}:{to_id}:{channel}:{port}:{rx_time}:{digest}"


def _settings():
    import modules.settings as st

    return (
        getattr(st, "packet_dedup_enabled", True),
        max(30, int(getattr(st, "packet_dedup_ttl_seconds", 300))),
        max(256, int(getattr(st, "packet_dedup_max_entries", 8192))),
    )


def _prune(now: float, ttl: float, max_entries: int) -> None:
    cutoff = now - ttl
    while _seen:
        key, ts = next(iter(_seen.items()))
        if ts >= cutoff and len(_seen) <= max_entries:
            break
        _seen.popitem(last=False)
    while len(_seen) > max_entries:
        _seen.popitem(last=False)


def should_drop_duplicate_packet(packet: Dict[str, Any]) -> bool:
    """
    Return True if this packet was already processed recently (drop it).
    Call after unwrap_sim_tunnel_packet() so MQTT/UDP share the same key.
    """
    enabled, ttl, max_entries = _settings()
    if not enabled:
        return False

    try:
        key = packet_dedup_key(packet)
    except Exception as e:
        logger.debug(f"System: packet dedup key failed ({e!s}); processing packet")
        return False

    now = time.time()
    with _lock:
        if key in _seen:
            _seen.move_to_end(key)
            _stats["dropped"] += 1
            logger.debug(f"System: Dropping duplicate packet ({key})")
            return True
        _seen[key] = now
        _seen.move_to_end(key)
        _prune(now, ttl, max_entries)
        _stats["accepted"] += 1
    return False


def dedup_stats() -> Dict[str, int]:
    with _lock:
        return dict(_stats, cache_size=len(_seen))
