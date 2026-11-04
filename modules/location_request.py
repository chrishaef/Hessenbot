# Async mesh position request when a command needs the requester's location.
# Never falls back to bot/config lat/lon for user nodes.

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

BuildResponseFn = Callable[[float, float, str, str], str]

_lock = threading.RLock()
_pending: dict[str, dict[str, Any]] = {}
_last_request_ts: dict[str, float] = {}

_cmd_ctx = threading.local()


def set_command_context(
    *,
    channel: int = 0,
    is_dm: bool = True,
    device_id: int = 1,
    node_id: int = 0,
    reply_id=None,
) -> None:
    _cmd_ctx.data = {
        "channel": int(channel or 0),
        "is_dm": bool(is_dm),
        "device_id": int(device_id or 1),
        "node_id": int(node_id or 0),
        "reply_id": reply_id,
    }


def get_command_context() -> dict:
    return dict(getattr(_cmd_ctx, "data", {}) or {})


def _settings():
    import modules.settings as st

    return st


def _timeout_sec() -> int:
    return max(5, int(getattr(_settings(), "location_request_timeout_sec", 25) or 25))


def _cooldown_sec() -> int:
    return max(0, int(getattr(_settings(), "location_request_cooldown_sec", 60) or 60))


def _enabled() -> bool:
    return bool(getattr(_settings(), "location_request_enabled", True))


def lookup_known_node_location(node_id, device_id: int = 1, round_digits: int = 2):
    """Return (lat, lon, source) from NodeDB or mesh map only — never bot config."""
    from modules.system import get_node_location_with_source

    result = get_node_location_with_source(node_id, device_id, round_digits=round_digits)
    if not result or len(result) < 3:
        return None
    lat, lon, from_gps = result[0], result[1], result[2]
    if lat is None or lon is None or not from_gps:
        return None
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None
    if int(lat_f) == 0 and int(lon_f) == 0:
        return None
    return lat_f, lon_f, "gps"


def cancel_pending(node_id) -> bool:
    with _lock:
        return _pending.pop(str(node_id), None) is not None


def has_pending(node_id) -> bool:
    with _lock:
        return str(node_id) in _pending


def _send_ack(node_id: int, device_id: int, channel: int, is_dm: bool) -> None:
    from modules.locale_de import location_request_ack
    from modules.system import send_message
    import modules.settings as st

    dest = node_id if (is_dm or getattr(st, "useDMForResponse", True)) else 0
    send_message(location_request_ack(), channel, dest, device_id)


def _send_text(
    text: str,
    node_id: int,
    device_id: int,
    channel: int,
    is_dm: bool,
    reply_id=None,
) -> None:
    if not text:
        return
    from modules.system import send_message
    import modules.settings as st

    dest = node_id if (is_dm or getattr(st, "useDMForResponse", True)) else 0
    kwargs = {}
    if reply_id is not None and dest == 0:
        kwargs["reply_id"] = reply_id
    send_message(text, channel, dest, device_id, **kwargs)


def _fire_position_request(device_id: int, node_id: int, channel: int) -> None:
    """Ask the node for a position without blocking onReceive."""
    try:
        import modules.system as sysmod

        iface = getattr(sysmod, f"interface{device_id}", None)
    except Exception:
        iface = None
    if iface is None:
        logger.debug(f"LocationRequest: no interface{device_id} for node {node_id}")
        return
    try:
        from meshtastic import mesh_pb2
        from meshtastic import portnums_pb2

        def _on_response(_packet):
            try:
                try_complete_pending_location(node_id)
            except Exception as e:
                logger.debug(f"LocationRequest: onResponse complete failed: {e}")

        pos = mesh_pb2.Position()
        iface.sendData(
            pos,
            destinationId=int(node_id),
            portNum=portnums_pb2.PortNum.POSITION_APP,
            wantAck=False,
            wantResponse=True,
            onResponse=_on_response,
            channelIndex=int(channel or 0),
        )
        logger.info(
            f"LocationRequest: POSITION request sent to {node_id} via IF{device_id} ch={channel}"
        )
    except Exception as e:
        logger.warning(f"LocationRequest: send failed for {node_id}: {e}")
        try:
            iface.sendPosition(
                destinationId=int(node_id),
                wantResponse=False,
                channelIndex=int(channel or 0),
            )
        except Exception as e2:
            logger.debug(f"LocationRequest: sendPosition fallback failed: {e2}")


def _timeout_message(cmd_key: str, timeout_kind: str) -> str:
    from modules.locale_de import location_request_timeout_hint

    return location_request_timeout_hint(cmd_key or "wx", timeout_kind)


def _watch_pending(node_key: str, deadline: float) -> None:
    while time.time() < deadline:
        time.sleep(1.0)
        with _lock:
            if node_key not in _pending:
                return
        try:
            nid = int(node_key)
        except ValueError:
            nid = node_key
        if try_complete_pending_location(nid):
            return
    with _lock:
        pend = _pending.pop(node_key, None)
    if not pend:
        return
    logger.info(f"LocationRequest: timeout for node {node_key} cmd={pend.get('cmd_key')}")
    _send_text(
        _timeout_message(pend.get("cmd_key") or "", pend.get("timeout_kind") or "weather"),
        int(pend["node_id"]),
        int(pend["device_id"]),
        int(pend["channel"]),
        bool(pend["is_dm"]),
        pend.get("reply_id"),
    )


