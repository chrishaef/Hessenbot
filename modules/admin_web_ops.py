#!/usr/bin/env python3
# Helpers for web admin: Meshtastic NodeDB, config.ini (MOTD, scheduler), runtime scheduler refresh.

from __future__ import annotations

import html
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.paths import path_in_repo


def _system_mod():
    import modules.system as system_mod

    return system_mod


def iter_radio_interfaces() -> List[int]:
    """1..9 interface indices that are enabled and have a live object."""
    sm = _system_mod()
    out = []
    for i in range(1, 10):
        if not sm.__dict__.get(f"interface{i}_enabled"):
            continue
        if sm.__dict__.get(f"interface{i}") is not None:
            out.append(i)
    return out


def list_node_rows(iface_id: int) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Return (error_message or None, rows dicts for template)."""
    from modules.system import decimal_to_hex

    sm = _system_mod()
    iface = sm.__dict__.get(f"interface{iface_id}")
    if iface is None:
        return f"Interface {iface_id} ist nicht initialisiert.", []
    if not sm.__dict__.get(f"interface{iface_id}_enabled"):
        return f"Interface {iface_id} ist deaktiviert.", []
    nodes = getattr(iface, "nodes", None) or {}
    myn = sm.__dict__.get(f"myNodeNum{iface_id}", 777)
    rows: List[Dict[str, Any]] = []
    for node in nodes.values():
        num = node.get("num")
        if num is None:
            continue
        user = node.get("user") or {}
        short_n = html.escape(str(user.get("shortName", "")))
        long_n = html.escape(str(user.get("longName", "")))
        lh = node.get("lastHeard") or 0
        try:
            lh_s = time.strftime("%Y-%m-%d %H:%M", time.localtime(lh)) if lh else "—"
        except (OverflowError, OSError, TypeError):
            lh_s = "—"
        snr = node.get("snr", "")
        is_self = num == myn
        try:
            node_id_disp = html.escape(decimal_to_hex(int(num)))
        except (TypeError, ValueError):
            node_id_disp = "—"
        rows.append(
            {
                "num": num,
                "node_id": node_id_disp,
                "shortName": short_n,
                "longName": long_n,
                "lastHeard": lh_s,
                "lastHeard_raw": lh or 0,
                "snr": snr,
                "is_self": is_self,
            }
        )
    rows.sort(key=lambda r: r.get("lastHeard_raw", 0), reverse=True)
    return None, rows


def nodedb_row_search_text(row: Dict[str, Any]) -> str:
    """Plain-text blob for client-side NodeDB table filtering."""
    parts: List[str] = []
    num = row.get("num")
    if num is not None:
        parts.append(str(num))
        try:
            parts.append(f"!{int(num):08x}")
        except (TypeError, ValueError):
            pass
    for key in ("node_id", "shortName", "longName", "lastHeard", "snr"):
        val = row.get(key)
        if val is None:
            continue
        text = html.unescape(str(val)).strip()
        if text and text != "—":
            parts.append(text)
    return " ".join(parts).lower()


def nodedb_row_search_attr(row: Dict[str, Any]) -> str:
    return f' data-search="{html.escape(nodedb_row_search_text(row), quote=True)}"'


def nodedb_search_toolbar_html(*, placeholder: str = "Knoten suchen (ID, Name, …)") -> str:
    ph = html.escape(placeholder)
    return f"""
<div class="nodedb-search-toolbar mb-2">
  <div class="input-group input-group-sm">
    <span class="input-group-text" aria-hidden="true"><i class="bi bi-search"></i></span>
    <input type="search" class="form-control nodedb-search-input" placeholder="{ph}"
           autocomplete="off" spellcheck="false" aria-label="NodeDB durchsuchen">
    <span class="input-group-text nodedb-search-count text-muted" aria-live="polite"></span>
  </div>
</div>"""


def remove_node_from_radio(iface_id: int, node_num: int) -> str:
    """Remove a node from the radio's NodeDB (Admin message). Returns user-facing German status."""
    from meshtastic import LOCAL_ADDR

    sm = _system_mod()
    iface = sm.__dict__.get(f"interface{iface_id}")
    if iface is None:
        return "Interface nicht verbunden."
    myn = sm.__dict__.get(f"myNodeNum{iface_id}", 777)
    if node_num == myn:
        return "Der eigene Knoten kann nicht aus der NodeDB entfernt werden."
    try:
        iface.getNode(LOCAL_ADDR, requestChannels=False, timeout=90).removeNode(node_num)
    except Exception as e:
        return f"Fehler beim Entfernen: {e!s}"
    return "Knoten wurde entfernt (sofern das Gerät die Admin-Anfrage akzeptiert hat)."


