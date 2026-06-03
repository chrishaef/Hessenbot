#!/usr/bin/env python3
"""Live mesh message feed and send helpers for the web admin."""

from __future__ import annotations

import hashlib
import html
import os
import re
import threading
import glob
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from modules.web_dashboard import (
    _NodeDirectory,
    _parse_ts_from_log_line,
    _strip_ansi,
    _tail_lines,
)

_RING: deque = deque(maxlen=300)
_RING_LOCK = threading.Lock()
_SEND_LOCK = threading.Lock()

_SEND_DM_TEXT_RE = re.compile(r"Sending DM:\s*(.+?)\s+To:")
_RECV_DM_TEXT_RE = re.compile(r"(?:Received|Ignoring) DM:\s*(.+?)\s+From:")
_RECV_DM_MISSING_BANG_RE = re.compile(r"Received DM \(missing !\):\s*(.+?)\s+From:")

MESHBOT_TAIL_IN = 12000
MESHBOT_TAIL_OUT_SCAN = 30000
MESHBOT_TAIL_DM_IN = 15000
MSGLOG_TAIL_DEFAULT = 2000
MSGLOG_TAIL_DM_SCAN = 6000
FEED_LIMIT_DEFAULT = 150
FEED_LIMIT_MAX = 250
# meshbot ReceivedChannel vs messages.log for the same packet can differ by seconds
_INCOMING_CHANNEL_DEDUP_SEC = 15


def _message_key(event: Dict[str, Any]) -> str:
    raw = "|".join(
        str(event.get(k, ""))
        for k in ("time", "dir", "kind", "channel", "id", "text", "device")
    )
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def record_optimistic(event: Dict[str, Any]) -> None:
    """Append a just-sent message so the UI updates before the log line appears."""
    event = dict(event)
    event.setdefault("mid", _message_key(event))
    event.setdefault("source", "web")
    with _RING_LOCK:
        _RING.append(event)


def _parse_ts(line: str) -> Optional[datetime]:
    return _parse_ts_from_log_line(line)


def _normalize_incoming_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    return re.sub(r"^[\w.*-]+\s*\|\s*", "", t)


def _peer_name_key(entry: Dict[str, Any]) -> str:
    for field in ("long", "short"):
        value = (entry.get(field) or "").strip().lower()
        if value:
            return value
    return ""


