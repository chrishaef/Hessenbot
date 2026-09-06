# Blitz proximity watch: Home (GPS or fixed) + up to 3 extra locations.
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from typing import Any

from modules.log import logger
from modules.paths import ensure_parent_dir, path_in_repo

trap_list_blitzwatch = ("blitzwatch",)

DEFAULT_RADIUS_KM = 8
MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 10
MAX_EXTRA_LOCATIONS = 3
COOLDOWN_SEC = 3600
POLL_SEC = 300
META_CHANNEL_TS = "last_channel_alert_ts"
HOME_MODE_GPS = "gps"
HOME_MODE_FIXED = "fixed"
WEB_CODE_TTL_SEC = 15 * 60
WEB_CODE_MAX_FAILS = 8
WEB_CODE_MIN_INTERVAL_SEC = 25
WEB_CODE_DIGITS = 5
PUBLIC_SETUP_PATH = "/mein-blitzwatch"

_last_poll_ts = 0.0

_RADIUS_TOKEN_RE = re.compile(r"^(\d+)\s*km?$", re.IGNORECASE)


def _db_path() -> str:
    import modules.settings as st

    rel = getattr(st, "blitzwatch_db", "data/blitzwatch.db") or "data/blitzwatch.db"
    return path_in_repo(rel)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in c.fetchall()}


def _ensure_home_columns(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn, "blitzwatch")
    c = conn.cursor()
    if "home_mode" not in cols:
        c.execute(
            "ALTER TABLE blitzwatch ADD COLUMN home_mode TEXT NOT NULL DEFAULT 'gps'"
        )
    if "home_lat" not in cols:
        c.execute("ALTER TABLE blitzwatch ADD COLUMN home_lat REAL")
    if "home_lon" not in cols:
        c.execute("ALTER TABLE blitzwatch ADD COLUMN home_lon REAL")
    if "home_label" not in cols:
        c.execute("ALTER TABLE blitzwatch ADD COLUMN home_label TEXT")


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
                last_alert_ts REAL NOT NULL DEFAULT 0,
                home_mode TEXT NOT NULL DEFAULT 'gps',
                home_lat REAL,
                home_lon REAL,
                home_label TEXT
            )"""
        )
        _ensure_home_columns(conn)
        c.execute(
            """CREATE TABLE IF NOT EXISTS blitzwatch_locations (
                id INTEGER PRIMARY KEY,
                node_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                label TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                radius_km INTEGER NOT NULL,
                last_alert_ts REAL NOT NULL DEFAULT 0,
                UNIQUE(node_id, slot)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS blitzwatch_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )"""
        )
        _ensure_web_code_table(conn)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Blitzwatch: DB init failed: {e}")
        return False


def _ensure_web_code_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS blitzwatch_web_codes (
            code_hash TEXT PRIMARY KEY,
            node_id INTEGER NOT NULL UNIQUE,
            expires_ts REAL NOT NULL,
            fails INTEGER NOT NULL DEFAULT 0,
            created_ts REAL NOT NULL
        )"""
    )


def _web_code_hmac_key() -> bytes:
    import modules.settings as st

    secret = (getattr(st, "web_admin_secret_key", "") or "").strip()
    if not secret:
        secret = "hessenbot-blitzwatch-web"
    return secret.encode("utf-8")


