#!/usr/bin/env python3
# Public bot statistics page (Flask), inspired by etc/report_generator5.py log parsing.

from __future__ import annotations

import json
import os
import pickle
import platform
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from html import escape as html_escape
from typing import Any, Dict, List, Optional

from modules.paths import path_in_repo, repo_root

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


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


def _extract_message_event(
    plain: str, timestamp: datetime, nodes: _NodeDirectory
) -> Optional[Dict[str, Any]]:
    """Parse one meshbot.log line into a structured message event."""
    if not timestamp:
        return None

    dev_m = re.search(r"Device:(\d+)", plain)
    ch_m = re.search(r"Channel:?\s*(\d+)", plain)
    device = int(dev_m.group(1)) if dev_m else None
    channel = int(ch_m.group(1)) if ch_m else None
    base: Dict[str, Any] = {
        "time": timestamp.isoformat(),
        "time_short": timestamp.strftime("%H:%M:%S"),
        "device": device,
        "channel": channel,
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
        return {**base, "dir": "in", "kind": kind, **peer}

    return None


def _format_message_peer(entry: Dict[str, Any]) -> str:
    short = entry.get("short") or ""
    node_id = entry.get("id") or ""
    hex_id = entry.get("hex") or ""
    long_name = entry.get("long") or ""

    if not hex_id and node_id.isdigit():
        hex_id = f"!{int(node_id):08x}"

    if short and hex_id and node_id:
        return f"{short} · {hex_id} (#{node_id})"
    if short and hex_id:
        return f"{short} · {hex_id}"
    if short and node_id:
        return f"{short} · #{node_id}"
    if hex_id:
        return hex_id
    if node_id:
        return f"#{node_id}"
    if long_name:
        return long_name
    return "?"


def _format_message_line(entry: Dict[str, Any]) -> str:
    t = entry.get("time_short") or entry.get("time", "")[-8:]
    direction = "An" if entry.get("dir") == "out" else "Von"
    peer = _format_message_peer(entry)

    if entry.get("kind") == "channel" and entry.get("dir") == "out":
        ch = entry.get("channel")
        return f"{t} · Kanal {ch if ch is not None else '?'} (gesendet)"

    suffix = ""
    if entry.get("kind") == "dm":
        suffix = " · DM"
    elif entry.get("kind") == "channel" and entry.get("channel") is not None:
        suffix = f" · Kanal {entry['channel']}"

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


def _parse_messages_log_tail(
    log_path: str, nodes: _NodeDirectory, *, max_lines: int = 800
) -> List[Dict[str, Any]]:
    """Supplement recent messages from logs/messages.log (pipe format)."""
    if not os.path.isfile(log_path):
        return []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    events: List[Dict[str, Any]] = []
    for line in lines[-max_lines:]:
        m = re.match(
            r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \| "
            r"Device:(\d+) Channel:(\d+) \| ([^|]+) \|(?: DM \|)?\s*(.*)$",
            line.strip(),
        )
        if not m:
            continue
        ts_s, _dev, ch, name, _text = m.groups()
        try:
            ts = datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        peer = nodes.resolve(name.strip())
        is_dm = " DM |" in line
        events.append(
            {
                "time": ts.isoformat(),
                "time_short": ts.strftime("%H:%M:%S"),
                "dir": "in",
                "kind": "dm" if is_dm else "channel",
                "channel": int(ch),
                **peer,
            }
        )
    return events


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
    }