def save_motd_to_config(motd: str) -> None:
    import modules.settings as st

    text = motd.replace("\r\n", "\n").strip()
    if "general" not in st.config:
        st.config["general"] = {}
    st.config["general"]["motd"] = text
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)
    st.MOTD = text


def save_scheduler_to_config(
    enabled: bool,
    iface: int,
    channel: int,
    message: str,
    scheduler_motd: bool,
    value: str,
    interval: str,
    sched_time: str,
) -> None:
    import modules.settings as st

    if "scheduler" not in st.config:
        st.config["scheduler"] = {}
    sec = st.config["scheduler"]
    sec["enabled"] = "True" if enabled else "False"
    sec["interface"] = str(iface)
    sec["channel"] = str(channel)
    sec["message"] = message.replace("\r\n", "\n")
    sec["schedulerMotd"] = "True" if scheduler_motd else "False"
    sec["value"] = value.strip()
    sec["interval"] = interval.strip()
    sec["time"] = sched_time.strip()
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    st.scheduler_enabled = enabled
    st.schedulerInterface = iface
    st.schedulerChannel = channel
    st.schedulerMessage = sec["message"]
    st.schedulerMotd = scheduler_motd
    st.schedulerValue = sec["value"]
    st.schedulerInterval = sec["interval"]
    st.schedulerTime = sec["time"]


def ban_list_file_path() -> str:
    return path_in_repo("data/bbs_ban_list.txt")


def normalize_ban_node_id(raw: str) -> Optional[str]:
    """Accept decimal node ID or !xxxxxxxx hex."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("!"):
        try:
            return str(int(text[1:], 16))
        except ValueError:
            return None
    if text.isdigit():
        return text
    return None


def read_ban_list_file() -> List[str]:
    path = ban_list_file_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError:
        return []


def ban_node_label(node_id: str) -> str:
    try:
        nid = int(node_id)
        from modules.system import get_name_from_number

        name = get_name_from_number(nid, "short", 1)
        hex_id = f"!{nid:08x}"
        if name and str(name).strip() and str(name) != str(nid):
            return f"{name} · {hex_id}"
        return hex_id
    except (TypeError, ValueError):
        return str(node_id)


def reload_ban_list_runtime() -> List[str]:
    """Reload in-memory list from disk (replaces runtime list with file contents)."""
    import modules.settings as st
    from modules.system import load_bbsBanList

    file_ids = read_ban_list_file()
    st.bbs_ban_list = list(file_ids)
    if not file_ids:
        load_bbsBanList()
        return list(st.bbs_ban_list)
    return file_ids


def save_ban_list(node_ids: List[str]) -> List[str]:
    """Persist ban list to data/bbs_ban_list.txt, config.ini, and runtime settings."""
    import modules.settings as st
    from modules.system import save_bbsBanList

    cleaned: List[str] = []
    seen: set[str] = set()
    for raw in node_ids:
        nid = normalize_ban_node_id(str(raw))
        if not nid or nid in seen:
            continue
        seen.add(nid)
        cleaned.append(nid)

    st.bbs_ban_list = cleaned
    path = ban_list_file_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for nid in cleaned:
            fh.write(f"{nid}\n")

    if "bbs" not in st.config:
        st.config["bbs"] = {}
    st.config["bbs"]["bbs_ban_list"] = ",".join(cleaned)
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    save_bbsBanList()
    return cleaned


def rebuild_scheduler_jobs() -> None:
    """Clear schedule jobs and rebuild from modules.settings (no-op if scheduler disabled)."""
    import modules.settings as st

    if not st.scheduler_enabled:
        return
    import schedule
    from modules.scheduler import setup_scheduler

    schedule.clear()
    setup_scheduler(
        st.schedulerMotd,
        st.MOTD,
        st.schedulerMessage,
        st.schedulerChannel,
        st.schedulerInterface,
        st.schedulerValue,
        st.schedulerTime,
        st.schedulerInterval,
    )