def _incoming_time_bucket(iso_time: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_time)
        return str(int(dt.timestamp()) // _INCOMING_CHANNEL_DEDUP_SEC)
    except (TypeError, ValueError):
        return (iso_time or "")[:19]


def _incoming_channel_fingerprint(ev: Dict[str, Any]) -> Optional[str]:
    if ev.get("kind") != "channel" or ev.get("dir") != "in":
        return None
    text = _normalize_incoming_text(ev.get("text", ""))
    if not text:
        return None
    return "|".join(
        (
            _incoming_time_bucket(ev.get("time", "")),
            str(ev.get("channel", "")),
            str(ev.get("device", "")),
            _peer_name_key(ev),
            text,
        )
    )


def _message_sort_key(entry: Dict[str, Any]) -> Tuple[str, int, str]:
    """Chronological order; at equal time show incoming before bot replies."""
    dir_rank = 0 if entry.get("dir") == "in" else 1
    return (entry.get("time", ""), dir_rank, entry.get("mid", ""))


def _line_is_meshbot_dm(plain: str) -> bool:
    return (
        "Sending DM:" in plain
        or "Received DM" in plain
        or "Ignoring DM:" in plain
    )


def _line_is_meshbot_out(plain: str) -> bool:
    return (
        "Sending DM:" in plain
        or "SendingChannel:" in plain
        or "Sending Multi-Chunk Message:" in plain
        or "Sending Multi-Chunk DM:" in plain
    )


def _channel_index(entry: Dict[str, Any]) -> Optional[int]:
    ch = entry.get("channel")
    if ch is None:
        return None
    try:
        return int(ch)
    except (TypeError, ValueError):
        return None


def _matches_channel_filter(entry: Dict[str, Any], channel: int) -> bool:
    idx = _channel_index(entry)
    return idx is not None and idx == int(channel)


def dm_peer_id(entry: Dict[str, Any]) -> str:
    """Stable key for grouping a DM thread (numeric id, hex, or name fallback)."""
    pid = entry.get("id")
    if pid not in (None, ""):
        return str(pid)
    hex_id = (entry.get("hex") or "").strip()
    if hex_id:
        return hex_id.lower()
    long_n = (entry.get("long") or "").strip().lower()
    if long_n:
        return "n:" + long_n
    short = (entry.get("short") or "").strip().lower()
    if short:
        return "n:" + short
    return ""


def _trim_feed(merged: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Keep the newest ``limit`` rows but never drop bot replies in that window."""
    if limit <= 0 or len(merged) <= limit:
        return merged
    tail = merged[-limit:]
    floor_time = tail[0].get("time", "")
    seen = {m.get("mid") for m in tail if m.get("mid")}
    extra = [
        m
        for m in merged
        if m.get("dir") == "out"
        and m.get("source") == "bot"
        and m.get("time", "") >= floor_time
        and m.get("mid") not in seen
    ]
    if not extra:
        return tail
    combined = sorted(tail + extra, key=_message_sort_key)
    return combined


def _bot_event(extra: Dict[str, Any]) -> Dict[str, Any]:
    ev = dict(extra)
    ev.setdefault("source", "bot")
    return ev


def _parse_meshbot_line(
    plain: str, timestamp: datetime, nodes: _NodeDirectory
) -> Optional[Dict[str, Any]]:
    from modules.web_dashboard import _parse_channel_from_log

    dev_m = re.search(r"Device:(\d+)", plain)
    device = int(dev_m.group(1)) if dev_m else 1
    channel, channel_label = _parse_channel_from_log(plain, device)
    base: Dict[str, Any] = {
        "time": timestamp.isoformat(),
        "time_short": timestamp.strftime("%H:%M:%S"),
        "device": device,
        "channel": channel,
        "channel_label": channel_label,
        "text": "",
    }

    ns = re.search(r"NodeID:(\d+)\s+ShortName:(\S+)", plain)
    if ns:
        nodes.register(int(ns.group(1)), short=ns.group(2))

    if "Sending DM:" in plain or "Sending Multi-Chunk DM:" in plain:
        to_m = re.search(r"\sTo:\s*(.+?)$", plain)
        to_label = to_m.group(1).strip() if to_m else ""
        peer = nodes.resolve(to_label) if to_label else {}
        text_m = _SEND_DM_TEXT_RE.search(plain)
        text = text_m.group(1).strip() if text_m else ""
        return _bot_event({**base, "dir": "out", "kind": "dm", "text": text, **peer})

    if "SendingChannel:" in plain or "Sending Multi-Chunk Message:" in plain:
        text_m = re.search(
            r"Sending(?: Multi-Chunk)?(?: Message)?:\s*(.+?)(?:\s+Chunker|\s*$)",
            plain,
        )
        if not text_m:
            text_m = re.search(r"SendingChannel:\s*(.+)$", plain)
        text = text_m.group(1).strip() if text_m else ""
        return _bot_event({
            **base,
            "dir": "out",
            "kind": "channel",
            "text": text,
            "id": "",
            "hex": "",
            "short": "",
            "long": "",
        })

    if "Received DM (missing !):" in plain:
        from_m = re.search(r"From:\s*(.+?)$", plain)
        from_label = from_m.group(1).strip() if from_m else ""
        peer = nodes.resolve(from_label) if from_label else {}
        text_m = _RECV_DM_MISSING_BANG_RE.search(plain)
        text = text_m.group(1).strip() if text_m else ""
        return _bot_event({**base, "dir": "in", "kind": "dm", "text": text, **peer})

    if "Received DM:" in plain or "Ignoring DM:" in plain:
        from_m = re.search(r"From:\s*(.+?)$", plain)
        from_label = from_m.group(1).strip() if from_m else ""
        peer = nodes.resolve(from_label) if from_label else {}
        text_m = _RECV_DM_TEXT_RE.search(plain)
        text = text_m.group(1).strip() if text_m else ""
        return _bot_event({**base, "dir": "in", "kind": "dm", "text": text, **peer})

    if "ReceivedChannel:" in plain or "Ignoring Message:" in plain:
        from_m = re.search(r"From:\s*(.+?)$", plain)
        peer = nodes.resolve(from_m.group(1)) if from_m else {}
        if "ReceivedChannel:" in plain:
            text_m = re.search(r"ReceivedChannel:\s*(.+?)\s+From:", plain)
        else:
            text_m = re.search(r"Ignoring Message:\s*(.+?)\s+From:", plain)
        text = text_m.group(1).strip() if text_m else ""
        return _bot_event({**base, "dir": "in", "kind": "channel", "text": text, **peer})

    return None


def _merge_events(
    meshbot_events: List[Dict[str, Any]],
    msg_log_events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prefer messages.log text for incoming when timestamps align."""
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    semantic_seen: Dict[str, str] = {}

    def _enrich(existing: Dict[str, Any], ev: Dict[str, Any]) -> None:
        if not existing.get("text") and ev.get("text"):
            existing["text"] = ev["text"]
        for field in ("short", "long", "hex", "id", "channel_label"):
            if not existing.get(field) and ev.get(field):
                existing[field] = ev[field]

    def add(ev: Dict[str, Any]) -> None:
        fp = _incoming_channel_fingerprint(ev)
        if fp and fp in semantic_seen:
            _enrich(by_key[semantic_seen[fp]], ev)
            return

        base_key = _message_key(ev)
        key = base_key
        suffix = 0
        while key in by_key:
            existing = by_key[key]
            if not existing.get("text") and ev.get("text"):
                _enrich(existing, ev)
                return
            suffix += 1
            key = f"{base_key}:{suffix}"
        ev = dict(ev)
        ev["mid"] = key
        by_key[key] = ev
        order.append(key)
        if fp:
            semantic_seen[fp] = key

    for ev in meshbot_events:
        add(ev)
    for ev in msg_log_events:
        add(ev)

    with _RING_LOCK:
        for ev in _RING:
            add(ev)

    return [by_key[k] for k in order]


def _resolve_rotated_log_paths(
    log_dir: str, basename: str, *, max_backups: int = 1
) -> List[str]:
    """Current log plus the most recent rotated backup (midnight rotation)."""
    base = os.path.realpath(log_dir)
    paths: List[str] = []
    primary = os.path.join(base, basename)
    if os.path.isfile(primary):
        paths.append(primary)
    backups = sorted(
        (p for p in glob.glob(os.path.join(base, f"{basename}.*")) if os.path.isfile(p)),
        key=os.path.getmtime,
        reverse=True,
    )
    for path in backups[:max_backups]:
        if path not in paths:
            paths.append(path)
    return paths


def _tail_merged_log_paths(paths: List[str], max_lines: int) -> List[str]:
    """Tail lines from rotated logs in chronological order (oldest file first)."""
    if not paths:
        return []
    if len(paths) == 1:
        return _tail_lines(paths[0], max_lines)
    per_file = max(max_lines // len(paths), 400)
    merged: List[str] = []
    for path in reversed(paths):
        merged.extend(_tail_lines(path, per_file))
    if len(merged) > max_lines:
        merged = merged[-max_lines:]
    return merged


def _parse_meshbot_tail(
    log_dir: str,
    nodes: _NodeDirectory,
    *,
    in_scan_lines: int = MESHBOT_TAIL_IN,
    out_scan_lines: int = MESHBOT_TAIL_OUT_SCAN,
    dm_in_only: bool = False,
) -> List[Dict[str, Any]]:
    """Parse meshbot.log in chronological log order (not outbound-first)."""
    events: List[Dict[str, Any]] = []
    seen: set = set()
    paths = _resolve_rotated_log_paths(log_dir, "meshbot.log")
    scan_lines = max(in_scan_lines, out_scan_lines)
    deep = _tail_merged_log_paths(paths, scan_lines)

    for line in deep:
        plain = _strip_ansi(line)
        if dm_in_only and not _line_is_meshbot_dm(plain):
            continue
        ts = _parse_ts(line)
        if not ts:
            continue
        ev = _parse_meshbot_line(plain, ts, nodes)
        if not ev:
            continue
        key = _message_key(ev)
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)

    return events


def _parse_messages_logs_tail(
    log_dir: str,
    nodes: _NodeDirectory,
    *,
    max_lines: int = MSGLOG_TAIL_DEFAULT,
    dm_only: bool = False,
    channel: Optional[int] = None,
) -> List[Dict[str, Any]]:
    from modules.web_dashboard import _parse_messages_log_lines

    paths = _resolve_rotated_log_paths(log_dir, "messages.log")
    if not paths:
        return []
    lines = _tail_merged_log_paths(paths, max_lines)
    if dm_only:
        lines = [ln for ln in lines if " DM |" in ln]
    elif channel is not None:
        ch = int(channel)
        pat = re.compile(rf"Channel:{ch}(?:\||\s)")
        lines = [ln for ln in lines if pat.search(ln)]
    return _parse_messages_log_lines(lines, nodes)


def collect_messages(
    log_dir: str,
    *,
    kind: Optional[str] = None,
    channel: Optional[int] = None,
    limit: int = 100,
    after_iso: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Return recent mesh messages from meshbot.log (+ messages.log when enabled).
    kind: 'channel' | 'dm' | None (all)
    """
    meshbot_path = os.path.join(os.path.realpath(log_dir), "meshbot.log")

    nodes = _NodeDirectory()
    dm_mode = kind == "dm"
    channel_mode = kind == "channel"
    meshbot_events = _parse_meshbot_tail(
        log_dir,
        nodes,
        in_scan_lines=MESHBOT_TAIL_DM_IN if dm_mode else MESHBOT_TAIL_IN,
        out_scan_lines=MESHBOT_TAIL_OUT_SCAN,
        dm_in_only=dm_mode,
    )
    msg_log_events = _parse_messages_logs_tail(
        log_dir,
        nodes,
        max_lines=MSGLOG_TAIL_DM_SCAN if dm_mode else MSGLOG_TAIL_DEFAULT,
        dm_only=dm_mode,
        channel=channel if channel_mode else None,
    )

    merged = _merge_events(meshbot_events, msg_log_events)

    if after_iso:
        merged = [m for m in merged if m.get("time", "") > after_iso]

    if kind:
        merged = [m for m in merged if m.get("kind") == kind]

    if channel is not None and kind == "channel":
        merged = [m for m in merged if _matches_channel_filter(m, channel)]

    merged.sort(key=_message_sort_key)
    merged = _trim_feed(merged, limit)

    err = None
    if not os.path.isfile(meshbot_path):
        err = "meshbot.log nicht gefunden — SyslogToFile in config.ini aktivieren."

    return merged, err


def default_mesh_channel() -> int:
    import modules.settings as st

    return int(getattr(st, "messages_channel", 1))


def default_mesh_interface() -> int:
    from modules import admin_web_ops as ops

    ifaces = ops.iter_radio_interfaces()
    return ifaces[0] if ifaces else 1


def list_send_targets(iface_id: int) -> Tuple[Optional[str], List[Dict[str, str]]]:
    from modules import admin_web_ops as ops

    err, rows = ops.list_node_rows(iface_id)
    if err:
        return err, []
    out = []
    for r in rows:
        if r.get("is_self"):
            continue
        short = html.unescape(str(r.get("shortName") or "")).strip()
        long_n = html.unescape(str(r.get("longName") or "")).strip()
        node_id = html.unescape(str(r.get("node_id") or "")).strip()
        num = str(r["num"])
        label = f"{short or '?'} · {long_n or '?'}"
        search = " ".join(
            p.lower()
            for p in (short, long_n, num, node_id, label)
            if p
        )
        out.append(
            {
                "num": num,
                "node_id": node_id,
                "short": short,
                "long": long_n,
                "label": label,
                "search": search,
            }
        )
    out.sort(key=lambda x: x["label"].lower())
    return None, out


def send_mesh_message(
    text: str,
    *,
    channel: int,
    interface: int,
    dest_node: int = 0,
) -> Tuple[bool, str]:
    text = (text or "").strip()
    if not text:
        return False, "Nachricht ist leer."
    if len(text) > 500:
        return False, "Maximal 500 Zeichen."

    from modules import admin_web_ops as ops

    ifaces = ops.iter_radio_interfaces()
    if interface not in ifaces:
        return False, f"Interface {interface} ist nicht verbunden."

    import modules.system as sm

    if dest_node:
        try:
            dest_node = int(dest_node)
        except (TypeError, ValueError):
            return False, "Ungültige Ziel-Node-ID."

    with _SEND_LOCK:
        ok = sm.send_message(text, channel, dest_node, interface)

    if ok:
        kind = "dm" if dest_node else "channel"
        from modules.system import format_channel_label

        ch_label = format_channel_label(channel, interface) if not dest_node else "DM"
        record_optimistic(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "time_short": datetime.now().strftime("%H:%M:%S"),
                "dir": "out",
                "kind": kind,
                "channel": channel,
                "channel_label": ch_label,
                "device": interface,
                "text": text,
                "id": str(dest_node) if dest_node else "",
                "short": "Web-Admin",
                "long": "Hessenbot Web-Admin",
            }
        )
        return True, "Nachricht gesendet."
    return False, "Senden fehlgeschlagen — siehe meshbot.log."


def peer_label(entry: Dict[str, Any]) -> str:
    short = entry.get("short") or ""
    long_name = entry.get("long") or ""
    hex_id = entry.get("hex") or ""
    node_id = entry.get("id") or ""
    if entry.get("dir") == "out" and entry.get("short") == "Web-Admin":
        return "Web-Admin"
    if short and long_name:
        return f"{short} · {long_name}"
    if long_name:
        return long_name
    if hex_id:
        return hex_id
    if node_id:
        return f"#{node_id}"
    if entry.get("kind") == "channel" and entry.get("dir") == "out":
        return entry.get("channel_label") or "Kanal"
    return "?"
