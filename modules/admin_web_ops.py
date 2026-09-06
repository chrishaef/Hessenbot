#!/usr/bin/env python3
# Helpers for web admin: Meshtastic NodeDB, config.ini (MOTD, scheduler), runtime scheduler refresh.

from __future__ import annotations

import base64
import html
import os
import re
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


def _parse_node_gps(node: Dict[str, Any]) -> Tuple[bool, Optional[float], Optional[float]]:
    """True if NodeDB has a non-zero latitude/longitude on the node."""
    pos = node.get("position")
    if not pos or not isinstance(pos, dict):
        return False, None, None
    if pos.get("latitude") is None or pos.get("longitude") is None:
        return False, None, None
    try:
        lat = float(pos["latitude"])
        lon = float(pos["longitude"])
    except (TypeError, ValueError):
        return False, None, None
    if lat == 0.0 and lon == 0.0:
        return False, None, None
    return True, lat, lon


def format_node_location_html(
    has_position: bool,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    *,
    source: str = "gps",
) -> str:
    if not has_position or lat is None or lon is None:
        return '<span class="text-muted" title="Keine Position (weder NodeDB noch Mesh-Karte)">—</span>'
    coords = html.escape(f"{lat:.5f}, {lon:.5f}")
    if source == "map":
        badge = (
            '<span class="badge bg-info me-1" title="Position aus Mesh-Karte (nodes.json)">Karte</span>'
        )
    else:
        badge = '<span class="badge bg-success me-1" title="Position in der NodeDB">GPS</span>'
    return f'{badge}<code class="small text-nowrap">{coords}</code>'


def _map_position_for_node(node_num: int) -> Tuple[bool, Optional[float], Optional[float]]:
    sm = _system_mod()
    try:
        sm._ensure_mesh_map_positions_loaded()
        snap = sm.mesh_map_node_positions.get(int(node_num))
        if not snap:
            return False, None, None
        lat = float(snap["lat"])
        lon = float(snap["lon"])
        if lat == 0.0 and lon == 0.0:
            return False, None, None
        return True, lat, lon
    except Exception:
        return False, None, None


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
        has_gps, lat, lon = _parse_node_gps(node)
        loc_source = "gps"
        if not has_gps:
            has_map, lat, lon = _map_position_for_node(int(num))
            if has_map:
                has_gps = True
                loc_source = "map"
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
                "has_gps": has_gps,
                "location_source": loc_source,
                "location_html": format_node_location_html(
                    has_gps, lat, lon, source=loc_source
                ),
            }
        )
    rows.sort(key=lambda r: r.get("lastHeard_raw", 0), reverse=True)
    _enrich_blitzwatch_rows(rows)
    return None, rows


def _enrich_blitzwatch_rows(rows: List[Dict[str, Any]]) -> None:
    """Attach blitzwatch_html / blitzwatch_active for NodeDB tables."""
    import modules.settings as st

    global_on = bool(getattr(st, "blitz_watch_enabled", True)) and bool(
        getattr(st, "location_enabled", True)
    )
    prefs_map: Dict[int, Dict[str, Any]] = {}
    if global_on:
        try:
            from modules.blitzwatch import get_all_prefs_map, get_node_prefs

            prefs_map = get_all_prefs_map()
        except Exception:
            prefs_map = {}

    for r in rows:
        if r.get("is_self"):
            r["blitzwatch_active"] = False
            r["blitzwatch_html"] = (
                '<span class="badge bg-secondary" title="Bot-Node ausgeschlossen">'
                "—</span>"
            )
            continue
        if not global_on:
            r["blitzwatch_active"] = False
            r["blitzwatch_html"] = (
                '<span class="badge bg-secondary" title="Blitzwatch global aus">aus</span>'
            )
            continue
        try:
            nid = int(r["num"])
        except (TypeError, ValueError, KeyError):
            r["blitzwatch_active"] = False
            r["blitzwatch_html"] = "—"
            continue
        prefs = prefs_map.get(nid)
        if prefs is None:
            try:
                from modules.blitzwatch import get_node_prefs

                prefs = get_node_prefs(nid)
            except Exception:
                prefs = {
                    "enabled": True,
                    "radius_km": 8,
                    "home_mode": "gps",
                    "extra_count": 0,
                }
        enabled = bool(prefs.get("enabled", True))
        radius = prefs.get("radius_km", 8)
        home_mode = (prefs.get("home_mode") or "gps").lower()
        home_fixed = home_mode == "fixed" and prefs.get("home_lat") is not None
        extra_count = int(prefs.get("extra_count") or 0)
        if "extra_count" not in prefs:
            try:
                from modules.blitzwatch import count_locations

                extra_count = count_locations(nid)
            except Exception:
                extra_count = 0
        has_fresh = False
        try:
            from modules.system import _nodedb_fresh_position

            has_fresh = bool(_nodedb_fresh_position(nid, 1, 2))
        except Exception:
            has_fresh = r.get("location_source") == "gps" and bool(r.get("has_gps"))
        home_active = home_fixed or has_fresh
        any_active = enabled and (home_active or extra_count > 0)
        # "bereit": enabled but only GPS-home and no GPS, and no extras
        only_waiting_gps = (
            enabled
            and not home_fixed
            and not has_fresh
            and extra_count == 0
        )
        tip_extra = f", {extra_count} Zusatzort(e)" if extra_count else ""
        if not enabled:
            r["blitzwatch_active"] = False
            r["blitzwatch_html"] = (
                f'<span class="badge bg-secondary" title="Opt-out (!blitzwatch off)">'
                f"aus</span>"
            )
        elif any_active:
            r["blitzwatch_active"] = True
            home_tip = "Fix" if home_fixed else f"GPS {radius}km"
            r["blitzwatch_html"] = (
                f'<span class="badge bg-success" '
                f'title="Blitzwatch aktiv — Home {home_tip}{tip_extra}">'
                f"an {radius}km"
                f'{f"+{extra_count}" if extra_count else ""}</span>'
            )
        elif only_waiting_gps:
            r["blitzwatch_active"] = False
            r["blitzwatch_html"] = (
                f'<span class="badge bg-warning text-dark" '
                f'title="Kein frisches GPS ≤24h — Radius {radius} km">'
                f"bereit {radius}km</span>"
            )
        else:
            r["blitzwatch_active"] = False
            r["blitzwatch_html"] = (
                f'<span class="badge bg-secondary" title="Blitzwatch inaktiv">aus</span>'
            )


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
    parts.append("gps" if row.get("has_gps") else "kein gps")
    if row.get("blitzwatch_active"):
        parts.append("blitzwatch an")
    else:
        parts.append("blitzwatch aus")
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
    ("day", "Alle N Tage zur Uhrzeit (1 = täglich)"),
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
_TIME_REQUIRED_MODES = frozenset({"day"}) | _WEEKDAY_MODES
_INTERVAL_MODES = frozenset({"day", "hour", "min"})


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
    if mode in _TIME_REQUIRED_MODES and not sched_time:
        return "Bitte eine Uhrzeit (HH:MM) angeben."
    if mode in _INTERVAL_MODES:
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


def channel_select_html(
    name: str,
    selected: int | str,
    *,
    iface_id: int | None = None,
    element_id: str | None = None,
    refresh: bool = False,
) -> str:
    """``<select>`` of mesh channels from the Meshtastic instance (radio cache)."""
    try:
        selected_n = int(selected)
    except (TypeError, ValueError):
        selected_n = 0
    try:
        channels = list_radio_channels(iface_id, refresh=refresh)
    except Exception:
        channels = []
    if not any(int(c["number"]) == selected_n for c in channels):
        channels = list(channels) + [
            {"number": selected_n, "label": f"Kanal {selected_n}"}
        ]
        channels.sort(key=lambda c: int(c["number"]))

    eid = element_id or name.replace("_", "-")
    parts = [
        f'<select name="{html.escape(name, quote=True)}" id="{html.escape(eid, quote=True)}" '
        f'class="form-select" required>'
    ]
    for ch in channels:
        num = int(ch["number"])
        label = str(ch.get("label") or f"Kanal {num}")
        sel = " selected" if num == selected_n else ""
        parts.append(
            f'<option value="{num}"{sel}>{html.escape(label)} (#{num})</option>'
        )
    parts.append("</select>")
    return "".join(parts)


def iface_select_html(
    name: str,
    selected: int | str,
    *,
    element_id: str | None = None,
) -> str:
    """``<select>`` of enabled radio interfaces (fallback 1–9 if none live)."""
    try:
        selected_n = int(selected)
    except (TypeError, ValueError):
        selected_n = 1
    try:
        ifaces = iter_radio_interfaces()
    except Exception:
        ifaces = []
    if not ifaces:
        ifaces = list(range(1, 10))
    if selected_n not in ifaces:
        ifaces = sorted(set(ifaces) | {selected_n})

    eid = element_id or name.replace("_", "-")
    parts = [
        f'<select name="{html.escape(name, quote=True)}" id="{html.escape(eid, quote=True)}" '
        f'class="form-select" required>'
    ]
    for i in ifaces:
        sel = " selected" if int(i) == selected_n else ""
        parts.append(f'<option value="{int(i)}"{sel}>Interface {int(i)}</option>')
    parts.append("</select>")
    return "".join(parts)