def hash_web_setup_code(code: str) -> str:
    return hmac.new(
        _web_code_hmac_key(),
        str(code).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def public_setup_url() -> str:
    """Absolute URL to the public PIN page, or empty if publicUrl is unset."""
    import modules.settings as st

    base = (getattr(st, "web_admin_public_url", "") or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}{PUBLIC_SETUP_PATH}"


def issue_web_setup_code(node_id: int) -> tuple[str | None, str | None]:
    """Create a one-time 5-digit web code. Returns (code, error)."""
    initialize_blitzwatch_database()
    nid = int(node_id)
    now = time.time()
    conn = _connect()
    _ensure_web_code_table(conn)
    c = conn.cursor()
    c.execute("DELETE FROM blitzwatch_web_codes WHERE expires_ts < ?", (now,))
    c.execute(
        "SELECT created_ts FROM blitzwatch_web_codes WHERE node_id=?",
        (nid,),
    )
    row = c.fetchone()
    if row and (now - float(row[0])) < WEB_CODE_MIN_INTERVAL_SEC:
        conn.commit()
        conn.close()
        wait = int(WEB_CODE_MIN_INTERVAL_SEC - (now - float(row[0]))) + 1
        return None, f"Bitte {wait}s warten, dann !blitzwatch web erneut senden."

    code = None
    digest = None
    for _ in range(48):
        candidate = f"{secrets.randbelow(10 ** WEB_CODE_DIGITS):0{WEB_CODE_DIGITS}d}"
        digest = hash_web_setup_code(candidate)
        c.execute(
            "SELECT 1 FROM blitzwatch_web_codes WHERE code_hash=?",
            (digest,),
        )
        if not c.fetchone():
            code = candidate
            break
    if not code or not digest:
        conn.close()
        return None, "Kein freier Code, später erneut versuchen."

    c.execute("DELETE FROM blitzwatch_web_codes WHERE node_id=?", (nid,))
    c.execute(
        """INSERT INTO blitzwatch_web_codes
           (code_hash, node_id, expires_ts, fails, created_ts)
           VALUES (?, ?, ?, 0, ?)""",
        (digest, nid, now + WEB_CODE_TTL_SEC, now),
    )
    conn.commit()
    conn.close()
    return code, None


def consume_web_setup_code(raw: str) -> tuple[int | None, str | None]:
    """Redeem a PIN. Returns (node_id, error)."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != WEB_CODE_DIGITS:
        return None, "Bitte den 5-stelligen Code aus der Bot-DM eingeben."
    initialize_blitzwatch_database()
    now = time.time()
    digest = hash_web_setup_code(digits)
    conn = _connect()
    _ensure_web_code_table(conn)
    c = conn.cursor()
    c.execute("DELETE FROM blitzwatch_web_codes WHERE expires_ts < ?", (now,))
    c.execute(
        "SELECT node_id, fails FROM blitzwatch_web_codes WHERE code_hash=?",
        (digest,),
    )
    row = c.fetchone()
    if not row:
        conn.commit()
        conn.close()
        return None, "Code ungültig oder abgelaufen. Neu anfordern: !blitzwatch web"
    nid = int(row[0])
    fails = int(row[1] or 0)
    if fails >= WEB_CODE_MAX_FAILS:
        c.execute("DELETE FROM blitzwatch_web_codes WHERE code_hash=?", (digest,))
        conn.commit()
        conn.close()
        return None, "Code ungültig oder abgelaufen. Neu anfordern: !blitzwatch web"
    c.execute("DELETE FROM blitzwatch_web_codes WHERE code_hash=?", (digest,))
    conn.commit()
    conn.close()
    return nid, None


def _connect() -> sqlite3.Connection:
    path = _db_path()
    ensure_parent_dir(path)
    conn = sqlite3.connect(path)
    return conn


def clamp_radius_km(value: int) -> int:
    try:
        import modules.settings as st

        max_r = int(getattr(st, "blitz_watch_max_radius_km", MAX_RADIUS_KM))
    except Exception:
        max_r = MAX_RADIUS_KM
    max_r = max(MIN_RADIUS_KM, min(50, max_r))  # hard ceiling
    return max(MIN_RADIUS_KM, min(max_r, int(value)))


def _default_radius() -> int:
    import modules.settings as st

    return clamp_radius_km(
        int(getattr(st, "blitz_watch_default_radius_km", DEFAULT_RADIUS_KM))
    )


def _prefs_from_row(row: tuple | None, *, in_db: bool) -> dict[str, Any]:
    default_r = _default_radius()
    if not row:
        return {
            "enabled": True,
            "radius_km": default_r,
            "last_alert_ts": 0.0,
            "home_mode": HOME_MODE_GPS,
            "home_lat": None,
            "home_lon": None,
            "home_label": None,
            "in_db": False,
        }
    (
        enabled,
        radius_km,
        last_alert_ts,
        home_mode,
        home_lat,
        home_lon,
        home_label,
    ) = row
    mode = (home_mode or HOME_MODE_GPS).lower()
    if mode not in (HOME_MODE_GPS, HOME_MODE_FIXED):
        mode = HOME_MODE_GPS
    return {
        "enabled": bool(enabled),
        "radius_km": clamp_radius_km(radius_km if radius_km is not None else default_r),
        "last_alert_ts": float(last_alert_ts or 0),
        "home_mode": mode,
        "home_lat": float(home_lat) if home_lat is not None else None,
        "home_lon": float(home_lon) if home_lon is not None else None,
        "home_label": (home_label or None),
        "in_db": in_db,
    }


def get_node_prefs(node_id: int) -> dict[str, Any]:
    """Return prefs; missing row → default enabled with default radius."""
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute(
            """SELECT enabled, radius_km, last_alert_ts,
                      home_mode, home_lat, home_lon, home_label
               FROM blitzwatch WHERE node_id=?""",
            (int(node_id),),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return _prefs_from_row(row, in_db=True)
    except Exception as e:
        logger.debug(f"Blitzwatch: get_node_prefs: {e}")
        initialize_blitzwatch_database()
    return _prefs_from_row(None, in_db=False)


def _upsert_node_row(
    node_id: int,
    *,
    enabled: int | None = None,
    radius_km: int | None = None,
    last_alert_ts: float | None = None,
    home_mode: str | None = None,
    home_lat: float | None = ...,
    home_lon: float | None = ...,
    home_label: str | None = ...,
) -> dict[str, Any]:
    """Upsert blitzwatch row; Ellipsis means leave existing / default home fields alone."""
    prefs = get_node_prefs(node_id)
    en = prefs["enabled"] if enabled is None else bool(enabled)
    rad = prefs["radius_km"] if radius_km is None else clamp_radius_km(radius_km)
    last = prefs["last_alert_ts"] if last_alert_ts is None else float(last_alert_ts)
    mode = prefs["home_mode"] if home_mode is None else home_mode
    lat = prefs["home_lat"] if home_lat is ... else home_lat
    lon = prefs["home_lon"] if home_lon is ... else home_lon
    label = prefs["home_label"] if home_label is ... else home_label

    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO blitzwatch (
               node_id, enabled, radius_km, last_alert_ts,
               home_mode, home_lat, home_lon, home_label
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(node_id) DO UPDATE SET
             enabled=excluded.enabled,
             radius_km=excluded.radius_km,
             last_alert_ts=excluded.last_alert_ts,
             home_mode=excluded.home_mode,
             home_lat=excluded.home_lat,
             home_lon=excluded.home_lon,
             home_label=excluded.home_label""",
        (
            int(node_id),
            1 if en else 0,
            rad,
            last,
            mode,
            lat,
            lon,
            label,
        ),
    )
    conn.commit()
    conn.close()
    return get_node_prefs(node_id)


