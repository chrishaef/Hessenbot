#!/usr/bin/env python3
# Public bot statistics page (Flask), inspired by etc/report_generator5.py log parsing.

from __future__ import annotations

import json
import os
import pickle
import platform
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape as html_escape
from typing import Any, Dict, List, Optional

from modules.paths import path_in_repo, repo_root

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,(\d+))?")


def _parse_log_timestamp(date_s: str, frac_s: Optional[str] = None) -> Optional[datetime]:
    try:
        dt = datetime.strptime(date_s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if frac_s:
        dt = dt.replace(microsecond=int(frac_s.ljust(6, "0")[:6]))
    return dt


def _parse_ts_from_log_line(line: str) -> Optional[datetime]:
    m = _LOG_TS_RE.match(line)
    if not m:
        return None
    return _parse_log_timestamp(m.group(1), m.group(2))


_REALM_TEXT_PREFIX_RE = re.compile(r"^[\w.*-]+\s*\|\s*", re.IGNORECASE)


def _strip_realm_text_prefix(text: str) -> str:
    """Remove leading ``meshhessen.de |`` style prefixes from message bodies."""
    out = (text or "").strip()
    while True:
        stripped = _REALM_TEXT_PREFIX_RE.sub("", out, count=1).strip()
        if stripped == out:
            return out
        out = stripped


class _NodeDirectory:
    """Maps Meshtastic node IDs / names while scanning meshbot.log."""

    def __init__(self) -> None:
        self._by_id: Dict[int, Dict[str, str]] = {}
        self._long_to_id: Dict[str, int] = {}

    def register(self, node_id: int, *, short: str = "", long_name: str = "") -> None:
        entry = self._by_id.setdefault(
            node_id,
            {"short": "", "long": "", "hex": f"!{node_id:08x}", "id": str(node_id)},
        )
        entry["hex"] = f"!{node_id:08x}"
        entry["id"] = str(node_id)
        if short:
            entry["short"] = short
        if long_name:
            entry["long"] = long_name
            self._long_to_id[long_name] = node_id

    def resolve(self, label: str) -> Dict[str, str]:
        label = (label or "").strip()
        if not label:
            return {"id": "", "hex": "", "short": "", "long": ""}

        if label.startswith("!"):
            try:
                node_id = int(label[1:], 16)
            except ValueError:
                return {"id": "", "hex": label, "short": "", "long": ""}
            entry = self._by_id.get(node_id, {})
            return {
                "id": str(node_id),
                "hex": label,
                "short": entry.get("short", ""),
                "long": entry.get("long", ""),
            }

        if label.isdigit():
            node_id = int(label)
            entry = self._by_id.get(node_id, {})
            return {
                "id": str(node_id),
                "hex": entry.get("hex", f"!{node_id:08x}"),
                "short": entry.get("short", ""),
                "long": entry.get("long", ""),
            }

        if label in self._long_to_id:
            node_id = self._long_to_id[label]
            entry = self._by_id[node_id]
            return {
                "id": str(node_id),
                "hex": entry["hex"],
                "short": entry.get("short", ""),
                "long": label,
            }

        for node_id, entry in self._by_id.items():
            if entry.get("long") == label:
                return {
                    "id": str(node_id),
                    "hex": entry["hex"],
                    "short": entry.get("short", ""),
                    "long": label,
                }
            if entry.get("short") == label:
                return {
                    "id": str(node_id),
                    "hex": entry["hex"],
                    "short": label,
                    "long": entry.get("long", ""),
                }

        return {"id": "", "hex": "", "short": "", "long": label}


def _parse_channel_from_log(plain: str, device: Optional[int]) -> tuple[Optional[int], str]:
    """Channel index + display label from meshbot.log (legacy and Channel:N|name)."""
    rx = device if device is not None else 1
    m = re.search(r"Channel:(\d+)(?:\|([^|\s]+))?", plain)
    if m:
        ch = int(m.group(1))
        label = (m.group(2) or "").strip()
        if label:
            return ch, label
        try:
            from modules.system import format_channel_label

            return ch, format_channel_label(ch, rx)
        except Exception:
            return ch, f"Kanal {ch}"
    m2 = re.search(r"Channel:?\s*(\d+)", plain)
    if m2:
        ch = int(m2.group(1))
        try:
            from modules.system import format_channel_label

            return ch, format_channel_label(ch, rx)
        except Exception:
            return ch, f"Kanal {ch}"
    return None, "?"


def _extract_message_event(
    plain: str, timestamp: datetime, nodes: _NodeDirectory
) -> Optional[Dict[str, Any]]:
    """Parse one meshbot.log line into a structured message event."""
    if not timestamp:
        return None

    dev_m = re.search(r"Device:(\d+)", plain)
    device = int(dev_m.group(1)) if dev_m else None
    channel, channel_label = _parse_channel_from_log(plain, device)
    base: Dict[str, Any] = {
        "time": timestamp.isoformat(),
        "time_short": timestamp.strftime("%H:%M:%S"),
        "device": device,
        "channel": channel,
        "channel_label": channel_label,
    }

    if "Sending DM:" in plain or "Sending Multi-Chunk DM:" in plain:
        to_m = re.search(r"\sTo:\s*(.+?)$", plain)
        peer = nodes.resolve(to_m.group(1)) if to_m else {}
        return {**base, "dir": "out", "kind": "dm", **peer}

    if "SendingChannel:" in plain or "Sending Multi-Chunk Message:" in plain:
        return {**base, "dir": "out", "kind": "channel", "id": "", "hex": "", "short": "", "long": ""}

    if any(
        marker in plain
        for marker in ("Received DM:", "Ignoring DM:", "Ignoring Message:", "ReceivedChannel:")
    ):
        from_m = re.search(r"From:\s*(.+?)$", plain)
        peer = nodes.resolve(from_m.group(1)) if from_m else {}
        if "Received DM:" in plain or "Ignoring DM:" in plain:
            kind = "dm"
        else:
            kind = "channel"
        text = ""
        if kind == "channel":
            if "ReceivedChannel:" in plain:
                msg_m = re.search(r"ReceivedChannel:\s*(.+?)\s+From:\s*", plain)
            else:
                msg_m = re.search(r"Ignoring Message:\s*(.+?)\s+From:\s*", plain)
            if msg_m:
                text = msg_m.group(1).strip()
        return {**base, "dir": "in", "kind": kind, "text": text, **peer}

    return None


def _format_message_peer(entry: Dict[str, Any]) -> str:
    short, long_name = _peer_display_names(entry)
    if long_name and long_name != short:
        return f"{short} | {long_name}"
    return short or long_name or "?"


def _format_message_line(entry: Dict[str, Any]) -> str:
    t = _hhmm_from_event(entry) or (entry.get("time_short") or "")[:5]
    direction = "An" if entry.get("dir") == "out" else "Von"
    peer = _format_message_peer(entry)

    if entry.get("kind") == "channel" and entry.get("dir") == "out":
        label = entry.get("channel_label") or (
            f"Kanal {entry['channel']}" if entry.get("channel") is not None else "?"
        )
        return f"{t} · {label} (gesendet)"

    suffix = ""
    if entry.get("kind") == "dm":
        suffix = " · DM"
    elif entry.get("kind") == "channel" and entry.get("channel") is not None:
        suffix = f" · {entry.get('channel_label') or f'Kanal {entry['channel']}'}"


    return f"{t} · {direction}: {peer}{suffix}"


def _short_timestamp(ts_iso: str) -> str:
    """DD.MM HH:MM for dashboard lists."""
    try:
        return datetime.fromisoformat(ts_iso).strftime("%d.%m %H:%M")
    except ValueError:
        return ts_iso[-8:] if len(ts_iso) >= 8 else ts_iso


def _parse_command_from_suffix(text: str) -> tuple[str, bool]:
    """Strip isDM:/playing: debug tail from mesh_bot command log lines."""
    text = (text or "").strip()
    is_dm = False
    dm_m = re.search(r"\bisDM:(True|False)\b", text)
    if dm_m:
        is_dm = dm_m.group(1) == "True"
        text = re.sub(r"\s*isDM:(True|False)\b", "", text)
    text = re.sub(r"\s*playing:(?:False|None|True|\w+)\b", "", text)
    text = re.sub(r"\s+is\s+playing\s+\w+", "", text, flags=re.IGNORECASE)
    return text.strip(), is_dm


def _format_command_label(cmd: str, who_raw: str = "") -> str:
    who, is_dm = _parse_command_from_suffix(who_raw)
    parts = [cmd]
    if who and who != "?":
        parts.append(who)
    label = " · ".join(parts)
    if is_dm:
        label += " · DM"
    return label


def _format_command_line(ts_iso: str, label: str) -> str:
    return f"{_short_timestamp(ts_iso)} · {label}"


def _command_list_items(entries: List[tuple], empty: str = "Keine Befehle") -> str:
    if not entries:
        return f'<li class="text-muted">{html_escape(empty)}</li>'
    lines = [_format_command_line(ts, label) for ts, label in reversed(entries[-12:])]
    return "".join(f"<li>{html_escape(line)}</li>" for line in lines)


def _tail_lines(log_path: str, max_lines: int, *, encoding: str = "utf-8") -> List[str]:
    """Read ~the last ``max_lines`` lines without loading the whole file.

    Seeks from the end in 64 KiB blocks until enough newlines are collected, so a
    multi-MB log doesn't get fully read into memory on every dashboard request.
    """
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            block = 65536
            data = b""
            while pos > 0 and data.count(b"\n") <= max_lines:
                read_size = min(block, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size) + data
    except OSError:
        return []
    lines = data.decode(encoding, errors="replace").splitlines(keepends=True)
    return lines[-max_lines:]


def _parse_messages_log_lines(
    lines: List[str], nodes: _NodeDirectory
) -> List[Dict[str, Any]]:
    """Parse messages.log lines (pipe format)."""
    events: List[Dict[str, Any]] = []
    for line in lines:
        m = re.match(
            r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d+) \| "
            r"Device:(\d+) (Channel:\d+(?:\|[^|]+)?) \| ([^|]+) \|(?: DM \|)?\s*(.*)$",
            line.strip(),
        )
        if not m:
            m = re.match(
                r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d+) \| "
                r"Device:(\d+) Channel:(\d+) \| ([^|]+) \|(?: DM \|)?\s*(.*)$",
                line.strip(),
            )
        if not m:
            continue
        ts_s, frac_s, dev_s, ch_field, name, _text = m.groups()
        ts = _parse_log_timestamp(ts_s, frac_s)
        if not ts:
            continue
        device = int(dev_s)
        if ch_field.startswith("Channel:"):
            channel, channel_label = _parse_channel_from_log(ch_field, device)
        else:
            channel, channel_label = int(ch_field), f"Kanal {ch_field}"
        peer = nodes.resolve(name.strip())
        is_dm = " DM |" in line
        body = _strip_realm_text_prefix(_text.strip().replace("\n", " "))
        events.append(
            {
                "time": ts.isoformat(),
                "time_short": ts.strftime("%H:%M:%S"),
                "dir": "in",
                "kind": "dm" if is_dm else "channel",
                "channel": channel,
                "channel_label": channel_label,
                "device": device,
                "text": body,
                **peer,
            }
        )
    return events


