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
    _strip_ansi,
    _tail_lines,
)

_RING: deque = deque(maxlen=300)
_RING_LOCK = threading.Lock()
_SEND_LOCK = threading.Lock()

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+")
_SEND_DM_TEXT_RE = re.compile(r"Sending DM:\s*(.+?)\s+To:")
_RECV_DM_TEXT_RE = re.compile(r"(?:Received|Ignoring) DM:\s*(.+?)\s+From:")
_RECV_DM_MISSING_BANG_RE = re.compile(r"Received DM \(missing !\):\s*(.+?)\s+From:")

MESHBOT_TAIL_DEFAULT = 2500
MESHBOT_TAIL_DM_SCAN = 12000
MSGLOG_TAIL_DEFAULT = 1000
MSGLOG_TAIL_DM_SCAN = 4000


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
    with _RING_LOCK:
        _RING.append(event)


def _parse_ts(line: str) -> Optional[datetime]:
    m = _TS_RE.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _line_is_meshbot_dm(plain: str) -> bool:
    return (
        "Sending DM:" in plain
        or "Received DM" in plain
        or "Ignoring DM:" in plain
    )


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
        peer = nodes.resolve(to_m.group(1)) if to_m else {}
        text_m = _SEND_DM_TEXT_RE.search(plain)
        text = text_m.group(1).strip() if text_m else ""
        return {**base, "dir": "out", "kind": "dm", "text": text, **peer}

    if "SendingChannel:" in plain or "Sending Multi-Chunk Message:" in plain:
        text_m = re.search(
            r"Sending(?: Multi-Chunk)?(?: Message)?:\s*(.+?)(?:\s+Chunker|\s*$)",
            plain,
        )
        if not text_m:
            text_m = re.search(r"SendingChannel:\s*(.+)$", plain)
        text = text_m.group(1).strip() if text_m else ""
        return {
            **base,
            "dir": "out",
            "kind": "channel",
            "text": text,
            "id": "",
            "hex": "",
            "short": "",
            "long": "",
        }

    if "Received DM (missing !):" in plain:
        from_m = re.search(r"From:\s*(.+?)$", plain)
        peer = nodes.resolve(from_m.group(1)) if from_m else {}
        text_m = _RECV_DM_MISSING_BANG_RE.search(plain)
        text = text_m.group(1).strip() if text_m else ""
        return {**base, "dir": "in", "kind": "dm", "text": text, **peer}

    if "Received DM:" in plain or "Ignoring DM:" in plain:
        from_m = re.search(r"From:\s*(.+?)$", plain)
        peer = nodes.resolve(from_m.group(1)) if from_m else {}
        text_m = _RECV_DM_TEXT_RE.search(plain)
        text = text_m.group(1).strip() if text_m else ""
        return {**base, "dir": "in", "kind": "dm", "text": text, **peer}

    if "ReceivedChannel:" in plain or "Ignoring Message:" in plain:
        from_m = re.search(r"From:\s*(.+?)$", plain)
        peer = nodes.resolve(from_m.group(1)) if from_m else {}
        if "ReceivedChannel:" in plain:
            text_m = re.search(r"ReceivedChannel:\s*(.+?)\s+From:", plain)
        else:
            text_m = re.search(r"Ignoring Message:\s*(.+?)\s+From:", plain)
        text = text_m.group(1).strip() if text_m else ""
        return {**base, "dir": "in", "kind": "channel", "text": text, **peer}

    return None


def _merge_events(
    meshbot_events: List[Dict[str, Any]],
    msg_log_events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prefer messages.log text for incoming when timestamps align."""
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    def add(ev: Dict[str, Any]) -> None:
        base_key = _message_key(ev)
        key = base_key
        suffix = 0
        while key in by_key:
            existing = by_key[key]
            if not existing.get("text") and ev.get("text"):
                existing["text"] = ev["text"]
                for field in ("short", "long", "hex", "id", "channel_label"):
                    if not existing.get(field) and ev.get(field):
                        existing[field] = ev[field]
                return
            suffix += 1
            key = f"{base_key}:{suffix}"
        ev = dict(ev)
        ev["mid"] = key
        by_key[key] = ev
        order.append(key)

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
    max_lines: int = MESHBOT_TAIL_DEFAULT,
    dm_only: bool = False,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    paths = _resolve_rotated_log_paths(log_dir, "meshbot.log")
    for line in _tail_merged_log_paths(paths, max_lines):
        plain = _strip_ansi(line)
        if dm_only and not _line_is_meshbot_dm(plain):
            continue
        ts = _parse_ts(line)
        if not ts:
            continue
        ev = _parse_meshbot_line(plain, ts, nodes)
        if ev:
            events.append(ev)
    return events


def _parse_messages_logs_tail(
    log_dir: str,
    nodes: _NodeDirectory,
    *,
    max_lines: int = MSGLOG_TAIL_DEFAULT,
    dm_only: bool = False,
) -> List[Dict[str, Any]]:
    from modules.web_dashboard import _parse_messages_log_lines

    paths = _resolve_rotated_log_paths(log_dir, "messages.log")
    if not paths:
        return []
    lines = _tail_merged_log_paths(paths, max_lines)
    if dm_only:
        lines = [ln for ln in lines if " DM |" in ln]
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
    meshbot_events = _parse_meshbot_tail(
        log_dir,
        nodes,
        max_lines=MESHBOT_TAIL_DM_SCAN if dm_mode else MESHBOT_TAIL_DEFAULT,
        dm_only=dm_mode,
    )
    msg_log_events = _parse_messages_logs_tail(
        log_dir,
        nodes,
        max_lines=MSGLOG_TAIL_DM_SCAN if dm_mode else MSGLOG_TAIL_DEFAULT,
        dm_only=dm_mode,
    )

    merged = _merge_events(meshbot_events, msg_log_events)

    if after_iso:
        merged = [m for m in merged if m.get("time", "") > after_iso]

    if kind:
        merged = [m for m in merged if m.get("kind") == kind]

    if channel is not None:
        filtered = []
        for m in merged:
            if m.get("kind") == "dm":
                filtered.append(m)
            elif m.get("channel") == channel:
                filtered.append(m)
        merged = filtered

    merged.sort(key=lambda x: x.get("time", ""))
    if len(merged) > limit:
        merged = merged[-limit:]

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