def _schedule_ui_block(
    *,
    mode_name: str,
    mode_select_html: str,
    interval_name: str,
    interval_value: str,
    time_name: str,
    time_value: str,
    heading: str = "Wann und wie oft?",
) -> str:
    """Shared adaptive interval/time controls (MOTD/News/Scheduler)."""
    ivl = html.escape(str(interval_value or "1"))
    tim = html.escape(str(time_value or ""))
    return f"""
<div class="schedule-ui border rounded p-3 mb-3" data-schedule-ui>
  <h3 class="h6 mb-3">{html.escape(heading)}</h3>
  <label class="form-label">Art des Zeitplans</label>
  {mode_select_html}
  <div class="row g-3 align-items-end mt-1" data-schedule-interval-row>
    <div class="col-sm-6 col-md-4">
      <label class="form-label" for="sched-interval-{html.escape(interval_name)}">Alle</label>
      <div class="input-group">
        <input type="number" class="form-control" name="{html.escape(interval_name)}"
               id="sched-interval-{html.escape(interval_name)}"
               data-schedule-interval min="1" step="1" value="{ivl}">
        <span class="input-group-text" data-schedule-unit>Tage</span>
      </div>
    </div>
  </div>
  <div class="mt-3" data-schedule-time-row>
    <label class="form-label" for="sched-time-{html.escape(time_name)}">Uhrzeit</label>
    <input type="time" class="form-control" style="max-width: 12rem"
           name="{html.escape(time_name)}" id="sched-time-{html.escape(time_name)}"
           data-schedule-time value="{tim}"
           title="Format HH:MM">
    <div class="form-text">Nur bei tages- oder uhrzeitbasierten Plänen nötig.</div>
  </div>
  <p class="schedule-ui-summary alert alert-secondary small py-2 px-3 mb-0 mt-3"
     data-schedule-summary role="status">…</p>
</div>
<script src="/static/portal/schedule-ui.js?v=1"></script>
"""


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
    opts = [
        '<select name="bc_mode" class="form-select" required data-schedule-mode>'
    ]
    opts.append('<optgroup label="Intervall / Uhrzeit">')
    for val, label in BROADCAST_MODES[:3]:
        sel = " selected" if cur == val else ""
        opts.append(
            f'<option value="{html.escape(val, quote=True)}"{sel}>{html.escape(label)}</option>'
        )
    opts.append("</optgroup>")
    opts.append('<optgroup label="Wochentag">')
    for val, label in BROADCAST_MODES[3:]:
        sel = " selected" if cur == val else ""
        opts.append(
            f'<option value="{html.escape(val, quote=True)}"{sel}>{html.escape(label)}</option>'
        )
    opts.append("</optgroup></select>")

    # Normalize HH:MM for type=time (needs HH:MM)
    tim = (sched_time or "").strip()
    if tim and len(tim) >= 4 and ":" in tim:
        parts = tim.split(":")
        try:
            tim = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        except ValueError:
            pass

    schedule_block = _schedule_ui_block(
        mode_name="bc_mode",
        mode_select_html="".join(opts),
        interval_name="bc_interval",
        interval_value=str(interval or "1"),
        time_name="bc_time",
        time_value=tim,
    )
    sec = html.escape(config_section)
    iface_sel = iface_select_html("bc_interface", iface, element_id="bc_interface")
    ch_sel = channel_select_html(
        "bc_channel", channel, iface_id=int(iface), element_id="bc_channel"
    )
    return f"""
<hr class="my-4">
<h2 class="h5 mb-3">Automatischer Versand</h2>
<p class="text-muted small mb-3">Einstellungen in <code>config.ini</code> → <code>[{sec}]</code>.
Unabhängig vom allgemeinen Scheduler. Kanäle kommen von der Meshtastic-Instanz.</p>
<div class="form-check mb-3">
  <input class="form-check-input" type="checkbox" name="bc_enabled" id="bc_en"{chk}>
  <label class="form-check-label" for="bc_en">Automatisch senden</label>
</div>
<div class="row mb-3">
  <div class="col-md-6"><label class="form-label" for="bc_interface">Interface (Radio)</label>
    {iface_sel}</div>
  <div class="col-md-6"><label class="form-label" for="bc_channel">Kanal</label>
    {ch_sel}</div>
</div>
{schedule_block}
"""


def scheduler_value_select_html(current_raw: str) -> str:
    """Grouped <select name=value> for the general scheduler."""
    cur_raw = (current_raw or "").strip()
    cur = cur_raw.lower()

    groups = [
        (
            "Nachricht senden",
            [
                ("day", "Alle N Tage zur Uhrzeit (1 = täglich)"),
                ("hour", "Alle N Stunden"),
                ("min", "Alle N Minuten"),
                ("mon", "Montags zur Uhrzeit"),
                ("tue", "Dienstags zur Uhrzeit"),
                ("wed", "Mittwochs zur Uhrzeit"),
                ("thu", "Donnerstags zur Uhrzeit"),
                ("fri", "Freitags zur Uhrzeit"),
                ("sat", "Samstags zur Uhrzeit"),
                ("sun", "Sonntags zur Uhrzeit"),
            ],
        ),
        (
            "Special Jobs",
            [
                ("weather", "Wetter — täglich zur Uhrzeit"),
                ("news", "News — alle N Stunden"),
                ("readrss", "RSS — alle N Stunden"),
                ("sysinfo", "Sysinfo — alle N Stunden"),
                ("solar", "Sonne — täglich zur Uhrzeit"),
                ("link", "bbslink — alle N Stunden"),
                ("custom", "Eigene Logik (custom_scheduler.py)"),
            ],
        ),
    ]

    parts = [
        '<select name="value" class="form-select" required data-schedule-mode>',
        '<option value="">— Zeitplantyp wählen —</option>',
    ]
    matched = False
    for group_label, items in groups:
        parts.append(f'<optgroup label="{html.escape(group_label)}">')
        for val, lab in items:
            sel = " selected" if cur == val else ""
            if sel:
                matched = True
            parts.append(
                f'<option value="{html.escape(val, quote=True)}"{sel}>{html.escape(lab)}</option>'
            )
        parts.append("</optgroup>")
    if cur_raw and not matched:
        parts.append(
            f'<option value="{html.escape(cur_raw, quote=True)}" selected>'
            f"Freitext: {html.escape(cur_raw)}</option>"
        )
    parts.append("</select>")
    return "".join(parts)


def scheduler_schedule_fields_html(*, value: str, interval: str, sched_time: str) -> str:
    """Adaptive interval/time block for the Scheduler tab."""
    tim = (sched_time or "").strip()
    if tim and len(tim) >= 4 and ":" in tim:
        parts = tim.split(":")
        try:
            tim = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        except ValueError:
            pass
    return _schedule_ui_block(
        mode_name="value",
        mode_select_html=scheduler_value_select_html(value),
        interval_name="interval",
        interval_value=str(interval or "1"),
        time_name="time",
        time_value=tim,
        heading="Wann und wie oft?",
    )


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


def available_channels_for_test() -> List[Dict[str, Any]]:
    """Channels known across interfaces as [{'number': int, 'label': str}], deduped by number."""
    return list_radio_channels()


def list_radio_channels(
    iface_id: int | None = None, *, refresh: bool = False
) -> List[Dict[str, Any]]:
    """Channels from Meshtastic instance(s): [{'number', 'label', 'role'}], sorted.

    Prefers live protobuf slots (real names / preset for unnamed PRIMARY).
    """
    sm = None
    try:
        sm = _system_mod()
        if refresh and hasattr(sm, "refresh_channel_cache"):
            sm.refresh_channel_cache()
    except Exception:
        sm = None

    seen: Dict[int, Dict[str, Any]] = {}

    iface_ids: List[int] = []
    if iface_id is not None:
        iface_ids = [int(iface_id)]
    else:
        try:
            iface_ids = iter_radio_interfaces()
        except Exception:
            iface_ids = []
        if not iface_ids:
            iface_ids = list(range(1, 10))

    for iid in iface_ids:
        slots = []
        if sm is not None and hasattr(sm, "read_interface_channel_slots"):
            try:
                slots = sm.read_interface_channel_slots(iid)
            except Exception:
                slots = []
        for slot in slots or []:
            if slot.get("role_name") not in ("PRIMARY", "SECONDARY"):
                continue
            num = int(slot["index"])
            label = (slot.get("label") or slot.get("name") or f"Kanal {num}").strip()
            prev = seen.get(num)
            if prev is None or (
                prev["label"].startswith("Kanal ") and not label.startswith("Kanal ")
            ):
                seen[num] = {
                    "number": num,
                    "label": label,
                    "role": slot.get("role_name") or "",
                }

    if not seen:
        # Cache fallback (names from last successful read)
        cache = []
        try:
            if sm is not None:
                cache = sm.build_channel_cache()
        except Exception:
            cache = []
        for entry in cache or []:
            if iface_id is not None and int(entry.get("interface_id") or 0) != int(iface_id):
                continue
            for name, info in (entry.get("channels") or {}).items():
                if not isinstance(info, dict):
                    continue
                num = info.get("number")
                if num is None:
                    continue
                try:
                    num = int(num)
                except (TypeError, ValueError):
                    continue
                label = (info.get("label") or name or "").strip()
                if not label or label.startswith("Channel"):
                    label = f"Kanal {num}"
                prev = seen.get(num)
                if prev is None or (
                    prev["label"].startswith("Kanal ") and not label.startswith("Kanal ")
                ):
                    seen[num] = {
                        "number": num,
                        "label": label,
                        "role": info.get("role") or "",
                    }

    if not seen:
        seen[0] = {"number": 0, "label": "Kanal 0", "role": "PRIMARY"}
        try:
            import modules.settings as st

            msg_ch = int(getattr(st, "messages_channel", 1) or 1)
        except Exception:
            msg_ch = 1
        if msg_ch not in seen:
            seen[msg_ch] = {
                "number": msg_ch,
                "label": f"Kanal {msg_ch}",
                "role": "SECONDARY",
            }

    return [seen[n] for n in sorted(seen)]


def save_channel_test_to_config(enabled: bool, channels: List[str]) -> None:
    """Persist [channelTest] enabled/channels and update live settings."""
    import modules.settings as st

    clean = [str(c).strip() for c in channels if str(c).strip()]
    if "channelTest" not in st.config:
        st.config["channelTest"] = {}
    st.config["channelTest"]["enabled"] = "True" if enabled else "False"
    st.config["channelTest"]["channels"] = ",".join(clean)
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    st.channel_test_enabled = enabled
    st.channel_test_channels = clean


_DEFAULT_EXPENSIVE_CMDS = (
    "wx,wxc,warning,dealert,blitz,uv,regen,trace,whereami,rlist,satpass,tide,river,earthquake"
)