def parse_meshbot_log(log_path: str, max_lines: int = 25000) -> Dict[str, Any]:
    """Parse meshbot.log (same patterns as report_generator5)."""
    stats = _empty_log_stats()
    if not os.path.isfile(log_path):
        stats["log_error"] = f"Logdatei nicht gefunden: {log_path}"
        return stats

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        stats["log_error"] = str(e)
        return stats

    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    stats["log_lines"] = len(lines)

    hourly: Dict[str, int] = defaultdict(int)
    unique_users: set = set()
    command_counts: Counter = Counter()
    message_types: Counter = Counter()
    command_timestamps: List[tuple] = []
    message_timestamps: List[tuple] = []
    recent_messages: List[Dict[str, Any]] = []
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
            timestamp = datetime.strptime(timestamp_match.group(1), "%Y-%m-%d %H:%M:%S")
            hourly[timestamp.strftime("%Y-%m-%d %H:00:00")] += 1

        if "Bot detected Commands" in line or "LLM Query:" in line or "PlayingGame" in line:
            command = re.search(r"'cmd': '(\w+)'", line)
            user = re.search(r"From: (.+)$", line)
            if "LLM Query:" in line and timestamp:
                command_counts["LLM Query"] += 1
                command_timestamps.append((timestamp.isoformat(), "LLM Query"))
            if "PlayingGame" in line:
                game = re.search(r"PlayingGame (\w+)", line)
                if game and timestamp:
                    command_counts[game.group(1)] += 1
                    command_timestamps.append((timestamp.isoformat(), game.group(1)))
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
            recent_messages.append(evt)
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
            warnings.insert(0, line.strip()[:200])
        if "ERROR |" in line or "CRITICAL |" in line:
            errors.insert(0, line.strip()[:200])

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

    msg_log_path = os.path.join(os.path.dirname(log_path), "messages.log")
    msg_log_events = _parse_messages_log_tail(msg_log_path, nodes)
    if msg_log_events:
        merged = {e["time"]: e for e in recent_messages}
        for e in msg_log_events:
            if e["time"] not in merged:
                if e.get("dir") == "out":
                    message_types["Ausgehend"] += 1
                else:
                    message_types["Eingehend"] += 1
            merged.setdefault(e["time"], e)
        recent_messages = sorted(merged.values(), key=lambda x: x["time"])

    stats["command_counts"] = command_counts
    stats["message_types"] = message_types
    stats["hourly_activity"] = dict(hourly)
    stats["unique_users"] = list(unique_users)[-30:]
    stats["warnings"] = warnings[:15]
    stats["errors"] = errors[:15]
    stats["command_timestamps"] = command_timestamps[-40:]
    stats["message_timestamps"] = message_timestamps[-40:]
    stats["recent_messages"] = recent_messages[-40:]
    stats["bbs_dm_delivered"] = bbs_dm_delivered[-25:]
    stats["bbs_dm_queued"] = bbs_dm_queued[-50:]
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


def _format_bbs_node_id(from_node: Any) -> str:
    try:
        return f"!{int(from_node):08x}"
    except (TypeError, ValueError):
        return str(from_node) if from_node else "?"


def _format_bbs_public_line(entry: List[Any]) -> str:
    mid = entry[0] if entry else "?"
    subject = str(entry[1]).strip()[:120] if len(entry) > 1 else "—"
    body = (str(entry[2]).strip().replace("\n", " ") if len(entry) > 2 else "")[:100]
    if len(entry) > 2 and len(str(entry[2])) > 100:
        body += "…"
    from_node = _format_bbs_node_id(entry[3] if len(entry) > 3 else 0)
    when_raw = str(entry[4]) if len(entry) > 4 else ""
    try:
        when = datetime.strptime(when_raw[:19], "%Y-%m-%d %H:%M:%S").strftime("%d.%m %H:%M")
    except ValueError:
        when = when_raw[-8:] if when_raw else ""
    line = f"{when} · #{mid} · {subject} · {from_node}"
    if body:
        line += f" — {body}"
    return line