def _parse_messages_log_tail(
    log_path: str, nodes: _NodeDirectory, *, max_lines: int = 800
) -> List[Dict[str, Any]]:
    """Supplement recent messages from logs/messages.log (pipe format, with rotation)."""
    from modules.admin_mesh_chat import _parse_messages_logs_tail

    log_dir = os.path.dirname(os.path.realpath(log_path))
    return _parse_messages_logs_tail(log_dir, nodes, max_lines=max_lines)


def _empty_log_stats() -> Dict[str, Any]:
    return {
        "command_counts": Counter(),
        "message_types": Counter(),
        "unique_users": [],
        "warnings": [],
        "errors": [],
        "hourly_activity": {},
        "bbs_messages": 0,
        "messages_waiting": 0,
        "total_messages": 0,
        "command_timestamps": [],
        "message_timestamps": [],
        "recent_messages": [],
        "bbs_dm_delivered": [],
        "bbs_dm_queued": [],
        "firmware1_version": "—",
        "firmware2_version": "—",
        "node1_name": "—",
        "node2_name": "—",
        "node1_ID": "—",
        "node2_ID": "—",
        "nodeCount1": "—",
        "nodeCountOnline1": "—",
        "log_lines": 0,
        "log_error": None,
        "node_rx_counts_by_id": {},
        "node_rx_counts_24h_by_id": {},
    }


_LEADERBOARD_24H_SEC = 86400

# Cache parsed log stats so repeated dashboard requests (and the 5s auto-refresh
# admin views) don't re-read and re-parse a multi-MB log every time. Keyed by log
# path; served for up to _LOG_PARSE_TTL seconds and invalidated when meshbot.log or
# messages.log change (size/mtime, including the newest rotated backup).
_LOG_PARSE_TTL = 30.0
_log_parse_cache: Dict[str, Dict[str, Any]] = {}


def _log_sources_fingerprint(log_path: str) -> tuple:
    """Cheap change detector for meshbot.log + messages.log (+ latest rotation)."""
    import glob

    log_dir = os.path.dirname(os.path.realpath(log_path))
    parts: List[tuple] = []
    for basename in ("meshbot.log", "messages.log"):
        primary = os.path.join(log_dir, basename)
        try:
            parts.append(
                (basename, os.path.getsize(primary), int(os.path.getmtime(primary)))
            )
        except OSError:
            parts.append((basename, -1, -1))
        backups = sorted(
            glob.glob(os.path.join(log_dir, f"{basename}.*")),
            key=os.path.getmtime,
            reverse=True,
        )
        if backups:
            try:
                parts.append(
                    (
                        f"{basename}.rot",
                        os.path.getsize(backups[0]),
                        int(os.path.getmtime(backups[0])),
                    )
                )
            except OSError:
                parts.append((f"{basename}.rot", -1, -1))
    return tuple(parts)


def parse_meshbot_log(log_path: str, max_lines: int = 25000) -> Dict[str, Any]:
    """Parse meshbot.log with a short-TTL cache (see _log_parse_cache)."""
    now = time.time()
    fp = _log_sources_fingerprint(log_path)
    cached = _log_parse_cache.get(log_path)
    if (
        cached is not None
        and (now - cached["ts"]) < _LOG_PARSE_TTL
        and cached.get("fp") == fp
        and not cached["stats"].get("log_error")
    ):
        return cached["stats"]

    stats = _parse_meshbot_log_uncached(log_path, max_lines)
    _log_parse_cache[log_path] = {"ts": now, "fp": fp, "stats": stats}
    return stats