def set_node_enabled(node_id: int, enabled: bool) -> dict[str, Any]:
    return _upsert_node_row(node_id, enabled=1 if enabled else 0)


def set_node_radius(node_id: int, radius_km: int) -> dict[str, Any]:
    """Set home radius and enable watch."""
    return _upsert_node_row(node_id, enabled=1, radius_km=radius_km)


def set_home_fixed(
    node_id: int, lat: float, lon: float, label: str, *, radius_km: int | None = None
) -> dict[str, Any]:
    return _upsert_node_row(
        node_id,
        enabled=1,
        radius_km=radius_km,
        home_mode=HOME_MODE_FIXED,
        home_lat=float(lat),
        home_lon=float(lon),
        home_label=(label or f"{lat:.2f}, {lon:.2f}")[:80],
    )


def set_home_gps(node_id: int) -> dict[str, Any]:
    return _upsert_node_row(
        node_id,
        home_mode=HOME_MODE_GPS,
        home_lat=None,
        home_lon=None,
        home_label=None,
    )


def mark_home_alerted(node_id: int, when: float | None = None) -> None:
    ts = float(when if when is not None else time.time())
    _upsert_node_row(node_id, last_alert_ts=ts)


# Backwards-compatible alias used by older tests / callers
mark_node_alerted = mark_home_alerted


def list_locations(node_id: int) -> list[dict[str, Any]]:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute(
            """SELECT slot, label, lat, lon, radius_km, last_alert_ts
               FROM blitzwatch_locations
               WHERE node_id=?
               ORDER BY slot""",
            (int(node_id),),
        )
        rows = c.fetchall()
        conn.close()
        return [
            {
                "slot": int(slot),
                "label": label,
                "lat": float(lat),
                "lon": float(lon),
                "radius_km": clamp_radius_km(radius_km),
                "last_alert_ts": float(last_alert_ts or 0),
            }
            for slot, label, lat, lon, radius_km, last_alert_ts in rows
        ]
    except Exception as e:
        logger.debug(f"Blitzwatch: list_locations: {e}")
        initialize_blitzwatch_database()
        return []