def _render_bbs_public_html(messages: List[List[Any]], *, enabled: bool) -> str:
    if not enabled:
        return '<p class="text-muted small mb-0">Mesh-BBS ist deaktiviert.</p>'
    if not messages:
        return '<p class="text-muted small mb-0">Keine öffentlichen Nachrichten.</p>'
    lines = [_format_bbs_public_line(m) for m in reversed(messages[-25:])]
    return (
        '<ul class="dash-list dash-scroll mb-0">'
        + "".join(f"<li>{html_escape(line)}</li>" for line in lines)
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
    """Decimal node ID, short name, and hex for dashboard display."""
    try:
        nid = int(node_id)
    except (TypeError, ValueError):
        return str(node_id) if node_id not in (None, "") else "—"
    short = ""
    try:
        from modules.system import get_name_from_number

        short = str(get_name_from_number(nid, "short", 1) or "").strip()
    except Exception:
        pass
    hex_id = f"!{nid:08x}"
    if short and short != str(nid):
        return f"{nid} · {short} · {hex_id}"
    return f"{nid} · {hex_id}"


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


def _render_bbs_dm_meta_html(
    *,
    from_id: Any,
    to_id: Any,
    sent: str,
    received: str,
) -> str:
    von = html_escape(_bbs_dm_party_label(from_id))
    an = html_escape(_bbs_dm_party_label(to_id))
    sent_disp = html_escape(_format_dm_timestamp(sent))
    recv_disp = html_escape(_format_dm_timestamp(received))
    return (
        '<div class="dash-dm-meta">'
        f'<div class="dash-dm-row"><span class="dash-dm-k">Von</span><span class="dash-dm-v">{von}</span></div>'
        f'<div class="dash-dm-row"><span class="dash-dm-k">An</span><span class="dash-dm-v">{an}</span></div>'
        f'<div class="dash-dm-row"><span class="dash-dm-k">Abgesendet</span><span class="dash-dm-v">{sent_disp}</span></div>'
        f'<div class="dash-dm-row"><span class="dash-dm-k">Empfangen</span><span class="dash-dm-v">{recv_disp}</span></div>'
        "</div>"
    )


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
        meta = _render_bbs_dm_meta_html(
            from_id=from_id,
            to_id=to_id,
            sent=sent,
            received="",
        )
        items.append(
            f'<li class="dash-dm-item">{meta}{_bbs_dm_status_badge("waiting")}</li>'
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
        meta = _render_bbs_dm_meta_html(
            from_id=from_id or "—",
            to_id=to_id or "—",
            sent=sent,
            received=received,
        )
        items.append(
            f'<li class="dash-dm-item">{meta}{_bbs_dm_status_badge("delivered")}</li>'
        )
    if not items:
        return '<p class="text-muted small mb-0">Keine BBS-DMs.</p>'
    return '<ul class="dash-list dash-scroll mb-0">' + "".join(items) + "</ul>"


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


def _load_mesh_leaderboard() -> Dict[str, Any]:
    try:
        from modules.system import loadLeaderboard, meshLeaderboard

        loadLeaderboard()
        if meshLeaderboard:
            return dict(meshLeaderboard)
    except Exception:
        pass
    pkl = path_in_repo("data/leaderboard.pkl")
    if os.path.isfile(pkl):
        try:
            with open(pkl, "rb") as f:
                loaded = pickle.load(f)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {}


def _leaderboard_web_rows(lb: Dict[str, Any]) -> List[str]:
    """Human-readable mesh leaderboard lines for the public dashboard."""
    specs = [
        ("mostMessages", "💬 Meiste Nachrichten", lambda r: str(int(r["value"]))),
        ("mostTMessages", "📊 Meiste Telemetrie", lambda r: str(int(r["value"]))),
        ("lowestBattery", "🪫 Niedrigster Akku", lambda r: f"{round(float(r['value']), 1)} %"),
        ("longestUptime", "🕰️ Längste Laufzeit", lambda r: str(int(float(r["value"])))),
        ("highestDBm", "📶 Bestes SNR", lambda r: f"{r['value']} dB"),
        ("weakestDBm", "📶 Schwächstes SNR", lambda r: f"{r['value']} dB"),
        ("fastestSpeed", "🚓 Höchstgeschwindigkeit", lambda r: f"{round(float(r['value']), 1)} km/h"),
        ("highestAltitude", "🚀 Höchste Höhe", lambda r: f"{int(round(float(r['value'])))} m"),
        ("coldestTemp", "🥶 Kälteste Temperatur", lambda r: f"{round(float(r['value']), 1)} °C"),
        ("hottestTemp", "🥵 Heißeste Temperatur", lambda r: f"{round(float(r['value']), 1)} °C"),
    ]
    lines: List[str] = []
    for key, title, fmt in specs:
        rec = lb.get(key)
        if not isinstance(rec, dict) or rec.get("nodeID") is None:
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


def _render_mesh_leaderboard_html(lb: Dict[str, Any]) -> str:
    lines = _leaderboard_web_rows(lb)
    if not lines:
        return '<p class="text-muted small mb-0">Noch keine Leaderboard-Daten.</p>'
    return (
        '<ul class="dash-list dash-scroll mb-0">'
        + "".join(f"<li>{html_escape(line)}</li>" for line in lines)
        + "</ul>"
    )


def _render_toplist_html(cmd: Counter, lb: Dict[str, Any]) -> str:
    cmd_rows = cmd.most_common(10)
    msg_counts = lb.get("nodeMessageCounts") if isinstance(lb.get("nodeMessageCounts"), dict) else {}
    top_nodes = sorted(msg_counts.items(), key=lambda x: int(x[1]), reverse=True)[:10]

    cmd_items = (
        "".join(
            f"<li>{html_escape(name)} · {cnt}</li>" for name, cnt in cmd_rows
        )
        if cmd_rows
        else '<li class="text-muted">Keine Befehle im Log</li>'
    )
    node_items = (
        "".join(
            f"<li>{html_escape(_resolve_node_label(nid))} · {cnt}</li>"
            for nid, cnt in top_nodes
        )
        if top_nodes
        else '<li class="text-muted">Noch keine Mesh-Zähler</li>'
    )
    return f"""
<div class="row g-3">
  <div class="col-md-6">
    <h3 class="h6 text-muted mb-2">Top-Befehle (Log)</h3>
    <ul class="dash-list dash-scroll mb-0">{cmd_items}</ul>
  </div>
  <div class="col-md-6">
    <h3 class="h6 text-muted mb-2">Aktivste Knoten (Mesh)</h3>
    <ul class="dash-list dash-scroll mb-0">{node_items}</ul>
  </div>
</div>
"""


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


def collect_dashboard(log_dir: str) -> Dict[str, Any]:
    base = log_dir if os.path.isabs(log_dir) else path_in_repo(log_dir)
    log_path = os.path.join(base, "meshbot.log")
    if not os.path.isfile(log_path):
        log_path = path_in_repo("logs/meshbot.log")
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repo": repo_root(),
        "log_path": log_path,
        "log": parse_meshbot_log(log_path),
        "runtime": collect_runtime_stats(),
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
                "<tr>"
                f"<td><code>{r['node_id']}</code></td>"
                f"<td>{r['shortName']}{local}</td>"
                f"<td>{r['longName']}</td>"
                f'<td class="text-nowrap">{html_escape(str(r.get("lastHeard", "—")))}</td>'
                "</tr>"
            )
        parts.append(
            f"""
<h3 class="h6 section-title mb-2">
  <i class="bi bi-reception-4 text-success me-1"></i>Interface {iface}
  <span class="text-muted fw-normal">({len(rows)} Knoten)</span>
</h3>
<div class="table-scroll dash-nodedb-scroll mb-3">
  <table class="nodes-table table table-sm table-hover mb-0">
    <thead>
      <tr>
        <th>Node ID</th>
        <th>Kurzname</th>
        <th>Name</th>
        <th>Zuletzt gehört</th>
      </tr>
    </thead>
    <tbody>{"".join(trs)}</tbody>
  </table>
</div>"""
        )
    return "".join(parts)


def _message_list_items(entries: List[Dict[str, Any]], empty: str = "Keine Nachrichten") -> str:
    if not entries:
        return f'<li class="text-muted">{html_escape(empty)}</li>'
    lines = [_format_message_line(e) for e in reversed(entries[-12:])]
    return "".join(f"<li>{html_escape(line)}</li>" for line in lines)


def render_dashboard_page(data: Dict[str, Any]) -> str:
    log = data["log"]
    rt = data["runtime"]
    raw_cmd = log.get("command_counts") or {}
    cmd: Counter = raw_cmd if isinstance(raw_cmd, Counter) else Counter(raw_cmd)
    top_cmds = cmd.most_common(12)
    raw_msg = log.get("message_types") or {}
    msg_types: Counter = raw_msg if isinstance(raw_msg, Counter) else Counter(raw_msg)
    msg_keys = list(msg_types.keys())
    activity_labels, activity_values = _activity_series(log.get("hourly_activity") or {})
    lb = rt.get("mesh_leaderboard") or {}
    chart_data_json = json.dumps(
        {
            "cmdLabels": [c[0] for c in top_cmds],
            "cmdValues": [c[1] for c in top_cmds],
            "msgLabels": msg_keys,
            "msgValues": [int(msg_types[k]) for k in msg_keys],
            "activityLabels": activity_labels,
            "activityValues": activity_values,
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
    msg_chart_body = (
        '<div class="chart-canvas-wrap"><canvas id="msgChart"></canvas></div>'
        if msg_keys
        else '<p class="text-muted small mb-0">Noch keine Nachrichten im Log.</p>'
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
        _metric_card("Warnungen", str(len(log["warnings"])), "Log"),
        _metric_card("Fehler", str(len(log["errors"])), "Log"),
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
    toplist_html = _render_toplist_html(cmd, lb)
    leaderboard_html = _render_mesh_leaderboard_html(lb)
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
      <a href="/" class="btn btn-success">
        <i class="bi bi-arrow-clockwise me-2"></i>Aktualisieren
      </a>
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

<div class="row g-3 mb-4">
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-bar-chart text-success me-2"></i>Top-Befehle</h2>
      {cmd_chart_body}
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-pie-chart text-success me-2"></i>Nachrichtentypen</h2>
      {msg_chart_body}
    </div>
  </div>
</div>

<div class="row g-3 mb-4">
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-trophy me-2 text-success"></i>Topliste</h2>
      {toplist_html}
    </div>
  </div>
  <div class="col-lg-6">
    <div class="section-card">
      <h2 class="section-title h5"><i class="bi bi-award me-2 text-success"></i>Leaderboard</h2>
      <p class="small text-muted mb-2">Mesh-Rekorde seit letztem Reset</p>
      {leaderboard_html}
    </div>
  </div>
</div>

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
  <p class="small text-muted mb-2">Betreff, Absender und Vorschau · neueste zuerst</p>
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
<script src="/static/portal/dashboard-views.js"></script>
"""