def _parse_meshbot_log_uncached(log_path: str, max_lines: int = 25000) -> Dict[str, Any]:
    """Parse meshbot.log (same patterns as report_generator5)."""
    stats = _empty_log_stats()
    if not os.path.isfile(log_path):
        stats["log_error"] = f"Logdatei nicht gefunden: {log_path}"
        return stats

    lines = _tail_lines(log_path, max_lines)
    stats["log_lines"] = len(lines)

    hourly: Dict[str, int] = defaultdict(int)
    unique_users: set = set()
    command_counts: Counter = Counter()
    message_types: Counter = Counter()
    command_timestamps: List[tuple] = []
    message_timestamps: List[tuple] = []
    nodes = _NodeDirectory()
    warnings: List[str] = []
    errors: List[str] = []
    bbs_dm_delivered: List[Dict[str, Any]] = []
    bbs_dm_queued: List[Dict[str, Any]] = []
    timestamp = None

    for line in lines:
        plain = _strip_ansi(line)
        timestamp_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+", line)
        if timestamp_match:
            timestamp = _parse_ts_from_log_line(line)
            if timestamp:
                hourly[timestamp.strftime("%Y-%m-%d %H:00:00")] += 1

        if "Bot detected Commands" in line or "LLM Query:" in line:
            command = re.search(r"'cmd': '(\w+)'", line)
            user = re.search(r"From: (.+)$", line)
            if "LLM Query:" in line and timestamp:
                command_counts["LLM Query"] += 1
                command_timestamps.append((timestamp.isoformat(), "LLM Query"))
            if command and timestamp:
                cmd = command.group(1)
                command_counts[cmd] += 1
                who_raw = user.group(1) if user else ""
                command_timestamps.append(
                    (timestamp.isoformat(), _format_command_label(cmd, who_raw))
                )

        ns_match = re.search(r"NodeID:(\d+)\s+ShortName:(\S+)", plain)
        if ns_match:
            nodes.register(int(ns_match.group(1)), short=ns_match.group(2))

        evt = _extract_message_event(plain, timestamp, nodes) if timestamp else None
        if evt:
            if evt.get("dir") == "out":
                message_types["Ausgehend"] += 1
            else:
                message_types["Eingehend"] += 1
            stats["total_messages"] += 1
            if timestamp:
                peer = _format_message_peer(evt)
                direction = "An" if evt.get("dir") == "out" else "Von"
                message_timestamps.append(
                    (timestamp.isoformat(), f"{direction}: {peer}")
                )

        user_match = re.search(r"From: '([^']+)'(?: To:|$)", plain) or re.search(
            r"From: (.+)$", plain
        )
        if user_match:
            unique_users.add(user_match.group(1).strip()[:80])

        if "WARNING |" in line:
            warnings.append(line.strip()[:200])
        if "ERROR |" in line or "CRITICAL |" in line:
            errors.append(line.strip()[:200])

        bbs_match = re.search(
            r"ðŸ“¡BBSdb has (\d+) messages.*?Messages waiting: (\d+)", line
        )
        if bbs_match:
            stats["bbs_messages"] = int(bbs_match.group(1))
            stats["messages_waiting"] = int(bbs_match.group(2))

        if "BBS DM Queued:" in plain and timestamp:
            qm = re.search(r"from=(\d+)\s+to=(\d+)", plain)
            if qm:
                bbs_dm_queued.append(
                    {
                        "time": timestamp.isoformat(),
                        "from_id": qm.group(1),
                        "to_id": qm.group(2),
                    }
                )

        if "BBS DM Delivery:" in plain and timestamp:
            dm_new = re.search(r"from=(\d+)\s+to=(\d+)", plain)
            if dm_new:
                bbs_dm_delivered.append(
                    {
                        "time": timestamp.isoformat(),
                        "from_id": dm_new.group(1),
                        "to_id": dm_new.group(2),
                    }
                )
            else:
                dm_del = re.search(r"BBS DM Delivery:\s*(.+?)\s+For:\s*(.+)$", plain)
                if dm_del:
                    to_label = dm_del.group(2).strip()[:80]
                    to_resolved = nodes.resolve(to_label)
                    bbs_dm_delivered.append(
                        {
                            "time": timestamp.isoformat(),
                            "text": dm_del.group(1).strip(),
                            "to": to_label,
                            "to_id": to_resolved.get("id") or "",
                            "from_id": "",
                        }
                    )

        if "| Telemetry:" in line:
            telemetry_match = re.search(
                r"Telemetry:(\d+) numPacketsRx:(\d+).*?totalNodes:(\d+) Online:(\d+).*?"
                r"Uptime:(\d+d) Volt:([\d.]+) Firmware:([\d.]+)",
                line,
            )
            if telemetry_match:
                iface, _rx, total, online, uptime, volt, fw = telemetry_match.groups()
                summary = f"Nodes {online}/{total}, {uptime}, {volt}V"
                if iface == "1":
                    stats["firmware1_version"] = fw
                    stats["nodeCount1"] = total
                    stats["nodeCountOnline1"] = online
                    stats["node1_uptime"] = summary
                elif iface == "2":
                    stats["firmware2_version"] = fw
                    stats["node2_uptime"] = summary

        if "Autoresponder Started for Device" in plain:
            device_match = re.search(
                r"Autoresponder Started for Device(\d+)\s+([^\s,]+).*?NodeID: (\d+)",
                plain,
            )
            if device_match:
                dev_id, name, node_id = device_match.groups()
                nodes.register(int(node_id), short=name)
                if dev_id == "1":
                    stats["node1_name"] = name
                    stats["node1_ID"] = node_id
                elif dev_id == "2":
                    stats["node2_name"] = name
                    stats["node2_ID"] = node_id

    log_dir = os.path.dirname(os.path.realpath(log_path))
    from modules.admin_mesh_chat import build_merged_message_feed

    recent_messages = build_merged_message_feed(log_dir, limit=120)

    node_rx_counts: defaultdict[int, int] = defaultdict(int)
    node_rx_counts_24h: defaultdict[int, int] = defaultdict(int)
    cutoff_24h = datetime.now() - timedelta(hours=24)
    for e in recent_messages:
        if e.get("dir") != "in":
            continue
        eid = e.get("id")
        if not eid:
            continue
        try:
            nid = int(eid)
        except (TypeError, ValueError):
            continue
        node_rx_counts[nid] += 1
        evt_time = e.get("time")
        if evt_time:
            try:
                if datetime.fromisoformat(evt_time) >= cutoff_24h:
                    node_rx_counts_24h[nid] += 1
            except ValueError:
                pass

    stats["command_counts"] = command_counts
    stats["message_types"] = message_types
    stats["hourly_activity"] = dict(hourly)
    stats["unique_users"] = list(unique_users)[-30:]
    stats["warnings"] = warnings[-15:][::-1]
    stats["errors"] = errors[-15:][::-1]
    stats["command_timestamps"] = command_timestamps[-40:]
    stats["message_timestamps"] = message_timestamps[-40:]
    stats["recent_messages"] = recent_messages
    stats["bbs_dm_delivered"] = bbs_dm_delivered[-25:]
    stats["bbs_dm_queued"] = bbs_dm_queued[-50:]
    stats["node_rx_counts_by_id"] = dict(node_rx_counts)
    stats["node_rx_counts_24h_by_id"] = dict(node_rx_counts_24h)
    return stats


def _load_bbs_public_messages() -> List[List[Any]]:
    """Public BBS posts from live bot state or data/bbsdb.pkl."""
    messages: List[List[Any]] = []
    try:
        import modules.bbstools as bbs

        raw = getattr(bbs, "bbs_messages", None)
        if raw:
            messages = list(raw)
    except Exception:
        pass
    if not messages:
        pkl = path_in_repo("data/bbsdb.pkl")
        if os.path.isfile(pkl):
            try:
                with open(pkl, "rb") as f:
                    loaded = pickle.load(f)
                if isinstance(loaded, list):
                    messages = loaded
            except Exception:
                pass
    return messages


def _format_bbs_public_timestamp(when_raw: str) -> str:
    if not when_raw:
        return "—"
    try:
        return datetime.strptime(when_raw[:19], "%Y-%m-%d %H:%M:%S").strftime(
            "%d.%m.%Y %H:%M"
        )
    except ValueError:
        return when_raw[:16] if len(when_raw) >= 16 else when_raw


def _render_bbs_public_item_html(entry: List[Any]) -> str:
    mid = entry[0] if entry else "?"
    subject = str(entry[1]).strip() if len(entry) > 1 else "—"
    body = str(entry[2]).strip() if len(entry) > 2 else ""
    from_id = entry[3] if len(entry) > 3 else 0
    when_raw = str(entry[4]) if len(entry) > 4 else ""

    sender = html_escape(_bbs_dm_party_label(from_id))
    when_disp = html_escape(_format_bbs_public_timestamp(when_raw))
    subj_esc = html_escape(subject)
    body_esc = html_escape(body)
    mid_esc = html_escape(str(mid))

    body_block = (
        f'<p class="dash-bbs-body">{body_esc}</p>'
        if body_esc
        else '<p class="dash-bbs-body text-muted">—</p>'
    )

    return (
        '<li class="dash-bbs-item">'
        '<motion class="dash-bbs-meta">'
        '<motion class="dash-bbs-from">'
        '<span class="dash-bbs-from-k">Absender</span>'
        f'<span class="dash-bbs-from-v">{sender}</span>'
        "</motion>"
        '<motion class="dash-bbs-time">'
        '<span class="dash-bbs-time-k">Eingereicht</span>'
        f'<span class="dash-bbs-time-v">{when_disp}</span>'
        "</motion>"
        "</motion>"
        f'<h3 class="dash-bbs-subject"><span class="dash-bbs-id">#{mid_esc}</span> {subj_esc}</h3>'
        f"{body_block}"
        "</li>"
    ).replace("<motion", "<div").replace("</motion>", "</div>")