def normalize_expensive_commands(raw: str) -> List[str]:
    """Parse comma/space-separated command tokens without leading !."""
    seen: List[str] = []
    for part in re.split(r"[,;\s]+", raw or ""):
        tok = part.strip().lower().lstrip("!").rstrip("?")
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def save_rate_limit_settings_to_config(
    *,
    enabled: bool,
    max_cmds: int,
    window_sec: int,
    notify_once: bool,
    expensive_cooldown: int,
    expensive_commands: List[str],
) -> bool:
    """Persist cmdRateLimit* / cmdExpensive* under [messagingSettings]; reload runtime."""
    import modules.settings as st

    max_cmds = max(1, int(max_cmds))
    window_sec = max(1, int(window_sec))
    expensive_cooldown = max(0, int(expensive_cooldown))
    cmds = [
        str(c).strip().lower().lstrip("!").rstrip("?")
        for c in expensive_commands
        if str(c).strip()
    ]
    # stable unique order
    seen: List[str] = []
    for c in cmds:
        if c not in seen:
            seen.append(c)

    st.config.read(st.config_file, encoding="utf-8")
    if "messagingSettings" not in st.config:
        st.config["messagingSettings"] = {}
    sec = st.config["messagingSettings"]
    sec["cmdRateLimitEnabled"] = "True" if enabled else "False"
    sec["cmdRateLimitMax"] = str(max_cmds)
    sec["cmdRateLimitWindow"] = str(window_sec)
    sec["cmdRateLimitNotifyOnce"] = "True" if notify_once else "False"
    sec["cmdExpensiveCooldownSec"] = str(expensive_cooldown)
    sec["cmdExpensiveCommands"] = ",".join(seen)
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    return reload_runtime_settings()


def build_limits_settings_html(
    *,
    enabled: bool,
    max_cmds: int,
    window_sec: int,
    notify_once: bool,
    expensive_cooldown: int,
    expensive_commands: List[str],
    form_action: str,
) -> str:
    """Settings form for Admin → Limits (airtime throttle)."""
    en_chk = " checked" if enabled else ""
    once_chk = " checked" if notify_once else ""
    cmds_s = ", ".join(expensive_commands) if expensive_commands else _DEFAULT_EXPENSIVE_CMDS
    action = html.escape(form_action, quote=True)
    return f"""
<div class="section-card mb-4 limits-settings-card">
  <h2 class="h5 mb-1">Befehls-Limits einstellen</h2>
  <p class="small text-muted mb-3">
    Schützt die Mesh-Airtime: zu viele Befehle pro Node werden begrenzt.
    Beim ersten Überschreiten eine kurze Hinweis-DM, danach still.
    Teure Befehle haben zusätzlich einen eigenen Cooldown.
  </p>
  <form method="post" action="{action}" class="limits-settings-form">
    <input type="hidden" name="action" value="save_limits">
    <div class="row g-3">
      <div class="col-lg-6">
        <div class="limits-settings-block">
          <h3 class="h6 text-uppercase text-muted mb-3">Global pro Node</h3>
          <div class="form-check form-switch mb-3">
            <input class="form-check-input" type="checkbox" name="cmdRateLimitEnabled"
                   id="limEnabled" value="1"{en_chk}>
            <label class="form-check-label" for="limEnabled">Rate-Limit aktiv</label>
          </div>
          <div class="row g-2 mb-2">
            <div class="col-6">
              <label class="form-label" for="limMax">Max. Befehle</label>
              <input type="number" class="form-control" name="cmdRateLimitMax" id="limMax"
                     min="1" max="100" step="1" value="{html.escape(str(max_cmds))}" required>
            </div>
            <div class="col-6">
              <label class="form-label" for="limWindow">Fenster (Sekunden)</label>
              <input type="number" class="form-control" name="cmdRateLimitWindow" id="limWindow"
                     min="1" max="3600" step="1" value="{html.escape(str(window_sec))}" required>
            </div>
          </div>
          <p class="small text-muted mb-3">
            Beispiel: <code>{html.escape(str(max_cmds))}</code> Befehle in
            <code>{html.escape(str(window_sec))}s</code> — der nächste löst den Hinweis aus.
          </p>
          <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" name="cmdRateLimitNotifyOnce"
                   id="limNotifyOnce" value="1"{once_chk}>
            <label class="form-check-label" for="limNotifyOnce">
              Nur ein Hinweis pro Fenster, danach still
            </label>
          </div>
          <p class="small text-muted mt-1 mb-0">
            Aus = bei jedem Limit-Treffer erneut „Bitte etwas langsamer.“ senden (mehr Airtime).
          </p>
        </div>
      </div>
      <div class="col-lg-6">
        <div class="limits-settings-block">
          <h3 class="h6 text-uppercase text-muted mb-3">Teure Befehle</h3>
          <label class="form-label" for="limCool">Cooldown (Sekunden)</label>
          <input type="number" class="form-control mb-2" name="cmdExpensiveCooldownSec"
                 id="limCool" min="0" max="3600" step="1"
                 value="{html.escape(str(expensive_cooldown))}" required>
          <p class="small text-muted mb-3">
            Mindestabstand zwischen gleichen teuren Befehlen desselben Nodes.
            <code>0</code> schaltet den Extra-Cooldown aus.
          </p>
          <label class="form-label" for="limCmds">Befehlsliste</label>
          <textarea class="form-control font-monospace" name="cmdExpensiveCommands"
                    id="limCmds" rows="4"
                    placeholder="{html.escape(_DEFAULT_EXPENSIVE_CMDS, quote=True)}">{html.escape(cmds_s)}</textarea>
          <p class="small text-muted mt-1 mb-0">
            Kommagetrennt, ohne <code>!</code>. Erster Treffer im Cooldown: kurze Restzeit-DM;
            Wiederholung: still. Admins (<code>isNodeAdmin</code>) sind ausgenommen.
          </p>
        </div>
      </div>
    </div>
    <div class="d-flex flex-wrap gap-2 align-items-center mt-4">
      <button type="submit" class="btn btn-success">Limits speichern</button>
      <span class="small text-muted">Wird sofort in <code>config.ini</code> und zur Laufzeit übernommen.</span>
    </div>
  </form>
</div>
"""


def build_channel_test_html(enabled: bool, selected: List[str]) -> str:
    """Form for the Channel-Test tab: toggle + channel checkboxes (with manual fallback)."""
    chk = " checked" if enabled else ""
    selected_set = {str(s).strip() for s in selected if str(s).strip()}
    avail = available_channels_for_test()

    if avail:
        boxes = []
        for ch in avail:
            num = str(ch["number"])
            sel = " checked" if num in selected_set else ""
            boxes.append(
                f'<div class="form-check">'
                f'<input class="form-check-input" type="checkbox" name="channels" '
                f'value="{html.escape(num, quote=True)}" id="ct{num}"{sel}>'
                f'<label class="form-check-label" for="ct{num}">'
                f'{html.escape(ch["label"])} <span class="text-muted">(#{num})</span></label></div>'
            )
        channel_block = (
            '<label class="form-label">Kanäle</label>'
            '<div class="mb-2">' + "".join(boxes) + "</div>"
        )
    else:
        channel_block = (
            '<label class="form-label">Kanäle (kommagetrennte Nummern)</label>'
            '<p class="small text-muted mb-2">Keine Kanäle vom Radio gelesen — '
            "Nummern manuell eintragen.</p>"
        )

    manual = html.escape(",".join(sorted(selected_set, key=lambda x: (len(x), x))))
    return f"""
<p class="text-muted small mb-3">Bei aktivierter Funktion antwortet der Bot auf ein einfaches
<code>test</code> / <code>Test</code> (ohne <code>!</code>) direkt im Kanal — gleiche Antwort wie
<code>!test</code>. Nach dem Anlegen eines neuen Kanals diese Seite neu laden und den Slot
hier erneut anhaken. Gilt nur für die ausgewählten Kanäle; alle anderen Befehle bleiben unverändert
(DM und <code>!</code>).</p>
<form method="post">
  <div class="form-check form-switch mb-3">
    <input class="form-check-input" type="checkbox" name="enabled" id="ctEnabled"{chk}>
    <label class="form-check-label" for="ctEnabled">Funktion aktiv</label>
  </div>
  {channel_block}
  <label class="form-label">Zusätzliche Kanal-Nummern (optional, kommagetrennt)</label>
  <input type="text" name="channels_manual" class="form-control mb-3" value="{manual}"
         placeholder="z. B. 2,3">
  <button type="submit" class="btn btn-success w-100">Speichern</button>
</form>
<p class="small text-muted mt-3">Einstellungen in <code>config.ini</code> → <code>[channelTest]</code>.</p>
"""


def runtime_file_permission_hint(path: str, *, bot_user: str = "meshbot") -> str:
    repo = path_in_repo("")
    return (
        f"Keine Schreibrechte für {path}. "
        f"Auf dem Server ausführen: "
        f"sudo bash etc/set-permissions.sh {bot_user} {repo}"
    )


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