def count_locations(node_id: int) -> int:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM blitzwatch_locations WHERE node_id=?",
            (int(node_id),),
        )
        n = int(c.fetchone()[0])
        conn.close()
        return n
    except Exception:
        return 0


def _next_free_slot(node_id: int) -> int | None:
    used = {loc["slot"] for loc in list_locations(node_id)}
    for slot in range(1, MAX_EXTRA_LOCATIONS + 1):
        if slot not in used:
            return slot
    return None


def add_location(
    node_id: int,
    lat: float,
    lon: float,
    label: str,
    radius_km: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Add extra location in next free slot. Returns (loc, error)."""
    initialize_blitzwatch_database()
    slot = _next_free_slot(node_id)
    if slot is None:
        return None, f"Maximal {MAX_EXTRA_LOCATIONS} Zusatzorte. Erst mit del N löschen."
    radius = clamp_radius_km(
        radius_km if radius_km is not None else get_node_prefs(node_id)["radius_km"]
    )
    lab = (label or f"{lat:.2f}, {lon:.2f}")[:80]
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """INSERT INTO blitzwatch_locations
           (node_id, slot, label, lat, lon, radius_km, last_alert_ts)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        (int(node_id), slot, lab, float(lat), float(lon), radius),
    )
    conn.commit()
    conn.close()
    # Ensure node row exists and watch is on
    set_node_enabled(node_id, True)
    locs = [x for x in list_locations(node_id) if x["slot"] == slot]
    return (locs[0] if locs else None), None


def delete_location(node_id: int, slot: int) -> bool:
    if slot < 1 or slot > MAX_EXTRA_LOCATIONS:
        return False
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "DELETE FROM blitzwatch_locations WHERE node_id=? AND slot=?",
        (int(node_id), int(slot)),
    )
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def reset_watch_for_node(node_id: int) -> bool:
    """Remove stored prefs and extra locations (back to defaults)."""
    initialize_blitzwatch_database()
    nid = int(node_id)
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM blitzwatch_locations WHERE node_id=?", (nid,))
    loc_n = c.rowcount
    c.execute("DELETE FROM blitzwatch WHERE node_id=?", (nid,))
    deleted = loc_n > 0 or c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def list_admin_watchers() -> list[dict[str, Any]]:
    """All nodes with a DB row and/or extra locations, for the admin UI."""
    initialize_blitzwatch_database()
    prefs_map = get_all_prefs_map()
    out: list[dict[str, Any]] = []
    for nid in sorted(prefs_map):
        prefs = dict(prefs_map[nid])
        prefs["node_id"] = nid
        locs = list_locations(nid)
        prefs["locations"] = locs
        prefs["extra_count"] = len(locs)
        out.append(prefs)
    return out


def set_location_radius(node_id: int, slot: int, radius_km: int) -> dict[str, Any] | None:
    if slot < 1 or slot > MAX_EXTRA_LOCATIONS:
        return None
    radius = clamp_radius_km(radius_km)
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """UPDATE blitzwatch_locations SET radius_km=?
           WHERE node_id=? AND slot=?""",
        (radius, int(node_id), int(slot)),
    )
    ok = c.rowcount > 0
    conn.commit()
    conn.close()
    if not ok:
        return None
    for loc in list_locations(node_id):
        if loc["slot"] == slot:
            return loc
    return None


def mark_location_alerted(node_id: int, slot: int, when: float | None = None) -> None:
    ts = float(when if when is not None else time.time())
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """UPDATE blitzwatch_locations SET last_alert_ts=?
           WHERE node_id=? AND slot=?""",
        (ts, int(node_id), int(slot)),
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
    """node_id → prefs (+ extra_count) for UI enrichment."""
    out: dict[int, dict[str, Any]] = {}
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute(
            """SELECT node_id, enabled, radius_km, last_alert_ts,
                      home_mode, home_lat, home_lon, home_label
               FROM blitzwatch"""
        )
        for row in c.fetchall():
            node_id = int(row[0])
            prefs = _prefs_from_row(row[1:], in_db=True)
            out[node_id] = prefs
        c.execute(
            "SELECT node_id, COUNT(*) FROM blitzwatch_locations GROUP BY node_id"
        )
        counts = {int(nid): int(n) for nid, n in c.fetchall()}
        conn.close()
        for nid, prefs in out.items():
            prefs["extra_count"] = counts.get(nid, 0)
        for nid, n in counts.items():
            if nid not in out:
                prefs = get_node_prefs(nid)
                prefs["extra_count"] = n
                out[nid] = prefs
    except Exception as e:
        logger.debug(f"Blitzwatch: get_all_prefs_map: {e}")
    return out


