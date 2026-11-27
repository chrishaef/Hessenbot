# Live link status for the admin overview: Meshtastic interface (hardware / meshtasticd)
# and MQTT data flow. Uses in-memory runtime state only (no shelling out, no secrets).
#
# Signals:
#   hardware  -> interfaceN object, iface.isConnected (threading.Event), retry_intN flag,
#                last packet timestamp per interface (record_rx from mesh_bot.onReceive)
#   MQTT      -> localNode.moduleConfig.mqtt.enabled (node-side flag, no broker credentials)
#                + last packet that arrived via MQTT transport (transport_mechanism / viaMqtt)

from __future__ import annotations

import threading
import time
from html import escape as html_escape
from typing import Any, Dict, Optional

MQTT_FLOW_WINDOW_SEC = 600

_lock = threading.Lock()
_started_ts = time.time()
_last_rx: Dict[int, float] = {}
_last_mqtt_rx: Dict[int, float] = {}
_mqtt_rx_count = 0

_INTERFACE_TYPE_LABELS = {
    "serial": "Serial (USB)",
    "tcp": "TCP (meshtasticd)",
    "ble": "Bluetooth (BLE)",
}


def packet_via_mqtt_transport(packet: Any) -> bool:
    """True when the packet reached the node through its MQTT connection."""
    if not isinstance(packet, dict):
        return False
    decoded = packet.get("decoded") if isinstance(packet.get("decoded"), dict) else {}
    tm = str(
        packet.get("transport_mechanism")
        or packet.get("transportMechanism")
        or decoded.get("transport_mechanism")
        or decoded.get("transportMechanism")
        or ""
    ).lower()
    if tm:
        return "mqtt" in tm
    return bool(packet.get("viaMqtt") or decoded.get("viaMqtt"))


def record_rx(packet: Any, iface_idx: Optional[int], now: Optional[float] = None) -> None:
    """Remember last packet time (any / via MQTT) per interface index."""
    global _mqtt_rx_count
    if not isinstance(packet, dict):
        return
    ts = time.time() if now is None else now
    idx = int(iface_idx) if iface_idx else 0
    mqtt = packet_via_mqtt_transport(packet)
    with _lock:
        _last_rx[idx] = ts
        if mqtt:
            _last_mqtt_rx[idx] = ts
            _mqtt_rx_count += 1


def reset_for_tests() -> None:
    global _mqtt_rx_count, _started_ts
    with _lock:
        _last_rx.clear()
        _last_mqtt_rx.clear()
        _mqtt_rx_count = 0
        _started_ts = time.time()


def format_age(age_sec: Optional[float]) -> str:
    if age_sec is None:
        return "—"
    s = max(0, int(age_sec))
    if s < 60:
        return f"vor {s} s"
    if s < 3600:
        return f"vor {s // 60} min"
    if s < 86400:
        return f"vor {s // 3600} h {(s % 3600) // 60} min"
    return f"vor {s // 86400} d"