def _clean_mesh_admin_ids(node_ids: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen: set[str] = set()
    for raw in node_ids:
        nid = normalize_ban_node_id(str(raw))
        if not nid or nid in seen:
            continue
        seen.add(nid)
        cleaned.append(nid)
    return cleaned


def read_mesh_admin_list() -> List[str]:
    import modules.settings as st

    return _clean_mesh_admin_ids(list(st.bbs_admin_list))


def save_mesh_admin_list(node_ids: List[str]) -> List[str]:
    """Persist mesh admin node IDs to config.ini [bbs] bbs_admin_list and runtime."""
    import modules.settings as st

    cleaned = _clean_mesh_admin_ids(node_ids)
    st.bbs_admin_list.clear()
    st.bbs_admin_list.extend(cleaned)

    if "bbs" not in st.config:
        st.config["bbs"] = {}
    st.config["bbs"]["bbs_admin_list"] = ",".join(cleaned)
    with open(st.config_file, "w", encoding="utf-8") as fh:
        st.config.write(fh)

    return cleaned


_CONFIG_ATTR_ALIASES = {
    "respond_by_dm_only": "useDMForResponse",
    "filemon_enabled": "file_monitor_enabled",
    "LogBackupCount": "log_backup_count",
    "log_backup_count": "log_backup_count",
    "lheardCmdIgnoreNodes": "lheardCmdIgnoreNode",
    "lheardCmdIgnoreNode": "lheardCmdIgnoreNode",
    "fuzzAllLocations": "fuzzItAll",
    "fuzzItAll": "fuzzItAll",
    "sentryAlertAway": "sentryAlertFar",
    "sentryAlertFar": "sentryAlertFar",
    "bee": "bee_enabled",
}


def _patch_settings_from_config(st) -> None:
    """Alle bekannten settings-Attribute aus config.ini aktualisieren (ohne Modul-Reload)."""
    st.config.read(st.config_file, encoding="utf-8")
    for section in st.config.sections():
        for key in st.config[section]:
            attr = _CONFIG_ATTR_ALIASES.get(key, key)
            if not hasattr(st, attr):
                continue
            cur = getattr(st, attr)
            try:
                if isinstance(cur, bool):
                    setattr(st, attr, st.config[section].getboolean(key))
                elif isinstance(cur, int) and not isinstance(cur, bool):
                    setattr(st, attr, st.config[section].getint(key))
                elif isinstance(cur, float):
                    setattr(st, attr, st.config[section].getfloat(key))
                elif isinstance(cur, list):
                    setattr(
                        st,
                        attr,
                        [x.strip() for x in st.config[section].get(key, "").split(",") if x.strip()],
                    )
                else:
                    setattr(st, attr, st.config[section].get(key, ""))
            except (ValueError, AttributeError):
                continue


def _sync_wx_extra_trap_list() -> None:
    """!uv/!regen/!blitz in trap_list nach Web-Admin-Änderung."""
    import modules.settings as st

    try:
        import modules.system as sm
        from modules.wx_extra import trap_list_wx_extra
    except Exception:
        return

    without = tuple(t for t in sm.trap_list if t not in trap_list_wx_extra)
    if (
        st.location_enabled
        and getattr(st, "use_meteo_wxApi", False)
        and getattr(st, "wx_extra_commands", True)
    ):
        sm.trap_list = without + trap_list_wx_extra
    else:
        sm.trap_list = without


def _sync_metar_trap_list() -> None:
    """!metar in trap_list nach Web-Admin-Änderung (ohne Bot-Neustart)."""
    import modules.settings as st

    try:
        import modules.system as sm
        from modules.metar import trap_list_metar
    except Exception:
        return

    without = tuple(t for t in sm.trap_list if t not in trap_list_metar)
    if st.location_enabled and getattr(st, "metar_enabled", True):
        sm.trap_list = without + trap_list_metar
    else:
        sm.trap_list = without


def _sync_settings_to_system() -> None:
    import modules.settings as st

    try:
        import modules.system as sm
    except Exception:
        return

    skip = {
        "config",
        "config_file",
        "WELCOME_MSG",
        "EMERGENCY_RESPONSE",
        "MOTD",
        "NO_ALERTS",
        "NO_DATA_NOGPS",
        "ERROR_FETCHING_DATA",
    }
    for name, value in vars(st).items():
        if name in skip or name.startswith("_"):
            continue
        if name in vars(sm):
            setattr(sm, name, value)


def reload_runtime_settings() -> bool:
    """Nach Web-Admin-Config-Speichern: settings neu laden und an system spiegeln."""
    import importlib

    import modules.settings as st

    st.config.read(st.config_file, encoding="utf-8")
    full_reload = False
    try:
        importlib.reload(st)
        full_reload = True
    except Exception as e:
        from modules.log import logger

        logger.warning(
            f"Web-Admin: Vollständiger Modul-Reload nicht möglich ({e!s}); "
            "wende partielle Config-Aktualisierung an."
        )
        _patch_settings_from_config(st)

    _sync_settings_to_system()
    _sync_metar_trap_list()
    _sync_wx_extra_trap_list()

    try:
        rebuild_scheduler_jobs()
    except Exception:
        pass

    return full_reload


def save_config_from_admin_form(form) -> None:
    """Alle cfg__* Formularfelder in config.ini schreiben und Runtime aktualisieren."""
    import modules.settings as st
    from modules.admin_config import apply_form_to_config

    st.config.read(st.config_file, encoding="utf-8")
    apply_form_to_config(st.config, form, config_file=st.config_file)
    full = reload_runtime_settings()
    return full


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


# --- Local node settings (Meshtastic device config via admin channel) ---

_NODE_ROLE_LABELS: Dict[int, str] = {
    0: "CLIENT",
    1: "CLIENT_MUTE",
    2: "ROUTER",
    3: "ROUTER_CLIENT (veraltet)",
    4: "REPEATER (veraltet)",
    5: "TRACKER",
    6: "SENSOR",
    7: "TAK",
    8: "CLIENT_HIDDEN",
    9: "LOST_AND_FOUND",
    10: "TAK_TRACKER",
    11: "ROUTER_LATE",
    12: "CLIENT_BASE",
}

_REBROADCAST_LABELS: Dict[int, str] = {
    0: "ALL",
    1: "ALL_SKIP_DECODING",
    2: "LOCAL_ONLY",
    3: "KNOWN_ONLY",
    4: "NONE",
    5: "CORE_PORTNUMS_ONLY",
}


def _local_node_for_iface(iface_id: int):
    sm = _system_mod()
    iface = sm.__dict__.get(f"interface{iface_id}")
    if iface is None:
        return None, "Interface ist nicht verbunden."
    if not sm.__dict__.get(f"interface{iface_id}_enabled"):
        return None, f"Interface {iface_id} ist deaktiviert."
    if getattr(iface, "myInfo", None) is None:
        return None, "Radio noch nicht bereit (keine Verbindung zum Gerät)."
    return iface.localNode, None


def _enum_name(enum_path: str, value: int, fallback: Dict[int, str]) -> str:
    try:
        from meshtastic.protobuf import config_pb2

        obj = config_pb2.Config
        for part in enum_path.split("."):
            obj = getattr(obj, part)
        return obj.Name(int(value))
    except Exception:
        pass
    return fallback.get(int(value), str(value))


def fetch_local_node_settings(iface_id: int) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Read owner + device/position config from the connected local node."""
    from modules.system import decimal_to_hex

    node, err = _local_node_for_iface(iface_id)
    if err:
        return err, None

    sm = _system_mod()
    iface = sm.__dict__.get(f"interface{iface_id}")
    my_info = iface.getMyNodeInfo() or {}
    user = my_info.get("user") or {}
    short_name = str(user.get("shortName") or "")
    long_name = str(user.get("longName") or "")
    node_num = int(my_info.get("num") or sm.__dict__.get(f"myNodeNum{iface_id}", 0) or 0)

    lc = node.localConfig
    dev = lc.device
    pos = lc.position
    lora = lc.lora

    import modules.settings as st

    iface_type = getattr(st, f"interface{iface_id}_type", "?")

    pos_node = my_info.get("position") or {}
    latitude = pos_node.get("latitude")
    longitude = pos_node.get("longitude")
    if latitude is None:
        latitude = st.latitudeValue
    if longitude is None:
        longitude = st.longitudeValue
    altitude_m = pos_node.get("altitude")
    try:
        altitude_m = int(round(float(altitude_m))) if altitude_m is not None else None
    except (TypeError, ValueError):
        altitude_m = None

    return None, {
        "iface_id": iface_id,
        "iface_type": iface_type,
        "node_num": node_num,
        "node_id_hex": decimal_to_hex(node_num) if node_num else "—",
        "short_name": short_name,
        "long_name": long_name,
        "role": int(dev.role),
        "role_name": _enum_name("DeviceConfig.Role", dev.role, _NODE_ROLE_LABELS),
        "rebroadcast_mode": int(dev.rebroadcast_mode),
        "rebroadcast_name": _enum_name(
            "DeviceConfig.RebroadcastMode", dev.rebroadcast_mode, _REBROADCAST_LABELS
        ),
        "node_info_broadcast_secs": int(dev.node_info_broadcast_secs),
        "position_broadcast_secs": int(pos.position_broadcast_secs),
        "fixed_position": bool(pos.fixed_position),
        "latitude": latitude,
        "longitude": longitude,
        "altitude_m": altitude_m,
        "config_latitude": st.latitudeValue,
        "config_longitude": st.longitudeValue,
        "lora_region": _enum_name("LoRaConfig.RegionCode", lora.region, {}),
        "lora_modem_preset": _enum_name("LoRaConfig.ModemPreset", lora.modem_preset, {}),
        "lora_channel_num": int(lora.channel_num),
    }


def _parse_nonneg_int(raw: str, field_label: str, *, minimum: int = 0) -> Tuple[Optional[int], Optional[str]]:
    try:
        val = int((raw or "").strip())
    except ValueError:
        return None, f"{field_label}: bitte eine ganze Zahl eingeben."
    if val < minimum:
        return None, f"{field_label}: mindestens {minimum}."
    return val, None


def _parse_coord(
    raw: str, field_label: str, *, minimum: float, maximum: float
) -> Tuple[Optional[float], Optional[str]]:
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None, f"{field_label}: bitte einen Wert eingeben."
    try:
        val = float(text)
    except ValueError:
        return None, f"{field_label}: ungültige Zahl."
    if not minimum <= val <= maximum:
        return None, f"{field_label}: Wert zwischen {minimum} und {maximum}."
    return val, None


def _coords_changed(current: Dict[str, Any], lat: float, lon: float, alt_m: Optional[int]) -> bool:
    cur_lat = current.get("latitude")
    cur_lon = current.get("longitude")
    cur_alt = current.get("altitude_m")
    if cur_lat is None or cur_lon is None:
        return True
    if abs(float(cur_lat) - lat) > 1e-6 or abs(float(cur_lon) - lon) > 1e-6:
        return True
    if alt_m is None:
        return cur_alt is not None
    if cur_alt is None:
        return True
    return int(cur_alt) != int(alt_m)


def apply_local_node_settings(iface_id: int, form) -> Tuple[bool, str]:
    """Apply form values to the connected local Meshtastic node."""
    node, err = _local_node_for_iface(iface_id)
    if err:
        return False, err

    read_err, current = fetch_local_node_settings(iface_id)
    if read_err or not current:
        return False, read_err or "Einstellungen konnten nicht gelesen werden."

    short_name = (form.get("short_name") or "").strip()
    long_name = (form.get("long_name") or "").strip()
    if not short_name or len(short_name) > 4:
        return False, "Kurzname: 1–4 Zeichen erforderlich."
    if not long_name:
        return False, "Langname darf nicht leer sein."

    node_info_secs, err = _parse_nonneg_int(
        form.get("node_info_broadcast_secs"), "NodeInfo-Intervall", minimum=60
    )
    if err:
        return False, err
    pos_secs, err = _parse_nonneg_int(
        form.get("position_broadcast_secs"), "Positions-Intervall", minimum=60
    )
    if err:
        return False, err

    latitude, err = _parse_coord(form.get("latitude"), "Breitengrad", minimum=-90.0, maximum=90.0)
    if err:
        return False, err
    longitude, err = _parse_coord(form.get("longitude"), "Längengrad", minimum=-180.0, maximum=180.0)
    if err:
        return False, err

    alt_raw = (form.get("altitude_m") or "").strip().replace(",", ".")
    altitude_m: Optional[int] = None
    if alt_raw:
        try:
            altitude_m = int(round(float(alt_raw)))
        except ValueError:
            return False, "Höhe: ungültige Zahl."

    try:
        role = int(form.get("role", current["role"]))
        rebroadcast = int(form.get("rebroadcast_mode", current["rebroadcast_mode"]))
    except (TypeError, ValueError):
        return False, "Rolle oder Rebroadcast-Modus ungültig."

    changes: List[str] = []

    if short_name != current["short_name"] or long_name != current["long_name"]:
        try:
            node.setOwner(long_name=long_name, short_name=short_name)
        except Exception as e:
            return False, f"Name konnte nicht gesetzt werden: {e!s}"
        changes.append("Name")

    dev = node.localConfig.device
    dev_changed = False
    if role != int(dev.role):
        dev.role = role
        dev_changed = True
    if rebroadcast != int(dev.rebroadcast_mode):
        dev.rebroadcast_mode = rebroadcast
        dev_changed = True
    if node_info_secs != int(dev.node_info_broadcast_secs):
        dev.node_info_broadcast_secs = node_info_secs
        dev_changed = True
    if dev_changed:
        try:
            node.writeConfig("device")
        except Exception as e:
            return False, f"Geräte-Config konnte nicht geschrieben werden: {e!s}"
        changes.append("Gerät")

    pos = node.localConfig.position
    pos_changed = False
    if pos_secs != int(pos.position_broadcast_secs):
        pos.position_broadcast_secs = pos_secs
        pos_changed = True
    if bool(pos.position_broadcast_smart_enabled):
        pos.position_broadcast_smart_enabled = False
        pos_changed = True
    if bool(pos.gps_enabled):
        pos.gps_enabled = False
        pos_changed = True
    if not bool(pos.fixed_position):
        pos.fixed_position = True
        pos_changed = True
    if pos_changed:
        try:
            node.writeConfig("position")
        except Exception as e:
            return False, f"Positions-Config konnte nicht geschrieben werden: {e!s}"
        changes.append("Position")

    if _coords_changed(current, latitude, longitude, altitude_m) or not current.get("fixed_position"):
        try:
            node.setFixedPosition(latitude, longitude, altitude_m or 0)
        except Exception as e:
            return False, f"Feste Position konnte nicht gesetzt werden: {e!s}"
        changes.append("Feste Position")

    if not changes:
        return True, "Keine Änderungen."
    return True, f"Gespeichert auf dem Gerät: {', '.join(changes)}."


# --- Mesh channels (Meshtastic ChannelSettings via writeChannel) ---

_CHANNEL_ROLE_LABELS: Dict[int, str] = {
    0: "DISABLED",
    1: "PRIMARY",
    2: "SECONDARY",
}


def fetch_local_channels(iface_id: int) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    """Read mesh channel slots 0–7 from the connected local node protobuf."""
    node, err = _local_node_for_iface(iface_id)
    if err:
        return err, None

    sm = _system_mod()
    slots = []
    try:
        slots = sm.read_interface_channel_slots(int(iface_id))
    except Exception as e:
        return f"Kanäle konnten nicht gelesen werden: {e!s}", None

    if not slots:
        return (
            "Keine Kanäle vom Gerät gelesen — Verbindung prüfen oder Bot neu starten.",
            None,
        )

    out: List[Dict[str, Any]] = []
    for slot in slots:
        name = slot.get("name") or ""
        # Show preset-derived label in the name field when firmware name is empty
        name_field = name or (
            slot.get("label") if slot.get("role_name") == "PRIMARY" else ""
        )
        out.append(
            {
                "index": int(slot["index"]),
                "name": name,
                "name_display": name_field,
                "label": slot.get("label") or "",
                "role": int(slot.get("role") or 0),
                "role_name": slot.get("role_name") or "",
                "psk_label": slot.get("psk_kind") or "",
                "psk_value": slot.get("psk") or "",
                "uplink": bool(slot.get("uplink")),
                "downlink": bool(slot.get("downlink")),
                "empty": int(slot.get("role") or 0) == 0 and not name,
            }
        )
    return None, out


def _parse_channel_psk(psk_raw: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Parse a PSK field into protobuf bytes, or (None, None) if unchanged.

    meshtastic.util.fromPSK() returns a *str* for passphrases/unknown input.
    Assigning that to ChannelSettings.psk raises TypeError → Flask 500, nothing saved.
    """
    s = (psk_raw or "").strip()
    if not s:
        return None, None

    low = s.lower()
    try:
        from meshtastic import util as mesh_util

        if low in ("none", "default", "random") or (
            low.startswith("simple") and low[6:].isdigit()
        ):
            val = mesh_util.fromPSK(s)
            if not isinstance(val, (bytes, bytearray)):
                return None, "PSK ungültig."
            return bytes(val), None
    except Exception as e:
        return None, f"PSK ungültig: {e!s}"

    if s.startswith("0x") or s.startswith("0X"):
        try:
            raw = bytes.fromhex(re.sub(r"\s+", "", s[2:]))
        except ValueError as e:
            return None, f"PSK Hex ungültig: {e!s}"
        return raw, None

    body = s[7:].strip() if low.startswith("base64:") else s
    hexish = re.sub(r"[\s:-]", "", body)
    if re.fullmatch(r"[0-9a-fA-F]+", hexish) and len(hexish) in (32, 64):
        return bytes.fromhex(hexish), None

    try:
        pad = body + ("=" * ((4 - len(body) % 4) % 4))
        raw = base64.b64decode(pad, validate=False)
        if len(raw) in (16, 32):
            return raw, None
        if low.startswith("base64:") and raw:
            return raw, None
    except Exception:
        pass

    return None, (
        "PSK bitte als none, default, random, simpleN, 0x… (32/64 Hex-Zeichen) "
        "oder base64:… angeben — kein Klartext (sonst Absturz beim Speichern)."
    )


def apply_local_channel_settings(iface_id: int, form) -> Tuple[bool, str]:
    """Apply one channel slot from the Node Settings channel form."""
    try:
        return _apply_local_channel_settings(iface_id, form)
    except Exception as e:
        from modules.log import logger

        logger.exception("Admin: Kanal speichern fehlgeschlagen")
        return False, f"Kanal konnte nicht gespeichert werden: {e!s}"


def _apply_local_channel_settings(iface_id: int, form) -> Tuple[bool, str]:
    node, err = _local_node_for_iface(iface_id)
    if err:
        return False, err

    try:
        idx = int(form.get("channel_index", -1))
    except (TypeError, ValueError):
        return False, "Kanal-Index ungültig."
    if idx < 0 or idx > 7:
        return False, "Kanal-Index muss 0–7 sein."

    channels = getattr(node, "channels", None)
    if not channels or idx >= len(channels):
        return False, "Kanal-Slot nicht auf dem Gerät vorhanden."

    getter = getattr(node, "getChannelByChannelIndex", None)
    ch = getter(idx) if callable(getter) else channels[idx]
    if ch is None:
        return False, "Kanal-Slot nicht auf dem Gerät vorhanden."
    settings = ch.settings

    name = (form.get("name") or "").strip()
    if len(name) > 12:
        return False, "Kanalname: maximal 12 Zeichen."

    try:
        role = int(form.get("role", int(ch.role)))
    except (TypeError, ValueError):
        return False, "Rolle ungültig."

    if idx == 0:
        if role == 0:
            return False, "Primärkanal (#0) darf nicht DISABLED sein."
        if role != 1:
            return False, "Slot #0 muss PRIMARY bleiben."
    else:
        if role == 1:
            return False, "PRIMARY ist nur für Slot #0 erlaubt."
        if role not in (0, 2):
            return False, "Rolle: SECONDARY oder DISABLED."

    uplink = form.get("uplink_enabled") in ("1", "on", "true", "yes")
    downlink = form.get("downlink_enabled") in ("1", "on", "true", "yes")

    psk_raw = (form.get("psk") or "").strip()
    psk_changed = False
    if psk_raw:
        new_psk, psk_err = _parse_channel_psk(psk_raw)
        if psk_err:
            return False, psk_err
        if new_psk is not None:
            if len(new_psk) not in (1, 16, 32) and new_psk not in (b"", b"\x00"):
                return False, (
                    f"PSK hat {len(new_psk)} Bytes — erwartet 1 (none/default/simpleN), "
                    "16 oder 32 Bytes."
                )
            settings.psk = new_psk
            psk_changed = True

    settings.name = name
    settings.uplink_enabled = uplink
    settings.downlink_enabled = downlink
    ch.role = role
    ch.index = idx

    try:
        node.writeChannel(idx)
    except Exception as e:
        return False, f"Kanal #{idx} konnte nicht geschrieben werden: {e!s}"

    try:
        sm = _system_mod()
        if hasattr(sm, "refresh_channel_cache"):
            sm.refresh_channel_cache()
    except Exception:
        pass

    bits = [f"Name={name or '(leer)'}", f"Rolle={_CHANNEL_ROLE_LABELS.get(role, role)}"]
    if psk_changed:
        try:
            from meshtastic import util as mesh_util

            bits.append(
                f"PSK={mesh_util.pskToString(bytes(settings.psk) if settings.psk else b'')}"
            )
        except Exception:
            bits.append("PSK=geändert")
    bits.append(f"Up={'an' if uplink else 'aus'}")
    bits.append(f"Down={'an' if downlink else 'aus'}")
    return True, (
        f"Kanal #{idx} gespeichert ({', '.join(bits)}). "
        "Empfang auf einem neuen Slot: Channel-Test neu speichern; "
        "falls weiter nichts ankommt, Bot/meshtasticd neu starten."
    )


def _channel_role_options(index: int, selected: int) -> str:
    if index == 0:
        choices = [(1, "PRIMARY")]
    else:
        choices = [(2, "SECONDARY"), (0, "DISABLED")]
    opts = []
    for val, label in choices:
        sel = " selected" if int(selected) == val else ""
        opts.append(f'<option value="{val}"{sel}>{html.escape(label)}</option>')
    # If current role is unexpected (e.g. PRIMARY on #1), still show it
    if not any(int(selected) == v for v, _ in choices):
        label = _CHANNEL_ROLE_LABELS.get(int(selected), str(selected))
        opts.insert(
            0,
            f'<option value="{int(selected)}" selected>{html.escape(label)}</option>',
        )
    return "".join(opts)


def build_channels_settings_html(
    channels: List[Dict[str, Any]],
    *,
    iface_id: int,
    form_action: str,
) -> str:
    """Separate forms per channel slot for Node Settings."""
    rows = []
    for ch in channels:
        idx = int(ch["index"])
        name = html.escape(ch.get("name") or "")
        name_ph = html.escape(ch.get("label") or "z. B. MeshHessen")
        psk_label = html.escape(str(ch.get("psk_label") or "—"))
        psk_value = html.escape(str(ch.get("psk_value") or ""))
        up_chk = " checked" if ch.get("uplink") else ""
        down_chk = " checked" if ch.get("downlink") else ""
        role_opts = _channel_role_options(idx, int(ch.get("role") or 0))
        badge = ""
        if idx == 0:
            badge = '<span class="badge bg-primary ms-1">Primary</span>'
        elif ch.get("empty"):
            badge = '<span class="badge bg-secondary ms-1">leer</span>'
        rows.append(
            f"""
<div class="card border-secondary-subtle mb-3">
  <div class="card-header py-2 d-flex align-items-center justify-content-between">
    <span><strong>#{idx}</strong> {html.escape(ch.get("label") or "")} {badge}</span>
    <span class="small text-muted">PSK: <code>{psk_label}</code></span>
  </div>
  <div class="card-body py-3">
    <form method="post" class="row g-2 align-items-end">
      <input type="hidden" name="action" value="save_channel">
      <input type="hidden" name="iface_id" value="{iface_id}">
      <input type="hidden" name="channel_index" value="{idx}">
      <div class="col-md-3">
        <label class="form-label" for="ch-name-{idx}">Name (Firmware)</label>
        <input class="form-control form-control-sm" id="ch-name-{idx}" name="name"
               maxlength="12" value="{name}" placeholder="{name_ph}">
        <div class="form-text">Leer bei Primary = Anzeige über LoRa-Preset</div>
      </div>
      <div class="col-md-2">
        <label class="form-label" for="ch-role-{idx}">Rolle</label>
        <select class="form-select form-select-sm" id="ch-role-{idx}" name="role">
          {role_opts}
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label" for="ch-psk-{idx}">PSK ändern</label>
        <input class="form-control form-control-sm font-monospace" id="ch-psk-{idx}" name="psk"
               autocomplete="off" placeholder="leer = unverändert"
               title="none · default · random · base64:… · 0x…">
        <div class="form-text">aktuell: <code class="user-select-all">{psk_value or "—"}</code>
          · setzen: <code>none</code>/<code>default</code>/<code>simpleN</code>/<code>base64:…</code></div>
      </div>
      <div class="col-md-2">
        <div class="form-check mt-4">
          <input class="form-check-input" type="checkbox" name="uplink_enabled"
                 id="ch-up-{idx}" value="1"{up_chk}>
          <label class="form-check-label" for="ch-up-{idx}">Uplink</label>
        </div>
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="downlink_enabled"
                 id="ch-down-{idx}" value="1"{down_chk}>
          <label class="form-check-label" for="ch-down-{idx}">Downlink</label>
        </div>
      </div>
      <div class="col-md-2">
        <button type="submit" class="btn btn-sm btn-outline-primary w-100"
                onclick="return confirm('Kanal #{idx} wirklich auf dem Gerät speichern?');">
          Speichern
        </button>
      </div>
    </form>
  </div>
</div>
"""
        )

    return f"""
<hr class="my-4">
<h5 class="mb-2">Mesh-Kanäle</h5>
<p class="small text-muted mb-3">
  Liest die Kanal-Tabelle direkt aus der Meshtastic-Instanz (Protobuf, Slots 0–7).
  Primärkanal (#0) hat in der Firmware oft <strong>keinen Namen</strong> — die App zeigt dann den
  LoRa-Preset (z. B. ShortSlow). Der PSK erscheint als <code>none</code>/<code>default</code>/<code>simpleN</code>
  oder <code>base64:…</code> (lokaler Admin). Feld „PSK ändern“ leer lassen = unverändert.
</p>
<div class="alert alert-warning small">
  Typisch Meshhessen: <strong>#0 ShortSlow</strong> (PRIMARY) · <strong>#1 MeshHessen</strong> (SECONDARY).
  Primärkanal (#0) nicht deaktivieren. Nach dem Speichern Cache für Admin-Kanal/Channel-Test aktualisiert.
</div>
{''.join(rows) if rows else '<p class="text-muted">Keine Kanäle geladen.</p>'}
"""


def node_settings_role_options(selected: int) -> str:
    opts = []
    for val, label in sorted(_NODE_ROLE_LABELS.items()):
        sel = " selected" if val == selected else ""
        opts.append(f'<option value="{val}"{sel}>{html.escape(label)}</option>')
    return "".join(opts)


def node_settings_rebroadcast_options(selected: int) -> str:
    opts = []
    for val, label in sorted(_REBROADCAST_LABELS.items()):
        sel = " selected" if val == selected else ""
        opts.append(f'<option value="{val}"{sel}>{html.escape(label)}</option>')
    return "".join(opts)


def build_node_settings_html(
    settings: Dict[str, Any],
    *,
    iface_id: int,
    ifaces: List[int],
    form_action: str,
) -> str:
    """HTML form for local node settings."""
    tab_parts = []
    for i in ifaces:
        cls = "btn-light" if i == iface_id else "btn-outline-secondary"
        sep = "&" if "?" in form_action else "?"
        tab_parts.append(
            f'<a class="btn btn-sm {cls}" href="{html.escape(form_action)}{sep}iface={i}">IF {i}</a>'
        )
    tabs = " ".join(tab_parts)

    lat_val = settings["latitude"]
    lon_val = settings["longitude"]
    lat_disp = "" if lat_val is None else f"{float(lat_val):.6f}".rstrip("0").rstrip(".")
    lon_disp = "" if lon_val is None else f"{float(lon_val):.6f}".rstrip("0").rstrip(".")
    alt_disp = "" if settings["altitude_m"] is None else str(settings["altitude_m"])
    fixed_badge = (
        '<span class="badge bg-success">aktiv</span>'
        if settings["fixed_position"]
        else '<span class="badge bg-warning text-dark">noch nicht aktiv</span>'
    )
    cfg_lat = settings["config_latitude"]
    cfg_lon = settings["config_longitude"]

    return f"""
<p class="small text-muted mb-2">Schnittstelle: {tabs}</p>
<p class="small text-muted">Liest und schreibt die Konfiguration der <strong>lokal verbundenen</strong> Meshtastic-Node
  (wie <code>meshtastic --set</code>). Änderungen werden im Gerät gespeichert und gelten unabhängig vom Bot.</p>
<p class="small text-muted">Dieser Bot hat <strong>kein GPS</strong> — es können nur <strong>feste Positionen</strong> gesetzt werden
  (GPS am Gerät wird automatisch deaktiviert).</p>

<div class="row g-3 mb-3">
  <div class="col-md-4">
    <div class="p-3 rounded border border-secondary-subtle h-100">
      <div class="small text-muted">Node ID</div>
      <div><code>{html.escape(str(settings["node_num"]))}</code>
        <code class="ms-1">{html.escape(settings["node_id_hex"])}</code></div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="p-3 rounded border border-secondary-subtle h-100">
      <div class="small text-muted">Verbindung</div>
      <div>{html.escape(str(settings["iface_type"]).upper())} (Interface {iface_id})</div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="p-3 rounded border border-secondary-subtle h-100">
      <div class="small text-muted">LoRa (nur Anzeige)</div>
      <div class="small">{html.escape(settings["lora_region"])} · {html.escape(settings["lora_modem_preset"])} · Kanal {settings["lora_channel_num"]}</div>
    </div>
  </div>
</div>

<form method="post" class="node-settings-form">
  <input type="hidden" name="iface_id" value="{iface_id}">

  <h5 class="mt-2 mb-3">Knotenname</h5>
  <div class="row g-3 mb-4">
    <div class="col-md-3">
      <label class="form-label" for="ns-short">Kurzname (max. 4)</label>
      <input class="form-control" id="ns-short" name="short_name" maxlength="4" required
             value="{html.escape(settings["short_name"])}">
    </div>
    <div class="col-md-9">
      <label class="form-label" for="ns-long">Langname</label>
      <input class="form-control" id="ns-long" name="long_name" maxlength="40" required
             value="{html.escape(settings["long_name"])}">
    </div>
  </div>

  <h5 class="mb-3">Gerät</h5>
  <div class="row g-3 mb-4">
    <div class="col-md-4">
      <label class="form-label" for="ns-role">Rolle</label>
      <select class="form-select" id="ns-role" name="role">
        {node_settings_role_options(settings["role"])}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label" for="ns-rebroadcast">Rebroadcast</label>
      <select class="form-select" id="ns-rebroadcast" name="rebroadcast_mode">
        {node_settings_rebroadcast_options(settings["rebroadcast_mode"])}
      </select>
    </div>
    <div class="col-md-4">
      <label class="form-label" for="ns-nodeinfo">NodeInfo-Intervall (Sek.)</label>
      <input class="form-control" type="number" id="ns-nodeinfo" name="node_info_broadcast_secs"
             min="60" step="1" required value="{settings["node_info_broadcast_secs"]}">
      <div class="form-text">Wie oft NodeInfo gesendet wird (Standard oft 900 s).</div>
    </div>
  </div>

  <h5 class="mb-3">Feste Position</h5>
  <p class="small text-muted mb-3">Feste Position auf dem Gerät: {fixed_badge}
    · Vorgabe aus <code>config.ini</code> [location]: {cfg_lat}, {cfg_lon}</p>
  <div class="row g-3 mb-4">
    <div class="col-md-3">
      <label class="form-label" for="ns-lat">Breitengrad</label>
      <input class="form-control" type="text" inputmode="decimal" id="ns-lat" name="latitude" required
             placeholder="50.4484" value="{html.escape(lat_disp)}">
    </div>
    <div class="col-md-3">
      <label class="form-label" for="ns-lon">Längengrad</label>
      <input class="form-control" type="text" inputmode="decimal" id="ns-lon" name="longitude" required
             placeholder="9.509" value="{html.escape(lon_disp)}">
    </div>
    <div class="col-md-3">
      <label class="form-label" for="ns-alt">Höhe (m, optional)</label>
      <input class="form-control" type="number" id="ns-alt" name="altitude_m" step="1"
             placeholder="z. B. 320" value="{html.escape(alt_disp)}">
    </div>
    <div class="col-md-3">
      <label class="form-label" for="ns-pos">Positions-Intervall (Sek.)</label>
      <input class="form-control" type="number" id="ns-pos" name="position_broadcast_secs"
             min="60" step="1" required value="{settings["position_broadcast_secs"]}">
      <div class="form-text">Sendeintervall der festen Position ins Mesh.</div>
    </div>
  </div>

  <div class="alert alert-warning small">
    Kürzere Intervalle erhöhen Funklast und Stromverbrauch. Rolle und Rebroadcast beeinflussen das Mesh-Verhalten —
    auf öffentlichen Netzen vorsichtig ändern. GPS bleibt am Gerät ausgeschaltet.
  </div>

  <button type="submit" class="btn btn-primary">Auf Gerät speichern</button>
</form>
"""


def build_node_settings_page_html(
    settings: Dict[str, Any],
    channels: Optional[List[Dict[str, Any]]],
    channels_err: Optional[str],
    *,
    iface_id: int,
    ifaces: List[int],
    form_action: str,
) -> str:
    """Node settings form + channel editor section."""
    body = build_node_settings_html(
        settings,
        iface_id=iface_id,
        ifaces=ifaces,
        form_action=form_action,
    )
    if channels_err:
        body += (
            f'<hr class="my-4"><h5>Mesh-Kanäle</h5>'
            f'<p class="alert alert-warning">{html.escape(channels_err)}</p>'
        )
    elif channels is not None:
        body += build_channels_settings_html(
            channels, iface_id=iface_id, form_action=form_action
        )
    return body


def _bw_node_caption(nid: int) -> Tuple[str, str, str]:
    hex_id = f"!{int(nid):08x}"
    short = ""
    long_n = ""
    try:
        import modules.nodedb as ndb

        short = ndb.get_node_short_name(int(nid)) or ""
        long_n = ndb.get_node_long_name(int(nid)) or ""
    except Exception:
        pass
    return hex_id, short, long_n


def _bw_parse_node_id(raw: str) -> Optional[int]:
    s = normalize_ban_node_id(raw)
    if not s:
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return n if n > 0 else None


def apply_blitzwatch_admin_form(form) -> Tuple[bool, str, Optional[int]]:
    """Apply one admin Blitzwatch POST. Returns (ok, flash, redirect_node_id)."""
    from modules import blitzwatch as bw

    bw.initialize_blitzwatch_database()
    action = (form.get("action") or "").strip()
    nid = _bw_parse_node_id(form.get("node_id") or "")
    if not nid:
        return False, "Knoten-ID fehlt.", None

    if action == "reset":
        bw.reset_watch_for_node(nid)
        return True, f"Einstellungen für {nid} gelöscht (wieder Defaults).", None

    if action == "save_prefs":
        enabled = form.get("enabled") in ("1", "on", "true", "yes")
        try:
            radius = int((form.get("radius_km") or "8").strip())
        except ValueError:
            return False, "Radius muss eine ganze Zahl sein.", nid
        bw._upsert_node_row(nid, enabled=enabled, radius_km=radius)
        return True, f"Node {nid}: Warnung {'AN' if enabled else 'AUS'}, Home-Radius {bw.clamp_radius_km(radius)} km.", nid

    if action == "home_gps":
        bw.set_home_gps(nid)
        return True, f"Home für {nid} wieder GPS.", nid

    if action == "home_place":
        place = (form.get("place") or "").strip()
        if not place:
            return False, "Ort, Koordinaten oder Maidenhead angeben.", nid
        resolved, err = bw._resolve_explicit_location(
            f"!blitzwatch home {place}", nid, 1, ("blitzwatch", "home")
        )
        if err:
            return False, err, nid
        assert resolved is not None
        lat, lon, label = resolved
        bw.set_home_fixed(nid, lat, lon, label)
        return True, f"Home-Fix für {nid}: {label}.", nid

    if action == "add_extra":
        place = (form.get("place") or "").strip()
        if not place:
            return False, "Zusatzort: Ort, Koordinaten oder Grid angeben.", nid
        radius_raw = (form.get("extra_radius_km") or "").strip()
        radius_override = None
        if radius_raw:
            try:
                radius_override = int(radius_raw)
            except ValueError:
                return False, "Radius Zusatzort ungültig.", nid
        loc_msg = f"!blitzwatch add {place}"
        resolved, err = bw._resolve_explicit_location(
            loc_msg, nid, 1, ("blitzwatch", "add")
        )
        if err:
            return False, err, nid
        assert resolved is not None
        lat, lon, label = resolved
        loc, add_err = bw.add_location(nid, lat, lon, label, radius_override)
        if add_err:
            return False, add_err, nid
        return True, f"Zusatzort {loc['slot']}: {loc['label']}.", nid

    if action == "del_extra":
        try:
            slot = int(form.get("slot") or "0")
        except ValueError:
            return False, "Slot ungültig.", nid
        if bw.delete_location(nid, slot):
            return True, f"Zusatzort {slot} gelöscht.", nid
        return False, f"Kein Zusatzort {slot}.", nid

    if action == "extra_radius":
        try:
            slot = int(form.get("slot") or "0")
            radius = int(form.get("radius_km") or "0")
        except ValueError:
            return False, "Slot/Radius ungültig.", nid
        loc = bw.set_location_radius(nid, slot, radius)
        if not loc:
            return False, f"Kein Zusatzort {slot}.", nid
        return True, f"Ort {slot}: Radius {loc['radius_km']} km.", nid

    return False, "Unbekannte Aktion.", nid


def _bw_collect_admin_list() -> List[Dict[str, Any]]:
    """NodeDB nodes plus leftover Blitzwatch-only IDs, newest lastSeen first."""
    from modules import blitzwatch as bw

    bw.initialize_blitzwatch_database()
    prefs_map = bw.get_all_prefs_map()
    seen: set[int] = set()
    items: List[Dict[str, Any]] = []
    nodedb_list: List[Tuple[int, dict]] = []
    try:
        import modules.nodedb as ndb

        nodedb_list = ndb.list_nodes()
    except Exception:
        nodedb_list = []
    for nid, entry in nodedb_list:
        nid = int(nid)
        seen.add(nid)
        prefs = prefs_map.get(nid)
        if prefs is None:
            prefs = bw.get_node_prefs(nid)
        extras = int(prefs.get("extra_count") or 0)
        if "extra_count" not in prefs:
            extras = len(bw.list_locations(nid))
        last_seen = entry.get("lastSeen") or 0
        try:
            last_s = (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(float(last_seen)))
                if last_seen
                else "—"
            )
        except (OverflowError, OSError, TypeError, ValueError):
            last_s = "—"
        items.append(
            {
                "node_id": nid,
                "prefs": prefs,
                "extra_count": extras,
                "last_seen_s": last_s,
            }
        )
    leftover = sorted(int(n) for n in prefs_map if int(n) not in seen)
    for nid in leftover:
        prefs = prefs_map[nid]
        extras = int(prefs.get("extra_count") or 0)
        items.append(
            {
                "node_id": nid,
                "prefs": prefs,
                "extra_count": extras,
                "last_seen_s": "—",
            }
        )
    return items