def _render_bbs_public_html(messages: List[List[Any]], *, enabled: bool) -> str:
    if not enabled:
        return '<p class="text-muted small mb-0">Mesh-BBS ist deaktiviert.</p>'
    if not messages:
        return '<p class="text-muted small mb-0">Keine öffentlichen Nachrichten.</p>'
    items = [_render_bbs_public_item_html(m) for m in reversed(messages[-25:])]
    return (
        '<ul class="dash-list dash-list--bbs dash-scroll mb-0">'
        + "".join(items)
        + "</ul>"
    )


def _load_bbs_dm_queue() -> List[List[Any]]:
    """Pending BBS DMs (without internal placeholder row 0)."""
    rows: List[List[Any]] = []
    try:
        import modules.bbstools as bbs

        raw = list(getattr(bbs, "bbs_dm", None) or [])
        if raw:
            rows = raw
    except Exception:
        pass
    if len(rows) <= 1:
        pkl = path_in_repo("data/bbsdm.pkl")
        if os.path.isfile(pkl):
            try:
                with open(pkl, "rb") as f:
                    loaded = pickle.load(f)
                if isinstance(loaded, list) and loaded:
                    rows = loaded
            except Exception:
                pass
    return rows[1:] if len(rows) > 1 else []


def _format_dm_timestamp(iso_time: str) -> str:
    if not iso_time:
        return "—"
    try:
        return datetime.fromisoformat(iso_time).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso_time[:16] if len(iso_time) >= 16 else iso_time


def _bbs_dm_party_label(node_id: Any) -> str:
    from modules.bbstools import bbs_party_display_label

    return bbs_party_display_label(node_id, 1)


def _lookup_dm_sent_time(
    queued_log: List[Dict[str, Any]],
    from_id: Any,
    to_id: Any,
    *,
    before: str = "",
) -> str:
    fi, ti = str(from_id or ""), str(to_id or "")
    if not fi or not ti:
        return ""
    best = ""
    for entry in queued_log:
        if entry.get("from_id") != fi or entry.get("to_id") != ti:
            continue
        t = str(entry.get("time") or "")
        if before and t and t > before:
            continue
        if t >= best:
            best = t
    return best


def _bbs_dm_status_badge(status: str) -> str:
    if status == "delivered":
        return '<span class="badge text-bg-success dash-dm-badge">zugestellt</span>'
    return '<span class="badge text-bg-warning text-dark dash-dm-badge">wartend</span>'


def _render_bbs_dm_item_html(
    *,
    from_id: Any,
    to_id: Any,
    sent: str,
    received: str,
    status: str,
) -> str:
    von = html_escape(_bbs_dm_party_label(from_id))
    an = html_escape(_bbs_dm_party_label(to_id))
    sent_disp = html_escape(_format_dm_timestamp(sent))
    recv_disp = html_escape(_format_dm_timestamp(received))
    state_cls = "delivered" if status == "delivered" else "waiting"
    return (
        f'<li class="dash-dm-item dash-dm-item--{state_cls}">'
        '<TAG class="dash-dm-body">'
        f'<TAG class="dash-dm-row"><span class="dash-dm-k">Von</span><span class="dash-dm-v">{von}</span></TAG>'
        f'<TAG class="dash-dm-row"><span class="dash-dm-k">An</span><span class="dash-dm-v">{an}</span></TAG>'
        "</TAG>"
        '<TAG class="dash-dm-aside">'
        '<TAG class="dash-dm-times">'
        f'<TAG class="dash-dm-time"><span class="dash-dm-time-k">Eingereicht</span>'
        f'<span class="dash-dm-time-v">{sent_disp}</span></TAG>'
        f'<TAG class="dash-dm-time"><span class="dash-dm-time-k">Weitergeleitet</span>'
        f'<span class="dash-dm-time-v">{recv_disp}</span></TAG>'
        "</TAG>"
        f"{_bbs_dm_status_badge(status)}"
        "</TAG>"
        "</li>"
    ).replace("<TAG", "<div").replace("</TAG>", "</div>")


def _render_bbs_dm_queue_html(
    queue: List[List[Any]],
    delivered: List[Dict[str, Any]],
    queued_log: List[Dict[str, Any]],
    *,
    enabled: bool,
) -> str:
    if not enabled:
        return '<p class="text-muted small mb-0">Mesh-BBS ist deaktiviert.</p>'
    items: List[str] = []
    for row in reversed(queue[-25:]):
        to_id = row[0] if len(row) > 0 else 0
        from_id = row[2] if len(row) > 2 else 0
        sent = _lookup_dm_sent_time(queued_log, from_id, to_id)
        items.append(
            _render_bbs_dm_item_html(
                from_id=from_id,
                to_id=to_id,
                sent=sent,
                received="",
                status="waiting",
            )
        )
    for entry in reversed(delivered[-15:]):
        to_id = entry.get("to_id") or ""
        from_id = entry.get("from_id") or ""
        received = str(entry.get("time") or "")
        if not to_id and entry.get("to"):
            to_id = str(entry.get("to"))
        sent = _lookup_dm_sent_time(
            queued_log, from_id, to_id, before=received
        )
        items.append(
            _render_bbs_dm_item_html(
                from_id=from_id or "—",
                to_id=to_id or "—",
                sent=sent,
                received=received,
                status="delivered",
            )
        )
    if not items:
        return '<p class="text-muted small mb-0">Keine BBS-DMs.</p>'
    return (
        '<ul class="dash-list dash-list--dm dash-scroll dash-scroll--dm mb-0">'
        + "".join(items)
        + "</ul>"
    )


def _resolve_node_label(node_id: Any) -> str:
    if node_id is None:
        return "—"
    try:
        from modules.system import get_name_from_number

        name = get_name_from_number(int(node_id), "short", 1)
        if name and str(name).strip() and str(name) != str(node_id):
            return f"{name} · !{int(node_id):08x}"
    except Exception:
        pass
    try:
        return f"!{int(node_id):08x}"
    except (TypeError, ValueError):
        return str(node_id)


# Throttle the expensive leaderboard load (pickle read + full NodeDB sync inside
# loadLeaderboard()) so it runs at most once per TTL instead of on every request.
_MESH_LB_TTL = 30.0
_mesh_lb_cache: Dict[str, Any] = {"ts": 0.0, "data": None}


def _load_mesh_leaderboard() -> Dict[str, Any]:
    now = time.time()
    if _mesh_lb_cache["data"] is not None and (now - _mesh_lb_cache["ts"]) < _MESH_LB_TTL:
        return _mesh_lb_cache["data"]
    data = _load_mesh_leaderboard_uncached()
    _mesh_lb_cache["data"] = data
    _mesh_lb_cache["ts"] = now
    return data


def _load_mesh_leaderboard_uncached() -> Dict[str, Any]:
    """Load mesh leaderboard for the dashboard.

    Uses the bot's loadLeaderboard() when available. Only falls back to reading
    repo-root ``data/leaderboard.pkl`` when the in-memory message-count aggregates
    are missing (e.g. web process had wrong CWD before system.loadLeaderboard used
    path_in_repo) — avoiding a redundant second pickle read in the common case.
    """
    lb: Dict[str, Any] = {}
    try:
        from modules.system import loadLeaderboard, meshLeaderboard

        loadLeaderboard()
        if meshLeaderboard:
            lb = dict(meshLeaderboard)
    except Exception:
        pass

    local_mc = lb.get("nodeMessageCounts") if isinstance(lb.get("nodeMessageCounts"), dict) else {}
    local_tmc = lb.get("nodeTMessageCounts") if isinstance(lb.get("nodeTMessageCounts"), dict) else {}
    # In-memory counts present → no need to touch the pickle again.
    if lb and local_mc and local_tmc:
        return lb

    pkl = path_in_repo("data/leaderboard.pkl")
    if not os.path.isfile(pkl):
        return lb

    try:
        with open(pkl, "rb") as f:
            disk = pickle.load(f)
        if not isinstance(disk, dict):
            return lb

        disk_mc = disk.get("nodeMessageCounts") if isinstance(disk.get("nodeMessageCounts"), dict) else {}
        if disk_mc and not local_mc:
            lb["nodeMessageCounts"] = disk_mc

        disk_tmc = disk.get("nodeTMessageCounts") if isinstance(disk.get("nodeTMessageCounts"), dict) else {}
        if disk_tmc and not local_tmc:
            lb["nodeTMessageCounts"] = disk_tmc

        if not lb:
            lb = disk
    except Exception:
        pass
    return lb