def _parse_radius_token(token: str) -> int | None:
    m = _RADIUS_TOKEN_RE.fullmatch((token or "").strip())
    if not m:
        return None
    return int(m.group(1))


def _radius_set_message(raw: int, clamped: int) -> str | None:
    try:
        import modules.settings as st

        max_r = int(getattr(st, "blitz_watch_max_radius_km", MAX_RADIUS_KM))
    except Exception:
        max_r = MAX_RADIUS_KM
    max_r = max(MIN_RADIUS_KM, min(50, max_r))
    if raw > max_r:
        return f"Radius auf Maximum {max_r} km gesetzt (AN)."
    if raw < MIN_RADIUS_KM:
        return f"Radius auf Minimum {MIN_RADIUS_KM} km gesetzt (AN)."
    return None


def _resolve_explicit_location(
    message: str,
    node_id: int,
    device_id: int,
    command_tokens: tuple[str, ...],
) -> tuple[tuple[float, float, str] | None, str | None]:
    """Resolve Ort/Coords/Grid; require explicit arg (no GPS fallback)."""
    from modules.locationdata import resolve_message_location

    lat, lon, source, label = resolve_message_location(
        message,
        node_id,
        device_id,
        command_tokens=command_tokens,
    )
    if source == "error":
        return None, label
    if source in ("gps", "bot", "missing") or lat is None or lon is None:
        return None, "Standort fehlt (Ort, Koordinaten oder Maidenhead-Grid)."
    return (float(lat), float(lon), label or f"{lat:.2f}, {lon:.2f}"), None


def format_status(node_id: int, *, has_fresh_gps: bool) -> str:
    import modules.settings as st

    global_on = bool(getattr(st, "blitz_watch_enabled", True))
    prefs = get_node_prefs(node_id)
    locs = list_locations(node_id)
    node_on = bool(prefs["enabled"]) and global_on
    lines = ["⚡ Blitzwatch"]
    if not global_on:
        lines.append("Warnung: AUS (vom Admin deaktiviert)")
    else:
        lines.append(f"Warnung für deine Node: {'AN' if node_on else 'AUS'}")

    if prefs["home_mode"] == HOME_MODE_FIXED and prefs["home_lat"] is not None:
        home_s = f"Fix {prefs['home_label'] or f'{prefs['home_lat']:.2f}, {prefs['home_lon']:.2f}'}"
    elif has_fresh_gps:
        home_s = "GPS (≤24h)"
    else:
        home_s = "GPS fehlt (≤24h)"
    lines.append(f"Home: {home_s} · Radius {prefs['radius_km']} km")

    if locs:
        for loc in locs:
            lines.append(f"Ort {loc['slot']}: {loc['label']} · {loc['radius_km']} km")
    else:
        lines.append(f"Zusatzorte: keine (max. {MAX_EXTRA_LOCATIONS})")

    if prefs["last_alert_ts"]:
        ago = int((time.time() - prefs["last_alert_ts"]) / 60)
        lines.append(f"Letzte Home-Warnung: vor {ago} min")

    lines.append("Einstellen: !blitzwatch? · Web: !blitzwatch web")
    if node_on:
        lines.append("Aus: !blitzwatch off")
    else:
        lines.append("Ein: !blitzwatch on")
    lines.append("Home-Ort: !blitzwatch home Friedberg")
    return "\n".join(lines)


def format_location_list(node_id: int, *, has_fresh_gps: bool) -> str:
    prefs = get_node_prefs(node_id)
    locs = list_locations(node_id)
    lines = ["⚡ Blitzwatch Standorte"]
    if prefs["home_mode"] == HOME_MODE_FIXED and prefs["home_lat"] is not None:
        lines.append(
            f"Home (Fix): {prefs['home_label']} · {prefs['radius_km']} km"
        )
    else:
        gps = "GPS ok" if has_fresh_gps else "kein GPS"
        lines.append(f"Home ({gps}): {prefs['radius_km']} km")
    if not locs:
        lines.append("Keine Zusatzorte.")
    else:
        for loc in locs:
            lines.append(f"Ort {loc['slot']}: {loc['label']} · {loc['radius_km']} km")
    free = MAX_EXTRA_LOCATIONS - len(locs)
    lines.append(f"Frei: {free}/{MAX_EXTRA_LOCATIONS}")
    if locs:
        example = locs[0]["slot"]
        lines.append(f"Radius ändern: !blitzwatch {example} 5km")
    return "\n".join(lines)