def build_blitzwatch_node_editor_html(
    edit_nid: int,
    *,
    extra_footer: str = "",
) -> str:
    """Shared prefs editor (admin + public PIN session)."""
    from modules import blitzwatch as bw

    prefs = bw.get_node_prefs(edit_nid)
    locs = bw.list_locations(edit_nid)
    hex_id, short, long_n = _bw_node_caption(edit_nid)
    title = " · ".join(x for x in (short, long_n) if x) or hex_id
    en_chk = " checked" if prefs.get("enabled") else ""
    home_lab = html.escape(prefs.get("home_label") or "")
    last = prefs.get("last_alert_ts") or 0
    last_s = "—"
    if last:
        ago = int((time.time() - float(last)) / 60)
        last_s = f"vor {ago} min"

    extra_rows = []
    for loc in locs:
        slot = int(loc["slot"])
        extra_rows.append(
            f"""
<div class="d-flex flex-wrap gap-2 align-items-end mb-2">
  <div class="flex-grow-1 small">
    <strong>Ort {slot}</strong> {html.escape(loc["label"])}
    <span class="text-muted">({loc["lat"]:.4f}, {loc["lon"]:.4f})</span>
  </div>
  <form method="post" class="d-flex gap-1">
    <input type="hidden" name="action" value="extra_radius">
    <input type="hidden" name="node_id" value="{edit_nid}">
    <input type="hidden" name="slot" value="{slot}">
    <input class="form-control form-control-sm" style="width:5rem" name="radius_km"
           type="number" min="1" max="50" value="{int(loc["radius_km"])}">
    <button class="btn btn-sm btn-outline-primary" type="submit">km</button>
  </form>
  <form method="post" onsubmit="return confirm('Ort {slot} löschen?');">
    <input type="hidden" name="action" value="del_extra">
    <input type="hidden" name="node_id" value="{edit_nid}">
    <input type="hidden" name="slot" value="{slot}">
    <button class="btn btn-sm btn-outline-danger" type="submit">Löschen</button>
  </form>
</div>"""
        )
    if not extra_rows:
        extra_rows.append('<p class="text-muted small mb-2">Keine Zusatzorte.</p>')

    return f"""
<div class="card border-primary mb-4 bw-admin-edit" id="bw-edit">
  <div class="card-header d-flex flex-wrap justify-content-between align-items-center gap-2">
    <span><strong>Einstellungen:</strong> {html.escape(title)}</span>
    <span class="small text-muted"><code>{edit_nid}</code> · <code>{html.escape(hex_id)}</code></span>
  </div>
  <div class="card-body">
    <p class="small text-muted mb-3">letzte Home-Warnung: {html.escape(last_s)}</p>
    <form method="post" class="row g-2 align-items-end mb-3">
      <input type="hidden" name="action" value="save_prefs">
      <input type="hidden" name="node_id" value="{edit_nid}">
      <div class="col-auto">
        <div class="form-check mt-4">
          <input class="form-check-input" type="checkbox" name="enabled" id="bwEn" value="1"{en_chk}>
          <label class="form-check-label" for="bwEn">Warnung AN</label>
        </div>
      </div>
      <div class="col-md-2">
        <label class="form-label">Home-Radius (km)</label>
        <input class="form-control" type="number" min="1" max="50" name="radius_km"
               value="{int(prefs.get("radius_km") or 8)}">
      </div>
      <div class="col-md-3">
        <button class="btn btn-primary" type="submit">Speichern</button>
      </div>
    </form>
    <p class="small mb-2">Home: <strong>{"Fix " + home_lab if prefs.get("home_mode") == "fixed" and home_lab else "GPS"}</strong></p>
    <div class="row g-2 mb-3">
      <div class="col-md-7">
        <form method="post" class="d-flex gap-2">
          <input type="hidden" name="action" value="home_place">
          <input type="hidden" name="node_id" value="{edit_nid}">
          <input class="form-control" name="place" placeholder="Ort, 50.34 8.76 oder JO40AA" required>
          <button class="btn btn-outline-primary" type="submit">Home-Fix setzen</button>
        </form>
      </div>
      <div class="col-md-3">
        <form method="post">
          <input type="hidden" name="action" value="home_gps">
          <input type="hidden" name="node_id" value="{edit_nid}">
          <button class="btn btn-outline-secondary" type="submit">Home = GPS</button>
        </form>
      </div>
    </div>
    <h6 class="mt-3">Zusatzorte (max. {bw.MAX_EXTRA_LOCATIONS})</h6>
    {"".join(extra_rows)}
    <form method="post" class="row g-2 align-items-end mt-2">
      <input type="hidden" name="action" value="add_extra">
      <input type="hidden" name="node_id" value="{edit_nid}">
      <div class="col-md-5">
        <label class="form-label">Neuer Zusatzort</label>
        <input class="form-control" name="place" placeholder="Ort / Coords / Grid" required>
      </div>
      <div class="col-md-2">
        <label class="form-label">Radius km</label>
        <input class="form-control" name="extra_radius_km" type="number" min="1" max="50" placeholder="wie Home">
      </div>
      <div class="col-md-3">
        <button class="btn btn-outline-success" type="submit">Hinzufügen</button>
      </div>
    </form>
    <form method="post" class="mt-4" onsubmit="return confirm('Alle Blitzwatch-Daten dieses Knotens löschen?');">
      <input type="hidden" name="action" value="reset">
      <input type="hidden" name="node_id" value="{edit_nid}">
      <button class="btn btn-sm btn-outline-danger" type="submit">Eintrag zurücksetzen</button>
    </form>
    {extra_footer}
  </div>
</div>
"""