def _leaderboard_24h_cutoff() -> float:
    return time.time() - _LEADERBOARD_24H_SEC


def _leaderboard_record_in_window(rec: Any, cutoff_ts: float) -> bool:
    if not isinstance(rec, dict) or rec.get("nodeID") is None:
        return False
    ts = rec.get("timestamp") or 0
    try:
        return float(ts) >= cutoff_ts
    except (TypeError, ValueError):
        return False


def _leaderboard_24h_message_leader(log: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Meiste empfangene Kanal/DM-Nachrichten in den letzten 24h (aus Log).

    Fällt auf alle geparsten RX-Zähler zurück, falls die strikte 24h-Teilmenge
    leer ist (z. B. wenn einzelne Zeitstempel nicht geparst werden konnten) —
    besser als der veraltete All-Time-Wert aus leaderboard.pkl.
    """
    if not log:
        return None
    counts = log.get("node_rx_counts_24h_by_id")
    if not isinstance(counts, dict) or not counts:
        counts = log.get("node_rx_counts_by_id")
    if not isinstance(counts, dict) or not counts:
        return None
    best_id = None
    best_n = 0
    for raw_id, raw_n in counts.items():
        try:
            n = int(raw_n)
            nid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if n > best_n:
            best_n = n
            best_id = nid
    if best_id is None or best_n <= 0:
        return None
    return {"nodeID": best_id, "value": best_n, "timestamp": time.time()}


def _format_uptime(value: Any) -> str:
    """Sekunden als kompakte Tage/Stunden/Minuten-Angabe (z. B. '3d 4h')."""
    try:
        secs = int(float(value))
    except (TypeError, ValueError):
        return "?"
    if secs < 0:
        return "?"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


# Throttle the live NodeDB scan used for the 24h leaderboard.
_NODEDB_LEADERS_TTL = 30.0
_nodedb_leaders_cache: Dict[str, Any] = {"ts": 0.0, "data": None}


def _cached_nodedb_leaders(cutoff_ts: float) -> Dict[str, Any]:
    now = time.time()
    if (
        _nodedb_leaders_cache["data"] is not None
        and (now - _nodedb_leaders_cache["ts"]) < _NODEDB_LEADERS_TTL
    ):
        return _nodedb_leaders_cache["data"]
    try:
        from modules.system import compute_24h_nodedb_leaders

        data = compute_24h_nodedb_leaders(cutoff_ts) or {}
    except Exception:
        data = {}
    _nodedb_leaders_cache["data"] = data
    _nodedb_leaders_cache["ts"] = now
    return data


def _leaderboard_web_rows(
    lb: Dict[str, Any], *, log: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Human-readable mesh leaderboard lines (nur Einträge der letzten 24h)."""
    cutoff = _leaderboard_24h_cutoff()
    msg_24h = _leaderboard_24h_message_leader(log)
    nodedb_leaders = _cached_nodedb_leaders(cutoff)
    specs = [
        ("mostMessages", "💬 Meiste Nachrichten", lambda r: str(int(r["value"]))),
        ("mostTMessages", "📊 Meiste Telemetrie", lambda r: str(int(r["value"]))),
        ("lowestBattery", "🪫 Niedrigster Akku", lambda r: f"{round(float(r['value']), 1)} %"),
        ("longestUptime", "🕰️ Längste Laufzeit", lambda r: _format_uptime(r["value"])),
        ("highestDBm", "📶 Bestes SNR", lambda r: f"{r['value']} dB"),
        ("weakestDBm", "📶 Schwächstes SNR", lambda r: f"{r['value']} dB"),
        ("fastestSpeed", "🚓 Höchstgeschwindigkeit", lambda r: f"{round(float(r['value']), 1)} km/h"),
        ("highestAltitude", "🚀 Höchste Höhe", lambda r: f"{int(round(float(r['value'])))} m"),
        ("coldestTemp", "🥶 Kälteste Temperatur", lambda r: f"{round(float(r['value']), 1)} °C"),
        ("hottestTemp", "🥵 Heißeste Temperatur", lambda r: f"{round(float(r['value']), 1)} °C"),
    ]
    lines: List[str] = []
    for key, title, fmt in specs:
        if key == "mostMessages" and msg_24h:
            rec = msg_24h
        elif key in nodedb_leaders:
            rec = nodedb_leaders[key]
        else:
            rec = lb.get(key)
        if not _leaderboard_record_in_window(rec, cutoff):
            continue
        if key == "lowestBattery" and float(rec.get("value", 101)) >= 101:
            continue
        if key == "coldestTemp" and float(rec.get("value", 999)) >= 999:
            continue
        if key == "hottestTemp" and float(rec.get("value", -999)) <= -999:
            continue
        node = _resolve_node_label(rec["nodeID"])
        lines.append(f"{title}: {fmt(rec)} · {node}")
    return lines


def _render_mesh_leaderboard_html(
    lb: Dict[str, Any], *, log: Optional[Dict[str, Any]] = None
) -> str:
    lines = _leaderboard_web_rows(lb, log=log)
    if not lines:
        return (
            '<div class="dash-card-body">'
            '<p class="text-muted small mb-0">In den letzten 24 Stunden noch keine Rekorde.</p></div>'
        )
    return (
        '<div class="dash-card-body">'
        '<ul class="dash-list dash-scroll dash-equal-scroll mb-0">'
        + "".join(f"<li>{html_escape(line)}</li>" for line in lines)
        + "</ul></div>"
    )


def _mesh_node_counts_for_dash(lb: Dict[str, Any], log: Dict[str, Any]) -> Dict[Any, Any]:
    """Prefer leaderboard nodeMessageCounts (TEXT_MESSAGE tallies); else use log-derived rx."""
    mc = lb.get("nodeMessageCounts") if isinstance(lb.get("nodeMessageCounts"), dict) else {}

    def _pos_total(d: Any) -> int:
        if not isinstance(d, dict):
            return 0
        t = 0
        for v in d.values():
            try:
                iv = int(v)  # type: ignore[arg-type]
                if iv > 0:
                    t += iv
            except (TypeError, ValueError):
                continue
        return t

    if _pos_total(mc) > 0:
        return mc
    rx = log.get("node_rx_counts_by_id") if isinstance(log.get("node_rx_counts_by_id"), dict) else {}
    if _pos_total(rx) > 0:
        return rx
    return mc


def _peer_short_name(entry: Dict[str, Any]) -> str:
    return _peer_display_names(entry)[0]


def _peer_long_name(entry: Dict[str, Any]) -> str:
    return _peer_display_names(entry)[1]


_REALM_LONG_SUFFIX_RE = re.compile(r"\s*\|\s*\*?meshhessen\.de\*?\s*$", re.IGNORECASE)


def _clean_peer_long_name(long_name: str) -> str:
    long_name = (long_name or "").strip()
    long_name = _REALM_LONG_SUFFIX_RE.sub("", long_name).strip()
    if "|" in long_name:
        left, right = [p.strip() for p in long_name.split("|", 1)]
        if "meshhessen" in right.lower().replace("*", ""):
            return left
    return long_name


def _resolve_peer_node_id(entry: Dict[str, Any]) -> Optional[int]:
    """Node id from log fields or persistent NodeDB (never guessed from longName)."""
    raw_id = entry.get("id")
    if raw_id not in (None, ""):
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            pass

    hex_id = (entry.get("hex") or "").strip()
    if hex_id.startswith("!"):
        try:
            return int(hex_id[1:], 16)
        except ValueError:
            pass

    try:
        from modules import nodedb as ndb

        raw_long = (entry.get("long") or "").strip()
        clean_long = _clean_peer_long_name(raw_long)
        for candidate in (raw_long, clean_long):
            if candidate:
                nid = ndb.find_node_id_by_long_name(candidate)
                if nid:
                    return nid
        entry_short = (entry.get("short") or "").strip()
        if entry_short:
            nid = ndb.find_node_id_by_short_name(entry_short)
            if nid:
                return nid
    except Exception:
        pass
    return None


def _peer_display_names(entry: Dict[str, Any]) -> tuple[str, str]:
    """Return (shortName, longName) from NodeDB / NodeInfo — not derived from longName."""
    device = int(entry.get("device") or 1)
    node_id = _resolve_peer_node_id(entry)
    short = ""
    long_name = _clean_peer_long_name(entry.get("long") or "")

    if node_id is not None:
        try:
            from modules.system import get_name_from_number

            resolved_short = get_name_from_number(node_id, "short", device)
            if (
                resolved_short
                and str(resolved_short).strip()
                and not str(resolved_short).startswith("!")
            ):
                short = str(resolved_short).strip()
            resolved_long = get_name_from_number(node_id, "long", device)
            if (
                resolved_long
                and str(resolved_long).strip()
                and not str(resolved_long).startswith("!")
            ):
                long_name = _clean_peer_long_name(str(resolved_long).strip())
        except Exception:
            pass

        if not short or short == "?":
            try:
                from modules import nodedb as ndb

                ndb._ensure_nodedb_loaded()
                cached_short = ndb.get_node_short_name(node_id)
                if cached_short and str(cached_short).strip():
                    short = str(cached_short).strip()
                if not long_name:
                    cached_long = ndb.get_node_long_name(node_id)
                    if cached_long and str(cached_long).strip():
                        long_name = _clean_peer_long_name(str(cached_long).strip())
            except Exception:
                pass

    if not long_name:
        long_name = _clean_peer_long_name(entry.get("long") or "")
    if not short:
        short = "?"
    if not long_name:
        long_name = "—"
    return short, long_name


def _hhmm_from_event(entry: Dict[str, Any]) -> str:
    ts = entry.get("time") or ""
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M")
    except ValueError:
        raw = (entry.get("time_short") or "")[:5]
        return raw if raw else "—"


def _channel_recent_messages(
    log: Dict[str, Any], *, channel: int = 1, limit: int = 10
) -> List[Dict[str, Any]]:
    events = log.get("recent_messages") or []
    filtered = [
        e
        for e in events
        if e.get("kind") == "channel"
        and e.get("dir") == "in"
        and e.get("channel") == channel
    ]
    filtered.sort(key=lambda e: e.get("time") or "")
    return list(reversed(filtered[-limit:]))


def _render_toplist_message_item(entry: Dict[str, Any]) -> str:
    """HH:MM Shortname | Longname, then message body on the next line."""
    short, long_name = _peer_display_names(entry)
    meta = (
        f"{html_escape(_hhmm_from_event(entry))} "
        f"{html_escape(short)} | {html_escape(long_name)}"
    )
    text = (entry.get("text") or "").strip().replace("\r\n", "\n").replace("\r", "\n")
    if text:
        body = html_escape(text)
        return (
            f'<li class="dash-toplist-msg">'
            f'<div class="dash-toplist-msg__meta">{meta}</div>'
            f'<div class="dash-toplist-msg__text">{body}</div>'
            f"</li>"
        )
    return f'<li class="dash-toplist-msg"><div class="dash-toplist-msg__meta">{meta}</div></li>'


def _dashboard_messages_channel() -> int:
    """Kanalindex für die Messages-Topliste (gleicher Kanal wie !messages)."""
    try:
        import modules.settings as st

        return int(getattr(st, "messages_channel", 1))
    except Exception:
        pass
    return 1


def _dashboard_channel_title(channel: int, rx_node: int = 1) -> str:
    try:
        from modules.system import format_channel_label

        return format_channel_label(channel, rx_node)
    except Exception:
        return f"Kanal {channel}"


def _dashboard_messages_heading(channel: int) -> str:
    """Überschrift-Zusatz z. B. „Kanal 1 · #1MeshHessen“."""
    name = _dashboard_channel_title(channel)
    generic = f"Kanal {channel}"
    if name == generic or name == f"Channel{channel}":
        return html_escape(generic)
    return html_escape(f"{generic} · {name}")


def _render_toplist_html(
    log: Dict[str, Any],
    *,
    channel: Optional[int] = None,
    log_dir: Optional[str] = None,
) -> str:
    if channel is None:
        channel = _dashboard_messages_channel()
    if log_dir:
        from modules.admin_mesh_chat import load_public_channel_toplist

        entries = load_public_channel_toplist(log_dir, channel, limit=10)
    else:
        entries = _channel_recent_messages(log, channel=channel, limit=10)
    ch_title = _dashboard_channel_title(channel)
    if entries:
        items = "".join(_render_toplist_message_item(e) for e in entries)
    else:
        items = (
            f'<li class="text-muted">Noch keine Nachrichten auf {html_escape(ch_title)} im Log.</li>'
        )
    return f"""
<div class="dash-card-body">
  <ul class="dash-list dash-scroll dash-equal-scroll mb-0">{items}</ul>
</div>"""


def _activity_series(hourly: Dict[str, int], *, hours: int = 48) -> tuple[List[str], List[int]]:
    if not hourly:
        return [], []
    keys = sorted(hourly.keys())[-hours:]
    labels: List[str] = []
    values: List[int] = []
    for key in keys:
        try:
            dt = datetime.strptime(key, "%Y-%m-%d %H:00:00")
            labels.append(dt.strftime("%d.%m %H:%M"))
        except ValueError:
            labels.append(key[-11:] if len(key) > 11 else key)
        values.append(int(hourly[key]))
    return labels, values


def render_admin_log_alerts_html(log: Dict[str, Any]) -> str:
    """Recent warnings/errors from meshbot.log for the admin overview."""
    warnings = [_strip_ansi(str(w)) for w in (log.get("warnings") or [])[:8]]
    errors = [_strip_ansi(str(e)) for e in (log.get("errors") or [])[:8]]
    if not warnings and not errors:
        return (
            '<p class="text-muted small mb-0">'
            "Keine Warnungen oder Fehler im aktuellen Log-Ausschnitt."
            "</p>"
        )
    parts: List[str] = []
    if errors:
        parts.append('<h3 class="h6 text-danger mb-2">Fehler</h3>')
        parts.append('<ul class="dash-list dash-scroll mb-3">')
        parts.extend(f'<li class="text-danger">{html_escape(line)}</li>' for line in errors)
        parts.append("</ul>")
    if warnings:
        parts.append('<h3 class="h6 text-warning mb-2">Warnungen</h3>')
        parts.append('<ul class="dash-list dash-scroll mb-0">')
        parts.extend(f"<li>{html_escape(line)}</li>" for line in warnings)
        parts.append("</ul>")
    return "".join(parts)


def _host_info() -> Dict[str, str]:
    if platform.system() != "Linux":
        return {"uptime": "—", "memory": "—", "disk": "—"}
    try:

        def run(cmd: str) -> str:
            return (
                subprocess.check_output(cmd, shell=True, timeout=3)
                .decode("utf-8", errors="replace")
                .strip()
            )

        return {
            "uptime": run("uptime -p"),
            "memory": f"{run('free -m | awk \'/Mem:/ {print $7}\'')} / {run('free -m | awk \'/Mem:/ {print $2}\'')} MB frei",
            "disk": f"{run('df -h / | awk \'NR==2 {print $4}\'')} frei von {run('df -h / | awk \'NR==2 {print $2}\'')}",
        }
    except Exception:
        return {"uptime": "—", "memory": "—", "disk": "—"}


def collect_runtime_stats() -> Dict[str, Any]:
    import modules.settings as st

    out: Dict[str, Any] = {
        "motd": getattr(st, "MOTD", "—"),
        "bbs_enabled": getattr(st, "bbs_enabled", False),
        "bbs_public_count": 0,
        "bbs_public_messages": [],
        "bbs_dm_count": 0,
        "bbs_dm_queue": [],
        "mesh_leaderboard": {},
        "node_summary": [],
        "node_tables": [],
        "mesh_nodes_total": 0,
        "interfaces_active": 0,
    }
    try:
        import modules.bbstools as bbs

        public = _load_bbs_public_messages()
        out["bbs_public_messages"] = public
        out["bbs_public_count"] = len(public)
        dm_queue = _load_bbs_dm_queue()
        out["bbs_dm_queue"] = dm_queue
        out["bbs_dm_count"] = len(dm_queue)
    except Exception:
        out["bbs_public_messages"] = _load_bbs_public_messages()
        out["bbs_public_count"] = len(out["bbs_public_messages"])
        out["bbs_dm_queue"] = _load_bbs_dm_queue()
        out["bbs_dm_count"] = len(out["bbs_dm_queue"])

    out["mesh_leaderboard"] = _load_mesh_leaderboard()

    try:
        from modules import admin_web_ops as ops

        ifaces = ops.iter_radio_interfaces()
        out["interfaces_active"] = len(ifaces)
        total = 0
        for i in ifaces:
            err, rows = ops.list_node_rows(i)
            out["node_tables"].append({"iface": i, "error": err, "rows": rows})
            if err:
                out["node_summary"].append(f"IF{i}: {err}")
                continue
            total += len(rows)
            local = next((r for r in rows if r.get("is_self")), None)
            if local:
                out["node_summary"].append(
                    f"IF{i}: {local['shortName']} ({local['node_id']}) — {len(rows)} Knoten"
                )
            else:
                out["node_summary"].append(f"IF{i}: {len(rows)} Knoten in NodeDB")
        out["mesh_nodes_total"] = total
    except Exception as e:
        out["node_summary"].append(f"NodeDB: {e!s}")

    return out


def _want_ack_on_dm_enabled() -> bool:
    try:
        from modules import settings as st

        return bool(getattr(st, "wantAckOnDm", True))
    except Exception:
        return True


def collect_dashboard(log_dir: str) -> Dict[str, Any]:
    try:
        # Use the cached channel list; forcing a rebuild here would do live radio
        # I/O on every page load and compete with the packet handler. Channel
        # config changes already force a refresh (admin save / reconnect).
        from modules.system import build_channel_cache

        build_channel_cache()
    except Exception:
        pass
    base = log_dir if os.path.isabs(log_dir) else path_in_repo(log_dir)
    log_path = os.path.join(base, "meshbot.log")
    if not os.path.isfile(log_path):
        log_path = path_in_repo("logs/meshbot.log")
    want_ack_dm = _want_ack_on_dm_enabled()
    dm_delivery_24h = None
    if want_ack_dm:
        try:
            from modules.dm_delivery_stats import parse_dm_delivery_stats_24h

            dm_delivery_24h = parse_dm_delivery_stats_24h(log_dir)
        except Exception:
            dm_delivery_24h = {
                "confirmed": 0,
                "failed_pki": 0,
                "failed_other": 0,
                "hours": 24,
                "lines_scanned": 0,
                "top_problem_nodes": [],
            }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": repo_root(),
        "log_path": log_path,
        "log_dir": os.path.dirname(os.path.realpath(log_path)),
        "log": parse_meshbot_log(log_path),
        "runtime": collect_runtime_stats(),
        "want_ack_on_dm": want_ack_dm,
        "dm_delivery_24h": dm_delivery_24h,
    }


