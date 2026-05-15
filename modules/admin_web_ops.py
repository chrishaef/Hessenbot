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


BROADCAST_MODES = [
    ("day", "Täglich zur Uhrzeit"),
    ("hour", "Alle N Stunden"),
    ("min", "Alle N Minuten"),
    ("mon", "Montags zur Uhrzeit"),
    ("tue", "Dienstags zur Uhrzeit"),
    ("wed", "Mittwochs zur Uhrzeit"),
    ("thu", "Donnerstags zur Uhrzeit"),
    ("fri", "Freitags zur Uhrzeit"),
    ("sat", "Samstags zur Uhrzeit"),
    ("sun", "Sonntags zur Uhrzeit"),
]

_WEEKDAY_MODES = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})


def parse_broadcast_schedule_form(form) -> Tuple[bool, int, int, str, str, str]:
    enabled = form.get("bc_enabled") == "on"
    iface = int(form.get("bc_interface", "1"))
    channel = int(form.get("bc_channel", "0"))
    mode = (form.get("bc_mode") or "day").strip().lower()
    interval = (form.get("bc_interval") or "1").strip()
    sched_time = (form.get("bc_time") or "").strip()
    return enabled, iface, channel, mode, interval, sched_time


def validate_broadcast_schedule(mode: str, interval: str, sched_time: str) -> Optional[str]:
    mode = (mode or "").strip().lower()
    if mode in ("day",) | _WEEKDAY_MODES and not sched_time:
        return "Bitte eine Uhrzeit (HH:MM) angeben."
    if mode in ("hour", "min"):
        try:
            if int(interval or "0") < 1:
                return "Intervall muss mindestens 1 sein."
        except ValueError:
            return "Intervall muss eine Zahl sein."
    if sched_time and len(sched_time) >= 5:
        parts = sched_time.split(":")
        if len(parts) != 2:
            return "Uhrzeit im Format HH:MM (z. B. 09:30)."
        try:
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                return "Uhrzeit ungültig (00:00–23:59)."
        except ValueError:
            return "Uhrzeit ungültig."
    return None


def broadcast_schedule_form_html(
    *,
    enabled: bool,
    iface: int,
    channel: int,
    mode: str,
    interval: str,
    sched_time: str,
    config_section: str,
) -> str:
    chk = " checked" if enabled else ""
    cur = (mode or "day").strip().lower()
    opts = ['<select name="bc_mode" class="form-select mb-2" required>']
    for val, label in BROADCAST_MODES:
        sel = " selected" if cur == val else ""
        opts.append(
            f'<option value="{html.escape(val, quote=True)}"{sel}>{html.escape(label)}</option>'
        )
    opts.append("</select>")
    ivl = html.escape(str(interval or "1"))
    tim = html.escape(str(sched_time or ""))
    sec = html.escape(config_section)
    return f"""
<hr class="my-4">
<h2 class="h5 mb-3">Automatischer Versand</h2>
<p class="text-muted small">Einstellungen in <code>config.ini</code> → <code>[{sec}]</code>.
Unabhängig vom allgemeinen Scheduler.</p>
<div class="form-check mb-3">
  <input class="form-check-input" type="checkbox" name="bc_enabled" id="bc_en"{chk}>
  <label class="form-check-label" for="bc_en">Automatisch senden</label>
</div>
<div class="row mb-2">
  <div class="col-md-6"><label class="form-label">Interface (Radio)</label>
    <input type="number" name="bc_interface" class="form-control" min="1" max="9" value="{iface}"></div>
  <div class="col-md-6"><label class="form-label">Kanal</label>
    <input type="number" name="bc_channel" class="form-control" value="{channel}"></div>
</div>
<label class="form-label">Rhythmus</label>
{"".join(opts)}
<label class="form-label">Intervall</label>
<input type="number" name="bc_interval" class="form-control mb-2" min="1" step="1" value="{ivl}">
<p class="small text-muted mb-2">
  <strong>day:</strong> Intervall = alle N Tage (1 = täglich), Uhrzeit erforderlich.
  <strong>hour / min:</strong> alle N Stunden bzw. Minuten.
  <strong>Mo–So:</strong> Uhrzeit erforderlich.
</p>
<label class="form-label">Uhrzeit (HH:MM)</label>
<input type="text" name="bc_time" class="form-control mb-3" placeholder="z. B. 09:00" value="{tim}"
       pattern="[0-2][0-9]:[0-5][0-9]" title="Format 00:00 bis 23:59">
"""


def save_motd_broadcast_to_config(
    enabled: bool, iface: int, channel: int, mode: str, interval: str, sched_time: str
) -> None:
    _save_broadcast_section(
        "motdBroadcast", enabled, iface, channel, mode, interval, sched_time, prefix="motd_broadcast"
    )


def save_news_broadcast_to_config(
    enabled: bool, iface: int, channel: int, mode: str, interval: str, sched_time: str
) -> None:
    _save_broadcast_section(
        "newsBroadcast", enabled, iface, channel, mode, interval, sched_time, prefix="news_broadcast"
    )


def _save_broadcast_section(
    section: str,
    enabled: bool,
    iface: int,
    channel: int,
    mode: str,
    interval: str,
    sched_time: str,
    *,
    prefix: str,
) -> None:
    import modules.settings as st

    if section not in st.config:
        st.config[section] = {}
    sec = st.config[section]
    sec["enabled"] = "True" if enabled else "False"
    sec["interface"] = str(iface)
    sec["channel"] = str(channel)
    sec["mode"] = mode.strip().lower()
    sec["interval"] = interval.strip()
    sec["time"] = sched_time.strip()
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    setattr(st, f"{prefix}_enabled", enabled)
    setattr(st, f"{prefix}_interface", iface)
    setattr(st, f"{prefix}_channel", channel)
    setattr(st, f"{prefix}_mode", sec["mode"])
    setattr(st, f"{prefix}_interval", sec["interval"])
    setattr(st, f"{prefix}_time", sec["time"])


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
    from modules.system import bbs_ban_list_file_path

    return bbs_ban_list_file_path()


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
    import modules.system as sysm
    from modules.system import save_bbsBanList

    cleaned: List[str] = []
    seen: set[str] = set()
    for raw in node_ids:
        nid = normalize_ban_node_id(str(raw))
        if not nid or nid in seen:
            continue
        seen.add(nid)
        cleaned.append(nid)

    st.bbs_ban_list.clear()
    st.bbs_ban_list.extend(cleaned)
    if sysm.bbs_ban_list is not st.bbs_ban_list:
        sysm.bbs_ban_list = st.bbs_ban_list

    if not save_bbsBanList():
        raise OSError(f"Keine Schreibrechte für {ban_list_file_path()}")

    if "bbs" not in st.config:
        st.config["bbs"] = {}
    st.config["bbs"]["bbs_ban_list"] = ",".join(cleaned)
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    return cleaned


def rebuild_scheduler_jobs() -> None:
    """Clear all schedule jobs and rebuild main scheduler plus MOTD/News broadcasts."""
    import schedule
    from modules.scheduler import setup_all_scheduled_jobs

    import modules.settings as st

    schedule.clear()
    setup_all_scheduled_jobs(
        st.schedulerMotd,
        st.MOTD,
        st.schedulerMessage,
        st.schedulerChannel,
        st.schedulerInterface,
        st.schedulerValue,
        st.schedulerTime,
        st.schedulerInterval,
    )