def build_blitzwatch_public_html(
    *,
    node_id: Optional[int],
    global_on: bool,
    location_on: bool,
) -> str:
    from modules.web_commands_help import render_blitzwatch_guide

    guide = render_blitzwatch_guide()
    if not location_on or not global_on:
        return (
            '<p class="alert alert-warning">Blitzwatch ist derzeit deaktiviert.</p>'
            + guide
        )
    if not node_id:
        return f"""
<div class="portal-card p-4 mb-4">
  <h1 class="h3 section-title mb-3">
    <i class="bi bi-lightning-charge text-success me-2"></i>Blitzwatch
  </h1>
  <p class="text-muted">
    Stelle Home, Radius und Zusatzorte hier im Browser ein.
    Der Code kommt nur per <strong>Direktnachricht</strong> vom Bot.
  </p>
  <ol class="text-muted small mb-4">
    <li>In der Meshtastic-App eine <strong>DM an den Bot</strong> senden:
      <code>!blitzwatch web</code> (oder <code>!blitzwatch set</code>)</li>
    <li>Den <strong>5-stelligen Code</strong> unten eingeben (15 Minuten gültig, einmalig).</li>
  </ol>
  <form method="post" class="row g-2 align-items-end" style="max-width: 22rem;">
    <input type="hidden" name="action" value="unlock">
    <div class="col-8">
      <label class="form-label" for="bwCode">Code</label>
      <input class="form-control form-control-lg text-center font-monospace bw-pin-input"
             id="bwCode" name="code" inputmode="numeric" pattern="[0-9]{5}"
             maxlength="5" minlength="5" autocomplete="one-time-code" required
             placeholder="•••••">
    </div>
    <div class="col-4">
      <button class="btn btn-success w-100" type="submit">Öffnen</button>
    </div>
  </form>
  <p class="small text-muted mt-4 mb-0">
    Mesh-Befehle bleiben: <code>!blitzwatch</code> · Übersicht:
    <a href="/befehle">Befehle</a>
  </p>
</div>
{guide}
"""
    logout = """
<form method="post" class="mt-3">
  <input type="hidden" name="action" value="logout">
  <button class="btn btn-sm btn-outline-secondary" type="submit">Sitzung beenden</button>
</form>
"""
    return f"""
<div class="mb-3">
  <h1 class="h3 section-title mb-2">
    <i class="bi bi-lightning-charge text-success me-2"></i>Deine Blitzwatch-Einstellungen
  </h1>
  <p class="small text-muted mb-0">Gilt nur für deine Node. Nach einer Stunde oder „Sitzung beenden“ ist der Zugang wieder zu.</p>
</div>
{build_blitzwatch_node_editor_html(int(node_id), extra_footer=logout)}
{guide}
"""