def _metric_card(title: str, value: str, sub: str = "", accent: str = "") -> str:
    val_cls = f" metric-value {accent}" if accent else "metric-value"
    sub_text = html_escape(sub) if sub else "&nbsp;"
    return f"""
    <div class="metric-card h-100">
      <div class="metric-label">{html_escape(title)}</div>
      <div class="{val_cls.strip()}">{html_escape(value)}</div>
      <div class="metric-label metric-sub">{sub_text}</div>
    </div>"""


def _list_items(items: List[str], empty: str = "Keine Einträge") -> str:
    if not items:
        return f'<li class="text-muted">{html_escape(empty)}</li>'
    return "".join(f"<li>{html_escape(str(x))}</li>" for x in items)


def render_host_metrics_html() -> str:
    """Host uptime/RAM/disk for admin UI."""
    host = _host_info()
    return f"""
<div class="row g-2 mb-0">
  <div class="col-md-4">
    <div class="metric-card">
      <div class="metric-label">Uptime</div>
      <div class="metric-value small">{html_escape(host["uptime"])}</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="metric-card">
      <div class="metric-label">RAM</div>
      <div class="metric-value small">{html_escape(host["memory"])}</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="metric-card">
      <div class="metric-label">Disk</div>
      <div class="metric-value small">{html_escape(host["disk"])}</div>
    </div>
  </div>
</div>
"""


