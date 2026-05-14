#!/usr/bin/env python3
# Helpers for web admin: Meshtastic NodeDB, config.ini (MOTD, scheduler), runtime scheduler refresh.

from __future__ import annotations

import html
import time
from typing import Any, Dict, List, Optional, Tuple


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
