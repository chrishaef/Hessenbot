# Blitz proximity watch: alert nodes with fresh GPS when lightning is nearby.
from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from modules.log import logger
from modules.paths import ensure_parent_dir, path_in_repo

trap_list_blitzwatch = ("blitzwatch",)

DEFAULT_RADIUS_KM = 8
MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 10
COOLDOWN_SEC = 3600
POLL_SEC = 300
META_CHANNEL_TS = "last_channel_alert_ts"

_last_poll_ts = 0.0


def _db_path() -> str:
    import modules.settings as st

    rel = getattr(st, "blitzwatch_db", "data/blitzwatch.db") or "data/blitzwatch.db"
    return path_in_repo(rel)


def initialize_blitzwatch_database() -> bool:
    try:
        path = _db_path()
        ensure_parent_dir(path)
        conn = sqlite3.connect(path)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS blitzwatch (
                node_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                radius_km INTEGER NOT NULL DEFAULT 8,
                last_alert_ts REAL NOT NULL DEFAULT 0
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS blitzwatch_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )"""
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Blitzwatch: DB init failed: {e}")
        return False


def _connect() -> sqlite3.Connection:
    path = _db_path()
    ensure_parent_dir(path)
    conn = sqlite3.connect(path)
    return conn


def clamp_radius_km(value: int) -> int:
    return max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, int(value)))


def get_node_prefs(node_id: int) -> dict[str, Any]:
    """Return prefs; missing row → default enabled with default radius."""
    import modules.settings as st

    default_r = clamp_radius_km(
        int(getattr(st, "blitz_watch_default_radius_km", DEFAULT_RADIUS_KM))
    )
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute(
            "SELECT enabled, radius_km, last_alert_ts FROM blitzwatch WHERE node_id=?",
            (int(node_id),),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "enabled": bool(row[0]),
                "radius_km": clamp_radius_km(row[1]),
                "last_alert_ts": float(row[2] or 0),
                "in_db": True,
            }
    except Exception as e:
        logger.debug(f"Blitzwatch: get_node_prefs: {e}")
        initialize_blitzwatch_database()
    return {
        "enabled": True,
        "radius_km": default_r,
        "last_alert_ts": 0.0,
        "in_db": False,
    }


def set_node_enabled(node_id: int, enabled: bool) -> dict[str, Any]:
    prefs = get_node_prefs(node_id)
    radius = prefs["radius_km"]
    last = prefs["last_alert_ts"]
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO blitzwatch (node_id, enabled, radius_km, last_alert_ts)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(node_id) DO UPDATE SET enabled=excluded.enabled""",
        (int(node_id), 1 if enabled else 0, radius, last),
    )
    conn.commit()
    conn.close()
    return get_node_prefs(node_id)


def set_node_radius(node_id: int, radius_km: int) -> dict[str, Any]:
    prefs = get_node_prefs(node_id)
    radius = clamp_radius_km(radius_km)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO blitzwatch (node_id, enabled, radius_km, last_alert_ts)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(node_id) DO UPDATE SET
             radius_km=excluded.radius_km,
             enabled=1""",
        (int(node_id), 1, radius, prefs["last_alert_ts"]),
    )
    conn.commit()
    conn.close()
    return get_node_prefs(node_id)


def mark_node_alerted(node_id: int, when: float | None = None) -> None:
    ts = float(when if when is not None else time.time())
    prefs = get_node_prefs(node_id)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO blitzwatch (node_id, enabled, radius_km, last_alert_ts)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(node_id) DO UPDATE SET last_alert_ts=excluded.last_alert_ts""",
        (
            int(node_id),
            1 if prefs["enabled"] else 0,
            prefs["radius_km"],
            ts,
        ),
    )
    conn.commit()
    conn.close()


