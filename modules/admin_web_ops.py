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
    parts.append("gps" if row.get("has_gps") else "kein gps")
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
_TIME_REQUIRED_MODES = frozenset({"day"}) | _WEEKDAY_MODES


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

    current, read_err = fetch_local_node_settings(iface_id)
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
