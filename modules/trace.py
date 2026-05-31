# !trace — Meshtastic traceroute to a node, result sent via DM.

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import google.protobuf.json_format
from meshtastic import mesh_pb2, portnums_pb2

from modules.log import logger
from modules.system import (
    api_throttle,
    decimal_to_hex,
    get_name_from_number,
    send_message,
)

trap_list_trace = ("trace",)

_UNK_SNR = -128
_TRACE_HOP_LIMIT = 7
_TRACE_PENDING: Dict[int, float] = {}
_TRACE_PENDING_TTL = 120.0


def _node_label(node_num, node_int: int) -> str:
    try:
        n = int(node_num)
    except (TypeError, ValueError):
        return str(node_num)
    short = get_name_from_number(n, "short", node_int) or "?"
    return f"{short} {decimal_to_hex(n)}"


def _snr_db(raw) -> str:
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return "?"
    if val == _UNK_SNR:
        return "?"
    return f"{val / 4:.0f}"


def format_traceroute_packet(packet: dict, node_int: int, dest_id: int) -> str:
    """Format a TRACEROUTE_APP response packet for mesh DM."""
    if not packet:
        return "Trace: keine Antwort vom Netz."

    payload = (packet.get("decoded") or {}).get("payload")
    if not payload:
        return "Trace: leere Antwort."

    route_discovery = mesh_pb2.RouteDiscovery()
    route_discovery.ParseFromString(payload)
    as_dict = google.protobuf.json_format.MessageToDict(route_discovery)

    dest_label = _node_label(dest_id, node_int)
    lines = [f"🔍 Trace → {dest_label}"]

    pkt_to = packet.get("to")
    pkt_from = packet.get("from")

    route = as_dict.get("route") or []
    snr_towards = as_dict.get("snrTowards") or []
    len_towards = len(route)
    snr_t_valid = len(snr_towards) == len_towards + 1

    towards = _node_label(pkt_to if pkt_to is not None else dest_id, node_int)
    if route:
        for idx, node_num in enumerate(route):
            snr = _snr_db(snr_towards[idx]) if snr_t_valid else "?"
            towards += f" → {_node_label(node_num, node_int)} ({snr} dB)"
    if pkt_from is not None:
        snr = _snr_db(snr_towards[-1]) if snr_t_valid and snr_towards else "?"
        if snr_t_valid or not route:
            towards += f" → {_node_label(pkt_from, node_int)} ({snr} dB)"
    lines.append(f"Hin:  {towards}")

    route_back = as_dict.get("routeBack") or []
    snr_back = as_dict.get("snrBack") or []
    len_back = len(route_back)
    back_valid = "hopStart" in packet and len(snr_back) == len_back + 1

    if back_valid and pkt_from is not None:
        back = _node_label(pkt_from, node_int)
        if route_back:
            for idx, node_num in enumerate(route_back):
                back += f" → {_node_label(node_num, node_int)} ({_snr_db(snr_back[idx])} dB)"
        back += f" → {_node_label(pkt_to if pkt_to is not None else dest_id, node_int)} ({_snr_db(snr_back[-1])} dB)"
        lines.append(f"Zurück: {back}")

    hop_count = max(len_towards, len_back)
    if hop_count:
        lines.append(f"{hop_count} Hop{'s' if hop_count != 1 else ''}")
    elif not route and not route_back:
        lines.append("Direktverbindung (0 Hops)")

    return "\n".join(lines)


def run_traceroute(dest_id: int, node_int: int, channel: int, hop_limit: int = _TRACE_HOP_LIMIT) -> str:
    """Blocking traceroute on the radio interface (call from a worker thread)."""
    import modules.system as sys

    interface = sys.__dict__.get(f"interface{node_int}")
    if interface is None:
        return f"Trace: Interface {node_int} nicht verbunden."

    dest = decimal_to_hex(dest_id)
    captured: Dict[str, Any] = {}

    def on_response(p: dict):
        captured["packet"] = p
        try:
            interface._acknowledgment.receivedTraceRoute = True
        except Exception:
            pass

    route_msg = mesh_pb2.RouteDiscovery()
    wait_factor = min(len(interface.nodes) - 1 if interface.nodes else 0, hop_limit)

    interface.sendData(
        route_msg,
        destinationId=dest,
        portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
        wantResponse=True,
        onResponse=on_response,
        channelIndex=channel,
        hopLimit=hop_limit,
    )
    interface.waitForTraceRoute(wait_factor)

    return format_traceroute_packet(captured.get("packet"), node_int, dest_id)


def _trace_worker(dest_id: int, requester_id: int, node_int: int, channel: int) -> None:
    try:
        result = run_traceroute(dest_id, node_int, channel)
    except Exception as e:
        logger.debug(f"Trace: failed dest={dest_id} requester={requester_id}: {e}")
        err = str(e).strip()
        if "Timed out" in err or "timeout" in err.lower():
            result = f"Trace zu {_node_label(dest_id, node_int)}: Zeitüberschreitung (keine Antwort)."
        else:
            result = f"Trace fehlgeschlagen: {err[:120]}"
    try:
        send_message(result, channel, requester_id, node_int)
    except Exception as e:
        logger.error(f"Trace: DM send failed: {e}")
    finally:
        _TRACE_PENDING.pop(requester_id, None)


def start_traceroute_to_requester(
    dest_id: int,
    requester_id: int,
    node_int: int,
    channel: int,
) -> str:
    """Queue a traceroute; result is sent via DM. Returns immediate ack text."""
    now = time.time()
    if requester_id in _TRACE_PENDING and (now - _TRACE_PENDING[requester_id]) < _TRACE_PENDING_TTL:
        return "⏳ Trace läuft bereits — bitte warten, Ergebnis kommt per DM."

    throttled = api_throttle(requester_id, node_int, channel, apiName="trace")
    if throttled:
        return throttled if isinstance(throttled, str) else "⏱️ Bitte etwas langsamer mit !trace."

    _TRACE_PENDING[requester_id] = now
    dest_label = _node_label(dest_id, node_int)
    threading.Thread(
        target=_trace_worker,
        args=(dest_id, requester_id, node_int, channel),
        daemon=True,
    ).start()
    return f"🔍 Trace zu {dest_label} gestartet — Ergebnis per DM."


def trace_help_text() -> str:
    return (
        "🔍 !trace — Traceroute zu dir (Ergebnis per DM).\n"
        "!trace <Kurzname> — z. B. !trace MHH\n"
        "!trace !a1b2c3d4 — Ziel per Hex-ID"
    )