def get_meta(key: str, default: str = "") -> str:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT value FROM blitzwatch_meta WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def set_meta(key: str, value: str) -> None:
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO blitzwatch_meta (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_all_prefs_map() -> dict[int, dict[str, Any]]:
    """node_id → prefs for UI enrichment."""
    out: dict[int, dict[str, Any]] = {}
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT node_id, enabled, radius_km, last_alert_ts FROM blitzwatch")
        for node_id, enabled, radius_km, last_alert_ts in c.fetchall():
            out[int(node_id)] = {
                "enabled": bool(enabled),
                "radius_km": clamp_radius_km(radius_km),
                "last_alert_ts": float(last_alert_ts or 0),
                "in_db": True,
            }
        conn.close()
    except Exception as e:
        logger.debug(f"Blitzwatch: get_all_prefs_map: {e}")
    return out


def format_status(node_id: int, *, has_fresh_gps: bool) -> str:
    import modules.settings as st

    global_on = bool(getattr(st, "blitz_watch_enabled", True))
    prefs = get_node_prefs(node_id)
    lines = ["🤖 !blitzwatch — Blitz-Nähe-Warnung"]
    if not global_on:
        lines.append("Global: AUS (Admin/Config)")
    else:
        lines.append("Global: AN")
    lines.append(f"Deine Node: {'AN' if prefs['enabled'] else 'AUS'}")
    lines.append(f"Radius: {prefs['radius_km']} km (max {MAX_RADIUS_KM} km)")
    if not has_fresh_gps:
        lines.append("Standort: kein frisches GPS (≤24h) — keine Warnungen möglich")
    else:
        lines.append("Standort: GPS bekannt (≤24h)")
    if prefs["last_alert_ts"]:
        ago = int((time.time() - prefs["last_alert_ts"]) / 60)
        lines.append(f"Letzte Warnung: vor {ago} min")
    lines.append("Befehle: on · off · 3km … 10km · ?")
    return "\n".join(lines)


def handle_blitzwatch_command(message: str, message_from_id: int, deviceID: int = 1) -> str:
    """Parse !blitzwatch for the sending node only."""
    import modules.settings as st
    from modules.system import _nodedb_fresh_position

    if not getattr(st, "location_enabled", True):
        return "Standortmodul aus ([location] enabled = False)."
    if not getattr(st, "blitz_watch_enabled", True):
        return "🤖 Blitzwatch ist global deaktiviert (Config/Admin)."

    initialize_blitzwatch_database()
    fresh = _nodedb_fresh_position(message_from_id, deviceID, 2)
    has_gps = bool(fresh)

    text = (message or "").strip()
    if text.startswith("!"):
        text = text[1:].strip()
    # Drop command token
    parts = text.replace("?", " ? ").split()
    args = [p for p in parts if p.lower().rstrip("?") != "blitzwatch"]

    if not args or args[0] in ("?", "status", "help"):
        return format_status(message_from_id, has_fresh_gps=has_gps)

    token = args[0].lower().strip()
    if token in ("on", "an", "ein"):
        set_node_enabled(message_from_id, True)
        return format_status(message_from_id, has_fresh_gps=has_gps)

    if token in ("off", "aus"):
        set_node_enabled(message_from_id, False)
        return (
            "Blitzwatch für deine Node: AUS.\n"
            "Mit !blitzwatch on wieder einschalten."
        )

    # Radius: 5, 5km, 5 km
    m = re.fullmatch(r"(\d+)\s*km?", token)
    if not m and len(args) >= 2:
        m = re.fullmatch(r"(\d+)", token) if args[1].lower().startswith("km") else None
    if m:
        radius = clamp_radius_km(int(m.group(1)))
        if int(m.group(1)) > MAX_RADIUS_KM:
            set_node_radius(message_from_id, radius)
            return (
                f"Radius auf Maximum {MAX_RADIUS_KM} km gesetzt (AN).\n"
                + format_status(message_from_id, has_fresh_gps=has_gps)
            )
        if int(m.group(1)) < MIN_RADIUS_KM:
            set_node_radius(message_from_id, radius)
            return (
                f"Radius auf Minimum {MIN_RADIUS_KM} km gesetzt (AN).\n"
                + format_status(message_from_id, has_fresh_gps=has_gps)
            )
        set_node_radius(message_from_id, radius)
        return (
            f"Blitzwatch Radius: {radius} km (AN).\n"
            + format_status(message_from_id, has_fresh_gps=has_gps)
        )

    return (
        "🤖 !blitzwatch — Nutzung:\n"
        "on / off — Warnung ein/aus\n"
        "3km … 10km — Radius setzen\n"
        "!blitzwatch — Status"
    )


def _collect_watch_candidates(deviceID: int) -> list[dict[str, Any]]:
    """Nodes with fresh NodeDB GPS, not bot self, watch enabled."""
    import modules.settings as st
    import modules.system as sysmod
    from modules.system import _nodedb_fresh_position, get_name_from_number

    cooldown = int(getattr(st, "blitz_watch_cooldown_sec", COOLDOWN_SEC))
    now = time.time()
    candidates: list[dict[str, Any]] = []

    my_ids: set[int] = set()
    seen: set[int] = set()
    try:
        iface_order = [deviceID] + [i for i in range(1, 10) if i != deviceID]
        for i in iface_order:
            if not sysmod.__dict__.get(f"interface{i}_enabled"):
                continue
            mid = sysmod.__dict__.get(f"myNodeNum{i}")
            if mid:
                my_ids.add(int(mid))
    except Exception as e:
        logger.debug(f"Blitzwatch: collect candidates: {e}")
        return []

    for i in range(1, 10):
        if not sysmod.__dict__.get(f"interface{i}_enabled"):
            continue
        iface = sysmod.__dict__.get(f"interface{i}")
        nodes = getattr(iface, "nodes", None) or {}
        for node in nodes.values():
            num = node.get("num")
            if num is None:
                continue
            try:
                nid = int(num)
            except (TypeError, ValueError):
                continue
            if nid in my_ids or nid in seen:
                continue
            fresh = _nodedb_fresh_position(nid, i, 2)
            if not fresh:
                continue
            prefs = get_node_prefs(nid)
            if not prefs["enabled"]:
                continue
            if prefs["last_alert_ts"] and (now - prefs["last_alert_ts"]) < cooldown:
                continue
            seen.add(nid)
            lat, lon = float(fresh[0]), float(fresh[1])
            short = get_name_from_number(nid, "short", i)
            candidates.append(
                {
                    "node_id": nid,
                    "lat": lat,
                    "lon": lon,
                    "radius_km": prefs["radius_km"],
                    "short": short or str(nid),
                    "iface": i,
                }
            )
    return candidates


def _channel_for_alerts() -> int:
    import modules.settings as st

    ch = getattr(st, "blitz_watch_channel", None)
    if ch is None or ch == "":
        return int(getattr(st, "publicChannel", 0))
    try:
        return int(ch)
    except (TypeError, ValueError):
        return int(getattr(st, "publicChannel", 0))


def run_blitzwatch_cycle(deviceID: int = 1) -> None:
    """Poll lightning and notify affected nodes (DM) + one channel message."""
    global _last_poll_ts
    import modules.settings as st
    from modules.system import send_message
    from modules.wx_extra import fetch_live_strikes_for_region, nearest_strike_for_point

    if not getattr(st, "blitz_watch_enabled", True):
        return
    if not getattr(st, "location_enabled", True):
        return
    if not getattr(st, "blitz_live_data", True):
        return

    now = time.time()
    poll_sec = int(getattr(st, "blitz_watch_poll_sec", POLL_SEC))
    if _last_poll_ts and (now - _last_poll_ts) < poll_sec:
        return
    _last_poll_ts = now

    initialize_blitzwatch_database()
    candidates = _collect_watch_candidates(deviceID)
    if not candidates:
        return

    max_r = max(c["radius_km"] for c in candidates)
    points = [(c["lat"], c["lon"]) for c in candidates]
    strikes, source = fetch_live_strikes_for_region(points, pad_km=float(max_r))
    if not strikes:
        return

    hits: list[dict[str, Any]] = []
    for c in candidates:
        nearest = nearest_strike_for_point(
            c["lat"], c["lon"], strikes, float(c["radius_km"])
        )
        if nearest:
            hits.append({**c, "strike": nearest, "source": source})

    if not hits:
        return

    cooldown = int(getattr(st, "blitz_watch_cooldown_sec", COOLDOWN_SEC))
    try:
        last_ch = float(get_meta(META_CHANNEL_TS, "0") or 0)
    except ValueError:
        last_ch = 0.0
    channel_ok = (now - last_ch) >= cooldown

    ch = _channel_for_alerts()

    # DMs to all hit nodes
    for h in hits:
        strike = h["strike"]
        age = strike.get("age_min")
        age_s = f", vor {age} min" if age is not None else ""
        dir_s = f" {strike['dir']}" if strike.get("dir") else ""
        dm = (
            f"⚡ Blitzwarnung: Einschlag ~{strike['km']:.1f} km{dir_s} "
            f"von dir{age_s}.\n"
            f"!blitzwatch off zum Abschalten · !blitz für Details"
        )
        iface = int(h.get("iface") or deviceID)
        try:
            send_message(dm, ch, h["node_id"], iface)
        except Exception as e:
            logger.warning(f"Blitzwatch: DM to {h['node_id']} failed: {e}")
        mark_node_alerted(h["node_id"], now)

    # One channel message
    if channel_ok:
        parts = [
            f"{h['short']} ~{h['strike']['km']:.0f} km"
            + (f" {h['strike']['dir']}" if h["strike"].get("dir") else "")
            for h in hits
        ]
        if len(hits) == 1:
            ch_msg = f"⚡ Blitz ~{hits[0]['strike']['km']:.1f} km"
            if hits[0]["strike"].get("dir"):
                ch_msg += f" {hits[0]['strike']['dir']}"
            ch_msg += f" von {hits[0]['short']}"
        else:
            ch_msg = "⚡ Blitznähe: " + ", ".join(parts)
        try:
            send_message(ch_msg, ch, 0, deviceID)
            set_meta(META_CHANNEL_TS, str(now))
        except Exception as e:
            logger.warning(f"Blitzwatch: channel send failed: {e}")

    logger.info(
        f"Blitzwatch: {len(hits)} Node(s) alerted"
        + (f" source={source}" if source else "")
    )


def handleBlitzWatch(deviceID: int = 1) -> None:
    """Watchdog entry point (safe wrapper)."""
    try:
        run_blitzwatch_cycle(deviceID)
    except Exception as e:
        logger.error(f"Blitzwatch: cycle error: {e}")