def _usage() -> str:
    return (
        "⚡ Blitzwatch — Einstellen\n"
        "Ein/Aus:\n"
        "!blitzwatch on\n"
        "!blitzwatch off\n"
        "Home (dein Standort):\n"
        "!blitzwatch 8km\n"
        "!blitzwatch home Friedberg\n"
        "!blitzwatch home gps\n"
        "Zusatzorte (max. 3):\n"
        "!blitzwatch add Kassel\n"
        "!blitzwatch add 5km JO40AA\n"
        "!blitzwatch del 1\n"
        "Radius Slot: !blitzwatch 1 5km\n"
        "Status: !blitzwatch · Liste: !blitzwatch list\n"
        "Web: !blitzwatch web · !blitzwatch set (Code per DM)"
    )


def handle_blitzwatch_command(
    message: str,
    message_from_id: int,
    deviceID: int = 1,
    *,
    is_dm: bool = True,
) -> str:
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
    nid = int(message_from_id)

    text = (message or "").strip()
    if text.startswith("!"):
        text = text[1:].strip()
    parts = text.replace("?", " ? ").split()
    args = [p for p in parts if p.lower().rstrip("?") != "blitzwatch"]

    if not args:
        return format_status(nid, has_fresh_gps=has_gps)
    if args[0].lower() in ("?", "help", "hilfe"):
        return _usage()
    if args[0].lower() == "status":
        return format_status(nid, has_fresh_gps=has_gps)

    token = args[0].lower().strip()

    if token in ("set", "web", "code", "pin"):
        if not is_dm:
            return (
                "Web-Code nur per DM — schreib mir direkt:\n"
                "!blitzwatch web"
            )
        code, err = issue_web_setup_code(nid)
        if err:
            return err
        mins = max(1, int(WEB_CODE_TTL_SEC // 60))
        url = public_setup_url()
        lines = [
            f"Blitzwatch-Code: {code}",
            f"{mins} Min., einmalig.",
            "Webseite → Menü Blitzwatch",
        ]
        if url:
            lines.append(url)
        return "\n".join(lines)

    if token in ("on", "an", "ein"):
        set_node_enabled(nid, True)
        return format_status(nid, has_fresh_gps=has_gps)

    if token in ("off", "aus"):
        set_node_enabled(nid, False)
        return (
            "Blitzwatch für deine Node: AUS.\n"
            "Mit !blitzwatch on wieder einschalten."
        )

    if token in ("list", "liste", "ls"):
        return format_location_list(nid, has_fresh_gps=has_gps)

    # home gps | home 5km | home <location>
    if token == "home":
        rest = args[1:]
        if not rest:
            return (
                "Home setzen: !blitzwatch home <Ort|Coords|Grid>\n"
                "oder: !blitzwatch home gps · home 5km"
            )
        if rest[0].lower() in ("gps", "node", "gerät", "geraet"):
            set_home_gps(nid)
            return "Home: wieder GPS.\n" + format_status(nid, has_fresh_gps=has_gps)

        r_tok = _parse_radius_token(rest[0])
        if r_tok is not None and len(rest) == 1:
            raw = r_tok
            clamped = clamp_radius_km(raw)
            set_node_radius(nid, clamped)
            note = _radius_set_message(raw, clamped)
            prefix = (note + "\n") if note else f"Home-Radius: {clamped} km (AN).\n"
            return prefix + format_status(nid, has_fresh_gps=has_gps)

        resolved, err = _resolve_explicit_location(
            message, nid, deviceID, ("blitzwatch", "home")
        )
        if err:
            return err
        assert resolved is not None
        lat, lon, label = resolved
        set_home_fixed(nid, lat, lon, label)
        return f"Home Fix: {label} · {get_node_prefs(nid)['radius_km']} km\n" + format_status(
            nid, has_fresh_gps=has_gps
        )

    # add [Nkm] <location>
    if token == "add":
        rest = args[1:]
        if not rest:
            return "Zusatzort: !blitzwatch add <Ort|Coords|Grid>\noder: add 5km <…>"
        radius_override: int | None = None
        loc_msg = message
        r_tok = _parse_radius_token(rest[0])
        if r_tok is not None:
            if len(rest) < 2:
                return "Nach dem Radius fehlt der Standort (Ort/Coords/Grid)."
            radius_override = clamp_radius_km(r_tok)
            # Rebuild message without the radius token for resolver
            loc_msg = "!blitzwatch add " + " ".join(rest[1:])
        resolved, err = _resolve_explicit_location(
            loc_msg, nid, deviceID, ("blitzwatch", "add")
        )
        if err:
            return err
        assert resolved is not None
        lat, lon, label = resolved
        loc, add_err = add_location(nid, lat, lon, label, radius_override)
        if add_err:
            return add_err
        assert loc is not None
        return (
            f"Zusatzort {loc['slot']}: {loc['label']} · {loc['radius_km']} km\n"
            + format_location_list(nid, has_fresh_gps=has_gps)
        )

    # del N / rm N
    if token in ("del", "rm", "delete", "remove", "lösche", "loesche"):
        if len(args) < 2 or not args[1].isdigit():
            return "Löschen: !blitzwatch del N  (N = 1…3)"
        slot = int(args[1])
        if delete_location(nid, slot):
            return f"Zusatzort {slot} gelöscht.\n" + format_location_list(
                nid, has_fresh_gps=has_gps
            )
        return f"Kein Zusatzort {slot}."

    # N 5km — slot radius
    if token.isdigit() and len(args) >= 2:
        slot = int(token)
        if 1 <= slot <= MAX_EXTRA_LOCATIONS:
            r_tok = _parse_radius_token(args[1])
            if r_tok is None and len(args) >= 3 and args[2].lower().startswith("km"):
                r_tok = int(args[1]) if args[1].isdigit() else None
            if r_tok is not None:
                loc = set_location_radius(nid, slot, r_tok)
                if not loc:
                    return f"Kein Zusatzort {slot}. Mit add anlegen."
                note = _radius_set_message(r_tok, loc["radius_km"])
                prefix = (
                    (note + "\n")
                    if note
                    else f"Slot {slot}: Radius {loc['radius_km']} km.\n"
                )
                return prefix + format_location_list(nid, has_fresh_gps=has_gps)

    # Home radius: 5, 5km, 5 km
    m = _RADIUS_TOKEN_RE.fullmatch(token)
    if not m and len(args) >= 2 and token.isdigit() and args[1].lower().startswith("km"):
        m = re.fullmatch(r"(\d+)", token)
    if m:
        raw = int(m.group(1))
        radius = clamp_radius_km(raw)
        set_node_radius(nid, radius)
        note = _radius_set_message(raw, radius)
        prefix = (note + "\n") if note else f"Home-Radius: {radius} km (AN).\n"
        return prefix + format_status(nid, has_fresh_gps=has_gps)

    return _usage()


def _bot_node_ids(deviceID: int) -> set[int]:
    import modules.system as sysmod

    my_ids: set[int] = set()
    try:
        iface_order = [deviceID] + [i for i in range(1, 10) if i != deviceID]
        for i in iface_order:
            if not sysmod.__dict__.get(f"interface{i}_enabled"):
                continue
            mid = sysmod.__dict__.get(f"myNodeNum{i}")
            if mid:
                my_ids.add(int(mid))
    except Exception as e:
        logger.debug(f"Blitzwatch: bot ids: {e}")
    return my_ids


def _collect_watch_candidates(deviceID: int) -> list[dict[str, Any]]:
    """Watch points: home (GPS or fixed) + extra slots, per enabled node."""
    import modules.settings as st
    import modules.system as sysmod
    from modules.system import _nodedb_fresh_position, get_name_from_number

    cooldown = int(getattr(st, "blitz_watch_cooldown_sec", COOLDOWN_SEC))
    now = time.time()
    candidates: list[dict[str, Any]] = []
    my_ids = _bot_node_ids(deviceID)
    seen: set[int] = set()

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
            seen.add(nid)

            prefs = get_node_prefs(nid)
            if not prefs["enabled"]:
                continue

            short = get_name_from_number(nid, "short", i) or str(nid)
            extras = list_locations(nid)

            # Home watch point
            home_lat = home_lon = None
            home_label = "dir"
            kind = "home"
            if prefs["home_mode"] == HOME_MODE_FIXED and prefs["home_lat"] is not None:
                home_lat = float(prefs["home_lat"])
                home_lon = float(prefs["home_lon"])
                home_label = prefs["home_label"] or "Home"
            else:
                fresh = _nodedb_fresh_position(nid, i, 2)
                if fresh:
                    home_lat = float(fresh[0])
                    home_lon = float(fresh[1])
                    home_label = "dir"

            if home_lat is not None and home_lon is not None:
                last = float(prefs["last_alert_ts"] or 0)
                if not last or (now - last) >= cooldown:
                    candidates.append(
                        {
                            "node_id": nid,
                            "kind": kind,
                            "slot": 0,
                            "lat": home_lat,
                            "lon": home_lon,
                            "radius_km": prefs["radius_km"],
                            "label": home_label,
                            "short": short,
                            "iface": i,
                        }
                    )

            for loc in extras:
                last = float(loc["last_alert_ts"] or 0)
                if last and (now - last) < cooldown:
                    continue
                candidates.append(
                    {
                        "node_id": nid,
                        "kind": "extra",
                        "slot": loc["slot"],
                        "lat": loc["lat"],
                        "lon": loc["lon"],
                        "radius_km": loc["radius_km"],
                        "label": loc["label"],
                        "short": short,
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


def _dm_where_phrase(hit: dict[str, Any]) -> str:
    if hit.get("kind") == "home" and hit.get("label") in (None, "", "dir"):
        return "von dir"
    label = hit.get("label") or "Standort"
    return f"bei {label}"


def _channel_where_phrase(hit: dict[str, Any]) -> str:
    short = hit.get("short") or str(hit.get("node_id"))
    if hit.get("kind") == "home" and hit.get("label") in (None, "", "dir"):
        return f"von {short}"
    label = hit.get("label") or "Standort"
    return f"von {short} bei {label}"


def run_blitzwatch_cycle(deviceID: int = 1) -> None:
    """Poll lightning and notify affected watch points (DM) + one channel message."""
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

    # DMs — one per hit watch-point (same node may get several if multiple slots hit)
    for h in hits:
        strike = h["strike"]
        age = strike.get("age_min")
        age_s = f", vor {age} min" if age is not None else ""
        dir_s = f" {strike['dir']}" if strike.get("dir") else ""
        where = _dm_where_phrase(h)
        dm = (
            f"⚡ Blitzwarnung: Einschlag ~{strike['km']:.1f} km{dir_s} "
            f"{where}{age_s}.\n"
            f"!blitzwatch off zum Abschalten · !blitz für Details"
        )
        iface = int(h.get("iface") or deviceID)
        try:
            send_message(dm, ch, h["node_id"], iface)
        except Exception as e:
            logger.warning(f"Blitzwatch: DM to {h['node_id']} failed: {e}")

        if h.get("kind") == "extra":
            mark_location_alerted(h["node_id"], int(h["slot"]), now)
        else:
            mark_home_alerted(h["node_id"], now)

    # One channel message
    if channel_ok:
        if len(hits) == 1:
            h0 = hits[0]
            ch_msg = f"⚡ Blitz ~{h0['strike']['km']:.1f} km"
            if h0["strike"].get("dir"):
                ch_msg += f" {h0['strike']['dir']}"
            ch_msg += f" {_channel_where_phrase(h0)}"
        else:
            parts = []
            for h in hits:
                bit = f"{h['short']}"
                if h.get("kind") == "extra" or (
                    h.get("kind") == "home" and h.get("label") not in (None, "", "dir")
                ):
                    bit += f"/{h.get('label', '?')}"
                bit += f" ~{h['strike']['km']:.0f} km"
                if h["strike"].get("dir"):
                    bit += f" {h['strike']['dir']}"
                parts.append(bit)
            ch_msg = "⚡ Blitznähe: " + ", ".join(parts)
        try:
            send_message(ch_msg, ch, 0, deviceID)
            set_meta(META_CHANNEL_TS, str(now))
        except Exception as e:
            logger.warning(f"Blitzwatch: channel send failed: {e}")

    logger.info(
        f"Blitzwatch: {len(hits)} point(s) alerted"
        + (f" source={source}" if source else "")
    )


def handleBlitzWatch(deviceID: int = 1) -> None:
    """Watchdog entry point (safe wrapper)."""
    try:
        run_blitzwatch_cycle(deviceID)
    except Exception as e:
        logger.error(f"Blitzwatch: cycle error: {e}")