def _clock(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _iface_connected(iface: Any) -> bool:
    ev = getattr(iface, "isConnected", None)
    if ev is None:
        return True
    is_set = getattr(ev, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return bool(ev)


def _node_mqtt_enabled(iface: Any) -> Optional[bool]:
    """Node MQTT module on/off from the cached module config; None if not loaded."""
    try:
        mqtt = iface.localNode.moduleConfig.mqtt
        if not iface.localNode.moduleConfig.HasField("mqtt"):
            return None
        return bool(mqtt.enabled)
    except Exception:
        return None


def _node_short_name(iface: Any) -> str:
    try:
        return str(((iface.getMyNodeInfo() or {}).get("user") or {}).get("shortName") or "")
    except Exception:
        return ""


def _hardware_entries(sm: Any, now: float) -> list[Dict[str, Any]]:
    out = []
    with _lock:
        last_rx = dict(_last_rx)
    for i in range(1, 10):
        if not getattr(sm, f"interface{i}_enabled", False):
            continue
        itype = str(getattr(sm, f"interface{i}_type", "") or "").lower()
        label = _INTERFACE_TYPE_LABELS.get(itype, itype or "?")
        iface = getattr(sm, f"interface{i}", None)
        retry = bool(getattr(sm, f"retry_int{i}", False))
        reconnecting = i in getattr(sm, "_interface_reconnecting", ())
        rx_ts = last_rx.get(i)
        rx_age = None if rx_ts is None else now - rx_ts

        if iface is None:
            state = "down"
            text = "Nicht verbunden"
            if reconnecting:
                detail = "Reconnect läuft …"
            elif retry:
                detail = "Reconnect geplant (Watchdog)"
            else:
                detail = ""
            connected = False
        elif not _iface_connected(iface):
            state = "warn"
            text = "Verbindung wird aufgebaut"
            detail = ""
            connected = False
        else:
            state = "ok"
            text = "Verbunden"
            connected = True
            name = _node_short_name(iface)
            detail = f"Node {name}" if name else ""
        out.append(
            {
                "interface": i,
                "type": itype,
                "type_label": label,
                "state": state,
                "text": text,
                "detail": detail,
                "connected": connected,
                "last_rx_ts": rx_ts,
                "last_rx_age_sec": rx_age,
                "mqtt_enabled": _node_mqtt_enabled(iface) if connected else None,
            }
        )
    return out


def _mqtt_entry(hw: list[Dict[str, Any]], now: float) -> Dict[str, Any]:
    with _lock:
        last_ts = max(_last_mqtt_rx.values()) if _last_mqtt_rx else None
        count = _mqtt_rx_count
        started = _started_ts
    age = None if last_ts is None else now - last_ts
    flowing = age is not None and age <= MQTT_FLOW_WINDOW_SEC
    connected_hw = [h for h in hw if h["connected"]]
    node_flags = [h["mqtt_enabled"] for h in connected_hw if h["mqtt_enabled"] is not None]
    node_enabled: Optional[bool]
    if any(node_flags):
        node_enabled = True
    elif node_flags:
        node_enabled = False
    else:
        node_enabled = None

    if flowing:
        state = "ok"
        text = "Daten fließen"
    elif not connected_hw:
        state = "unknown"
        text = "Unbekannt (Hardware nicht verbunden)"
    elif node_enabled is False:
        state = "unknown"
        text = "Am Node nicht aktiviert"
    elif last_ts is None:
        state = "warn"
        text = "Keine MQTT-Pakete seit Bot-Start"
    else:
        state = "warn"
        text = f"Keine MQTT-Pakete seit {int(MQTT_FLOW_WINDOW_SEC / 60)} min"

    parts = []
    if node_enabled is True:
        parts.append("MQTT am Node aktiv")
    elif node_enabled is False and not flowing:
        parts.append("MQTT am Node aus")
    if count:
        parts.append(f"{count} MQTT-Pakete seit Bot-Start")
    elif connected_hw:
        parts.append(f"Beobachtung seit {format_age(now - started)[4:]}")
    return {
        "state": state,
        "text": text,
        "detail": " · ".join(parts),
        "node_enabled": node_enabled,
        "last_rx_ts": last_ts,
        "last_rx_age_sec": age,
        "packet_count": count,
        "window_sec": MQTT_FLOW_WINDOW_SEC,
    }


def collect_link_status(system_mod: Any = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Snapshot for the admin overview (JSON-safe, no secrets)."""
    ts = time.time() if now is None else now
    if system_mod is None:
        import modules.system as system_mod
    hw = _hardware_entries(system_mod, ts)
    mqtt = _mqtt_entry(hw, ts)
    return {"ts": ts, "hardware": hw, "mqtt": mqtt, "html": render_link_status_rows(hw, mqtt)}


_STATE_CLASS = {
    "ok": "status-up",
    "warn": "status-maintenance",
    "down": "status-down",
    "unknown": "",
}


def _row(title: str, state: str, text: str, detail: str, last_ts: Optional[float], age: Optional[float]) -> str:
    cls = _STATE_CLASS.get(state, "")
    seen = ""
    if last_ts is not None:
        seen = f"Letztes Paket {html_escape(format_age(age))} ({html_escape(_clock(last_ts))})"
    extra = " · ".join(p for p in (html_escape(detail) if detail else "", seen) if p)
    extra_html = f'<div class="form-text mb-0">{extra}</div>' if extra else ""
    return (
        '<div class="d-flex align-items-start gap-2 py-1" data-link-state="'
        + html_escape(state)
        + '">'
        f'<span class="status-dot {cls} mt-2" aria-hidden="true"></span>'
        f'<div><span class="fw-semibold">{html_escape(title)}</span> '
        f'<span class="small">{html_escape(text)}</span>{extra_html}</div></div>'
    )


def render_link_status_rows(hw: list[Dict[str, Any]], mqtt: Dict[str, Any]) -> str:
    rows = []
    if not hw:
        rows.append(_row("Hardware", "unknown", "Kein Interface aktiviert", "", None, None))
    for h in hw:
        title = f"Hardware / meshtasticd · Interface {h['interface']} ({h['type_label']})"
        rows.append(
            _row(title, h["state"], h["text"], h["detail"], h["last_rx_ts"], h["last_rx_age_sec"])
        )
    rows.append(
        _row("MQTT", mqtt["state"], mqtt["text"], mqtt["detail"], mqtt["last_rx_ts"], mqtt["last_rx_age_sec"])
    )
    return "".join(rows)


def render_link_status_html() -> str:
    """Overview section: server-rendered rows, refreshed by static/portal/link-status.js."""
    try:
        data = collect_link_status()
        rows = data["html"]
    except Exception:
        rows = _row("Status", "unknown", "Nicht verfügbar", "", None, None)
    return f"""
<div id="link-status" data-api="/api/admin/link-status">
  <div data-link-rows>{rows}</div>
  <div class="form-text text-danger mb-0" data-link-error hidden></div>
</div>
<script src="/static/portal/link-status.js?v=2"></script>
"""