def build_blitzwatch_admin_html(
    *,
    edit_nid: Optional[int],
    form_action: str,
    global_on: bool,
    location_on: bool,
) -> str:
    if not location_on or not global_on:
        return (
            '<p class="alert alert-warning">Blitzwatch ist in der Config aus '
            '(<code>[location] enabled</code> / <code>blitzWatchEnabled</code>). '
            "Globale Schalter unter Einstellungen.</p>"
        )

    watchers = _bw_collect_admin_list()
    rows = []
    for w in watchers:
        nid = int(w["node_id"])
        prefs = w["prefs"]
        hex_id, short, long_n = _bw_node_caption(nid)
        name_plain = " · ".join(x for x in (short, long_n) if x) or "—"
        name = html.escape(name_plain)
        en = bool(prefs.get("enabled", True))
        badge = (
            '<span class="badge bg-success">AN</span>'
            if en
            else '<span class="badge bg-secondary">AUS</span>'
        )
        if prefs.get("home_mode") == "fixed" and prefs.get("home_lat") is not None:
            home = html.escape(str(prefs.get("home_label") or "Fix"))
            home_plain = str(prefs.get("home_label") or "Fix")
        else:
            home = "GPS"
            home_plain = "GPS"
        extras = int(w.get("extra_count") or 0)
        sel = " table-active" if edit_nid == nid else ""
        search = " ".join(
            [
                str(nid),
                hex_id,
                name_plain,
                "an" if en else "aus",
                home_plain,
                w.get("last_seen_s") or "",
            ]
        ).lower()
        search_attr = html.escape(search, quote=True)
        href = html.escape(f"{form_action}?node={nid}#bw-edit")
        rows.append(
            f'<tr class="{sel}" data-search="{search_attr}">'
            f"<td><code>{nid}</code><br><code class=\"small\">{html.escape(hex_id)}</code></td>"
            f"<td>{name}</td>"
            f"<td>{badge}</td>"
            f"<td>{home} · {int(prefs.get('radius_km') or 8)} km</td>"
            f"<td>{extras}</td>"
            f"<td>{html.escape(str(w.get('last_seen_s') or '—'))}</td>"
            f'<td><a class="btn btn-sm btn-outline-primary" href="{href}">Bearbeiten</a></td>'
            "</tr>"
        )

    empty_row = (
        '<tr class="nodedb-search-empty" hidden>'
        '<td colspan="7" class="text-muted small">Keine Treffer für die Suche.</td></tr>'
    )
    if rows:
        tbody = "".join(rows) + empty_row
    else:
        tbody = (
            '<tr><td colspan="7" class="text-muted">Keine Knoten in der NodeDB.</td></tr>'
            + empty_row
        )

    table = f"""
<div class="nodedb-search-block bw-admin-list">
  {nodedb_search_toolbar_html(placeholder="Knoten suchen (ID, Name, Hex …)")}
  <div class="table-scroll mb-0">
    <table class="table table-sm table-bordered table-hover nodes-table mb-0">
      <thead><tr>
        <th>Node</th><th>Name</th><th>Warnung</th><th>Home</th>
        <th>Zusatz</th><th>Zuletzt</th><th></th>
      </tr></thead>
      <tbody>{tbody}</tbody>
    </table>
  </div>
</div>
<script src="/static/portal/nodedb-search.js"></script>
"""

    detail = """
<div class="alert alert-secondary small mb-4" id="bw-edit">
  Wähle in der Liste einen Knoten — die Einstellungen erscheinen hier oben,
  ohne nach unten zu scrollen.
</div>
"""
    if edit_nid:
        detail = build_blitzwatch_node_editor_html(edit_nid)

    return f"""
<p class="small text-muted">Liste folgt der persistenten NodeDB. Ohne gespeicherten Blitzwatch-Eintrag gelten Defaults (Warnung AN, Default-Radius).
  Globale Optionen: <a href="/einstellungen">Einstellungen</a> → location / blitzWatch.</p>
{detail}
{table}
"""
