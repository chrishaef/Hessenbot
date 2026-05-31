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
_enrichment: Dict[str, Dict[str, Any]] = {}
_stats = {"dropped": 0, "accepted": 0}


def _decoded(packet: Dict[str, Any]) -> Dict[str, Any]:
    d = packet.get("decoded")
    return d if isinstance(d, dict) else {}


def _transport_mechanism(packet: Dict[str, Any]) -> str:
    decoded = _decoded(packet)
    return str(
        packet.get("transport_mechanism")
        or packet.get("transportMechanism")
        or decoded.get("transport_mechanism")
        or decoded.get("transportMechanism")
        or ""
    ).lower()


def _extract_hop_fields(packet: Dict[str, Any]) -> Dict[str, Any]:
    decoded = _decoded(packet)
    return {
        "hopsAway": packet.get("hopsAway"),
        "hopStart": packet.get("hopStart"),
        "hopLimit": packet.get("hopLimit"),
        "rxSnr": packet.get("rxSnr"),
        "rxRssi": packet.get("rxRssi"),
        "transport_mechanism": _transport_mechanism(packet),
        "viaMqtt": decoded.get("viaMqtt"),
    }


def _hop_metadata_score(packet: Dict[str, Any] | Dict[str, Any]) -> int:
    """Higher = richer routing metadata (prefer UDP/LoRa copy over bare MQTT)."""
    if isinstance(packet, dict) and "hopStart" in packet and "hopLimit" in packet and "hopsAway" in packet:
        fields = packet
    else:
        fields = _extract_hop_fields(packet)  # type: ignore[arg-type]

    score = 0
    hs = fields.get("hopStart")
    hl = fields.get("hopLimit")
    try:
        if hs is not None and hl is not None and int(hl) > 0 and int(hs) > int(hl):
            score += 1000 + (int(hs) - int(hl))
    except (TypeError, ValueError):
        pass
    try:
        ha = int(fields.get("hopsAway") or 0)
        if ha > 0:
            score += 100 + ha
    except (TypeError, ValueError):
        pass
    if fields.get("rxSnr") or fields.get("rxRssi"):
        score += 10
    tm = str(fields.get("transport_mechanism") or "").lower()
    if "udp" in tm or "lora" in tm:
        score += 5
    return score


def apply_hop_enrichment(packet: Dict[str, Any]) -> None:
    """
    Merge hop/rx metadata from a duplicate transport (e.g. UDP after MQTT).
    Call before reading hop fields in onReceive.
    """
    try:
        key = packet_dedup_key(packet)
    except Exception:
        return

    with _lock:
        extra = _enrichment.pop(key, None)
    if not extra:
        return
    if _hop_metadata_score(extra) <= _hop_metadata_score(packet):
        return

    for field, pkey in (
        ("hopsAway", "hopsAway"),
        ("hopStart", "hopStart"),
        ("hopLimit", "hopLimit"),
        ("rxSnr", "rxSnr"),
        ("rxRssi", "rxRssi"),
    ):
        val = extra.get(field)
        if val is not None:
            packet[pkey] = val
    tm = extra.get("transport_mechanism")
    if tm:
        packet["transport_mechanism"] = tm
    if extra.get("viaMqtt") is not None:
        decoded = packet.setdefault("decoded", {})
        if isinstance(decoded, dict):
            decoded["viaMqtt"] = extra["viaMqtt"]


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
            fields = _extract_hop_fields(packet)
            prev = _enrichment.get(key)
            if prev is None or _hop_metadata_score(fields) > _hop_metadata_score(prev):
                _enrichment[key] = fields
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