def _render_public_nodedb(node_tables: List[Dict[str, Any]]) -> str:
    from modules.admin_web_ops import nodedb_row_search_attr, nodedb_search_toolbar_html

    if not node_tables:
        return '<p class="text-muted mb-0">Keine Meshtastic-Schnittstelle verbunden.</p>'

    parts: List[str] = []
    for block in node_tables:
        iface = block.get("iface", "?")
        err = block.get("error")
        if err:
            parts.append(
                f'<p class="alert alert-info py-2 mb-3">'
                f"Interface {iface}: {html_escape(err)}</p>"
            )
            continue
        rows = block.get("rows") or []
        if not rows:
            parts.append(
                f'<p class="text-muted mb-3">Interface {iface}: Keine Knoten in der NodeDB.</p>'
            )
            continue

        trs = []
        for r in rows:
            local = (
                ' <span class="badge bg-success ms-1">lokal</span>'
                if r.get("is_self")
                else ""
            )
            trs.append(
                f"<tr{nodedb_row_search_attr(r)}>"
                f"<td><code>{r['node_id']}</code></td>"
                f"<td>{r['shortName']}{local}</td>"
                f"<td>{r['longName']}</td>"
                f"<td>{r.get('location_html', '—')}</td>"
                f'<td class="text-nowrap">{html_escape(str(r.get("lastHeard", "—")))}</td>'
                "</tr>"
            )
        trs.append(
            '<tr class="nodedb-search-empty" hidden>'
            '<td colspan="5" class="text-muted small">Keine Treffer für die Suche.</td></tr>'
        )
        parts.append(
            f"""
<h3 class="h6 section-title mb-2">
  <i class="bi bi-reception-4 text-success me-1"></i>Interface {iface}
  <span class="text-muted fw-normal nodedb-iface-count">({len(rows)} Knoten)</span>
</h3>
<div class="table-scroll dash-nodedb-scroll mb-3">
  <table class="nodes-table table table-sm table-hover mb-0">
    <thead>
      <tr>
        <th>Node ID</th>
        <th>Kurzname</th>
        <th>Name</th>
        <th>Standort</th>
        <th>Zuletzt gehört</th>
      </tr>
    </thead>
    <tbody>{"".join(trs)}</tbody>
  </table>
</div>"""
        )
    return (
        '<div class="nodedb-search-block">'
        + nodedb_search_toolbar_html()
        + '<div class="nodedb-search-scope">'
        + "".join(parts)
        + "</div></div>"
        '<script src="/static/portal/nodedb-search.js"></script>'
    )


def _message_list_items(entries: List[Dict[str, Any]], empty: str = "Keine Nachrichten") -> str:
    if not entries:
        return f'<li class="text-muted">{html_escape(empty)}</li>'
    ordered = sorted(entries, key=lambda e: e.get("time") or "")
    lines = [_format_message_line(e) for e in reversed(ordered[-12:])]
    return "".join(f"<li>{html_escape(line)}</li>" for line in lines)