def try_complete_pending_location(node_id, lat=None, lon=None) -> bool:
    """If pending and a plausible location is now known, run build_response and send."""
    node_key = str(node_id)
    with _lock:
        pend = _pending.get(node_key)
        if not pend:
            return False
        known = None
        if lat is not None and lon is not None:
            try:
                lat_f, lon_f = float(lat), float(lon)
                if (
                    -90.0 <= lat_f <= 90.0
                    and -180.0 <= lon_f <= 180.0
                    and not (int(lat_f) == 0 and int(lon_f) == 0)
                ):
                    known = (lat_f, lon_f, "gps")
            except (TypeError, ValueError):
                known = None
        if not known:
            known = lookup_known_node_location(pend["node_id"], pend["device_id"])
        if not known:
            return False
        _pending.pop(node_key, None)
        lat, lon, source = known
        build = pend.get("build_response")
        label = ""
        device_id = int(pend["device_id"])
        channel = int(pend["channel"])
        is_dm = bool(pend["is_dm"])
        reply_id = pend.get("reply_id")
        nid = int(pend["node_id"])

    if not callable(build):
        return True
    try:
        text = build(lat, lon, source, label)
    except Exception as e:
        logger.error(f"LocationRequest: build_response failed for {node_key}: {e}")
        return True
    _send_text(text, nid, device_id, channel, is_dm, reply_id)
    logger.info(f"LocationRequest: completed pending cmd for node {node_key}")
    return True


def resolve_or_request_location(
    message: str,
    node_id,
    device_id: int = 1,
    *,
    command_tokens=(),
    skip_numeric: bool = False,
    cmd_key: str = "",
    timeout_kind: str = "weather",
    build_response: Optional[BuildResponseFn] = None,
    channel: Optional[int] = None,
    is_dm: Optional[bool] = None,
    reply_id=None,
):
    """Resolve location for a command.

    Returns:
      (lat, lon, source, label) — ready to use
      str — error / hint for the user
      None — deferred (ack sent; result comes async via build_response)
    """
    from modules.locationdata import (
        extract_location_arg,
        geocode_place_name,
        parse_lat_lon_from_text,
        parse_maidenhead_from_text,
    )

    ctx = get_command_context()
    ch = int(channel if channel is not None else ctx.get("channel", 0) or 0)
    dm = bool(is_dm if is_dm is not None else ctx.get("is_dm", True))
    rid = reply_id if reply_id is not None else ctx.get("reply_id")
    nid = int(node_id)
    did = int(device_id)

    query = extract_location_arg(
        message or "",
        command_tokens,
        skip_numeric=skip_numeric,
    )

    if query:
        cancel_pending(nid)
        coords = parse_lat_lon_from_text(query)
        if coords:
            lat, lon = coords
            return lat, lon, "arg-coords", f"{lat:.2f}, {lon:.2f}"
        grid = parse_maidenhead_from_text(query)
        if grid:
            lat, lon, grid_label = grid
            return lat, lon, "arg-grid", grid_label
        if query.replace(" ", "").isdigit():
            query = ""
        else:
            geo = geocode_place_name(query)
            if not geo:
                return f"Ort nicht gefunden: {query}"
            lat, lon, display = geo
            return lat, lon, "arg-place", display

    known = lookup_known_node_location(nid, did)
    if known:
        cancel_pending(nid)
        lat, lon, source = known
        return lat, lon, source, ""

    if not _enabled() or build_response is None:
        from modules.locale_de import location_request_timeout_hint

        return location_request_timeout_hint(cmd_key or "cmd", timeout_kind)

    node_key = str(nid)
    now = time.time()
    with _lock:
        if node_key in _pending:
            return "Standort wird noch angefragt – bitte kurz warten…"

        last = float(_last_request_ts.get(node_key, 0) or 0)
        cd = _cooldown_sec()
        if last and (now - last) < cd:
            from modules.locale_de import location_request_timeout_hint

            return location_request_timeout_hint(cmd_key or "cmd", timeout_kind)

        _pending[node_key] = {
            "node_id": nid,
            "device_id": did,
            "channel": ch,
            "is_dm": dm,
            "reply_id": rid,
            "cmd_key": cmd_key or "",
            "timeout_kind": timeout_kind or "weather",
            "build_response": build_response,
            "started": now,
        }
        _last_request_ts[node_key] = now

    _send_ack(nid, did, ch, dm)
    threading.Thread(
        target=_fire_position_request,
        args=(did, nid, ch),
        name=f"locReq-{node_key}",
        daemon=True,
    ).start()
    deadline = now + _timeout_sec()
    threading.Thread(
        target=_watch_pending,
        args=(node_key, deadline),
        name=f"locWait-{node_key}",
        daemon=True,
    ).start()
    return None