def render_dashboard_page(data: Dict[str, Any]) -> str:
    log = data["log"]
    rt = data["runtime"]
    raw_cmd = log.get("command_counts") or {}
    cmd: Counter = raw_cmd if isinstance(raw_cmd, Counter) else Counter(raw_cmd)
    top_cmds = cmd.most_common(12)
    activity_labels, activity_values = _activity_series(log.get("hourly_activity") or {})
    lb = rt.get("mesh_leaderboard") or {}
    dm_stats_chart = data.get("dm_delivery_24h") or {}
    dm_delivery_values = [
        int(dm_stats_chart.get("confirmed", 0) or 0),
        int(dm_stats_chart.get("failed_pki", 0) or 0),
        int(dm_stats_chart.get("failed_other", 0) or 0),
    ]
    chart_data_json = json.dumps(
        {
            "cmdLabels": [c[0] for c in top_cmds],
            "cmdValues": [c[1] for c in top_cmds],
            "activityLabels": activity_labels,
            "activityValues": activity_values,
            "dmDeliveryLabels": ["Bestätigt", "PKI-Fehler", "Sonst. Fehler"],
            "dmDeliveryValues": dm_delivery_values if data.get("want_ack_on_dm") else [],
        },
        ensure_ascii=False,
    )
    activity_chart_body = (
        '<div class="chart-canvas-wrap chart-canvas-wrap--wide"><canvas id="activityChart"></canvas></div>'
        if activity_labels
        else '<p class="text-muted small mb-0">Noch keine Aktivitätsdaten im Log.</p>'
    )
    cmd_chart_body = (
        '<div class="chart-canvas-wrap"><canvas id="cmdChart"></canvas></div>'
        if top_cmds
        else '<p class="text-muted small mb-0">Noch keine Befehle im Log.</p>'
    )
    cards = [
        _metric_card("Nachrichten", str(log["total_messages"]), "meshbot.log"),
        _metric_card("Befehle", str(len(cmd)), f"{sum(cmd.values())} Aufrufe", "text-success"),
        _metric_card("Nutzer", str(len(log["unique_users"])), "eindeutig", "text-info"),
        _metric_card(
            "BBS öffentlich",
            str(rt["bbs_public_count"]),
            "live" if rt["bbs_enabled"] else "deaktiviert",
        ),
        _metric_card("BBS DMs", str(rt["bbs_dm_count"])),
        _metric_card(
            "Mesh-Knoten",
            str(rt["mesh_nodes_total"]),
            f"{rt['interfaces_active']} Radio(s)",
            "text-success",
        ),
    ]

    recent_cmds_html = _command_list_items(log["command_timestamps"][-12:])
    recent_msgs_html = _message_list_items(log.get("recent_messages") or [])
    nodedb_html = _render_public_nodedb(rt.get("node_tables") or [])
    motd_text = html_escape(str(rt.get("motd", "—"))[:500])
    bbs_public = rt.get("bbs_public_messages") or []
    bbs_public_html = _render_bbs_public_html(
        bbs_public, enabled=bool(rt.get("bbs_enabled"))
    )
    bbs_count = len(bbs_public)
    bbs_dm_queue = rt.get("bbs_dm_queue") or []
    bbs_dm_delivered = log.get("bbs_dm_delivered") or []
    dm_count = len(bbs_dm_queue)
    bbs_dm_html = _render_bbs_dm_queue_html(
        bbs_dm_queue,
        bbs_dm_delivered,
        log.get("bbs_dm_queued") or [],
        enabled=bool(rt.get("bbs_enabled")),
    )
    msg_ch = _dashboard_messages_channel()
    msg_ch_heading = _dashboard_messages_heading(msg_ch)
    toplist_html = _render_toplist_html(log, channel=msg_ch, log_dir=data.get("log_dir"))
    leaderboard_html = _render_mesh_leaderboard_html(lb, log=log)
    want_ack_dm = bool(data.get("want_ack_on_dm"))
    dm_stats = data.get("dm_delivery_24h")
    from modules.dm_delivery_stats import render_dm_delivery_stats_html

    if want_ack_dm and dm_stats is not None:
        dm_delivery_body = render_dm_delivery_stats_html(dm_stats, compact=True)
    elif want_ack_dm:
        dm_delivery_body = (
            '<p class="text-muted small mb-0">Keine DM-Zustell-Daten im Log-Ausschnitt.</p>'
        )
    else:
        dm_delivery_body = (
            '<p class="text-muted small mb-0">'
            "DM-Zustellüberwachung ist aus "
            "(<code>wantAckOnDm = False</code> in der Config)."
            "</p>"
        )

    messages_lb_row_html = f"""
<div class="row g-3 mb-4 dash-equal-cards">
  <div class="col-lg-6 d-flex">
    <div class="section-card flex-fill d-flex flex-column w-100">
      <h2 class="section-title h5">
        <i class="bi bi-chat-left-text me-2 text-success"></i>Messages
        <span class="text-muted fw-normal fs-6">— {msg_ch_heading}</span>
      </h2>
      {toplist_html}
    </div>
  </div>
  <div class="col-lg-6 d-flex">
    <div class="section-card flex-fill d-flex flex-column w-100">
      <h2 class="section-title h5"><i class="bi bi-award me-2 text-success"></i>Leaderboard (24h)</h2>
      {leaderboard_html}
    </div>
  </div>
</div>"""
    log_note = ""
    if log.get("log_error"):
        log_note = f'<p class="alert alert-info mb-3"><i class="bi bi-info-circle me-2"></i>{html_escape(log["log_error"])}</p>'
    try:
        stand_time = datetime.strptime(data["generated_at"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
    except ValueError:
        stand_time = html_escape(str(data.get("generated_at", ""))[-5:])

    return f"""
<div class="hero-section mb-4">
  <div class="row align-items-center g-3">
    <div class="col-lg-8">
      <h1 class="display-6 fw-bold mb-0">
        <i class="bi bi-broadcast text-success me-2"></i>Hessenbot
      </h1>
    </div>
    <div class="col-lg-4 text-lg-end">
      <button type="button" id="dash-refresh-btn" class="btn btn-success">
        <i class="bi bi-arrow-clockwise me-2"></i>Aktualisieren
      </button>
      <p class="small text-muted mt-2 mb-0">Stand {html_escape(stand_time)}</p>
    </div>
  </div>
</div>
{log_note}

<div class="dash-panels">
<div data-dash-panel="stats">
<div class="stat-grid">{"".join(cards)}</div>

<div class="section-card mb-4">
  <h2 class="section-title h5"><i class="bi bi-chat-quote me-2 text-success"></i>Message of the Day</h2>
  <p class="motd-box mb-0">{motd_text}</p>
</div>

<div class="section-card mb-4">
  <h2 class="section-title h5"><i class="bi bi-activity me-2 text-success"></i>Aktivität über die Zeit</h2>
  <p class="small text-muted mb-2">Log-Zeilen pro Stunde (letzte {len(activity_labels)} Stunden)</p>
  {activity_chart_body}
</div>

<div class="row g-3 mb-4 dash-equal-cards dash-charts-pair">
  <div class="col-lg-6">
    <div class="section-card h-100">
      <h2 class="section-title h5"><i class="bi bi-bar-chart text-success me-2"></i>Top-Befehle</h2>
      <div class="dash-card-body">{cmd_chart_body}</div>
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card h-100">
      <h2 class="section-title h5">
        <i class="bi bi-envelope-check me-2 text-success"></i>DM-Zustellung (24h)
      </h2>
      <div class="dash-card-body">{dm_delivery_body}</div>
    </div>
  </div>
</div>

{messages_lb_row_html}

<div class="row g-3 mb-4">
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-clock-history me-2 text-success"></i>Letzte Befehle</h2>
      <ul class="dash-list dash-scroll mb-0">{recent_cmds_html}</ul>
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-chat-dots me-2 text-success"></i>Letzte Nachrichten</h2>
      <ul class="dash-list dash-scroll mb-0">{recent_msgs_html}</ul>
    </div>
  </div>
</div>
</div>

<div data-dash-panel="bbs" hidden>
<div class="section-card mb-4">
  <h2 class="section-title h5">
    <i class="bi bi-inboxes me-2 text-success"></i>BBS öffentlich
    <span class="badge text-bg-secondary ms-2 fw-normal">{bbs_count}</span>
  </h2>
  <p class="small text-muted mb-2">Absender, Zeit, Betreff und Text · neueste zuerst</p>
  {bbs_public_html}
</div>

<div class="section-card mb-4">
  <h2 class="section-title h5">
    <i class="bi bi-envelope-paper me-2 text-success"></i>BBS-DM Warteschlange
    <span class="badge text-bg-secondary ms-2 fw-normal">{dm_count}</span>
  </h2>
  {bbs_dm_html}
</div>
</div>

<div data-dash-panel="nodedb" hidden>
<div class="section-card mb-4">
  <h2 class="section-title h5"><i class="bi bi-diagram-3 me-2 text-success"></i>NodeDB</h2>
  {nodedb_html}
</div>
</div>
</div>

<script type="application/json" id="dash-chart-data">{chart_data_json}</script>
<script src="/static/portal/chart.umd.min.js"></script>
<script src="/static/portal/dashboard-charts.js"></script>
<script src="/static/portal/dashboard-views.js?v=2"></script>
"""

