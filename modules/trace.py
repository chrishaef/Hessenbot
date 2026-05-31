# !trace — Meshtastic traceroute to a node, result sent via DM.

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict

import google.protobuf.json_format
from meshtastic import mesh_pb2, portnums_pb2

from modules.log import logger
from modules.system import (
    api_throttle,
    decimal_to_hex,
    get_name_from_number,
    send_message,
    record_mesh_hops_from_trace,
)

trap_list_trace = ("trace",)

_UNK_SNR = -128
_TRACE_HOP_LIMIT = 7
_TRACE_INTERFACE_COOLDOWN_S = 65.0
_TRACE_RESULT_MIN_GAP_S = 5.0  # min seconds after job start before result DM (after ack)


@dataclass(frozen=True)
class _TraceJob:
    dest_id: int
    requester_id: int
    node_int: int
    channel: int


_STATE_LOCK = threading.Lock()
_TRACE_QUEUE: queue.Queue[_TraceJob] = queue.Queue()
_PENDING_REQUESTERS: set[int] = set()
_TRACE_RUNNING = False
_DISPATCHER_STARTED = False
_INTERFACE_LAST_TRACE_START: Dict[int, float] = {}


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
        record_mesh_hops_from_trace(dest_id, hop_count)
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


def _wait_interface_cooldown(node_int: int) -> None:
    """Block until this interface may trigger the next traceroute (65s minimum interval)."""
    while True:
        with _STATE_LOCK:
            last = _INTERFACE_LAST_TRACE_START.get(node_int, 0.0)
            remaining = _TRACE_INTERFACE_COOLDOWN_S - (time.monotonic() - last)
        if remaining <= 0:
            return
        time.sleep(min(remaining, 1.0))


def _mark_interface_trace_started(node_int: int) -> None:
    with _STATE_LOCK:
        _INTERFACE_LAST_TRACE_START[node_int] = time.monotonic()


def _send_trace_result_dm(job: _TraceJob, result: str) -> None:
    """Send trace result via DM; split Hin/Zurück to avoid RATE_LIMIT on back-to-back DMs."""
    import modules.settings as st

    split_delay = max(float(getattr(st, "splitDelay", 0) or 0), 2.0)
    back_idx = result.find("\nZurück:")
    if back_idx > 0:
        part1 = result[:back_idx].strip()
        part2 = result[back_idx + 1 :].strip()
        send_message(part1, job.channel, job.requester_id, job.node_int)
        time.sleep(split_delay)
        send_message(part2, job.channel, job.requester_id, job.node_int)
    else:
        send_message(result, job.channel, job.requester_id, job.node_int)


def _run_trace_job(job: _TraceJob) -> None:
    import modules.settings as st

    job_started = time.monotonic()
    try:
        result = run_traceroute(job.dest_id, job.node_int, job.channel)
    except Exception as e:
        logger.debug(f"Trace: failed dest={job.dest_id} requester={job.requester_id}: {e}")
        err = str(e).strip()
        if "Timed out" in err or "timeout" in err.lower():
            result = f"Trace zu {_node_label(job.dest_id, job.node_int)}: Zeitüberschreitung (keine Antwort)."
        else:
            result = f"Trace fehlgeschlagen: {err[:120]}"
    min_gap = max(
        _TRACE_RESULT_MIN_GAP_S,
        float(getattr(st, "responseDelay", 0.7) or 0) + 3.0,
    )
    elapsed = time.monotonic() - job_started
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)
    try:
        _send_trace_result_dm(job, result)
    except Exception as e:
        logger.error(f"Trace: DM send failed: {e}")


def _trace_dispatcher_loop() -> None:
    global _TRACE_RUNNING
    while True:
        job = _TRACE_QUEUE.get()
        try:
            _wait_interface_cooldown(job.node_int)
            with _STATE_LOCK:
                _TRACE_RUNNING = True
            _mark_interface_trace_started(job.node_int)
            _run_trace_job(job)
        finally:
            with _STATE_LOCK:
                _TRACE_RUNNING = False
                _PENDING_REQUESTERS.discard(job.requester_id)
            _TRACE_QUEUE.task_done()


def _ensure_trace_dispatcher() -> None:
    global _DISPATCHER_STARTED
    with _STATE_LOCK:
        if _DISPATCHER_STARTED:
            return
        _DISPATCHER_STARTED = True
        threading.Thread(
            target=_trace_dispatcher_loop,
            daemon=True,
            name="trace-dispatcher",
        ).start()


def start_traceroute_to_requester(
    dest_id: int,
    requester_id: int,
    node_int: int,
    channel: int,
) -> str:
    """Queue a traceroute; result is sent via DM. Returns immediate ack text."""
    throttled = api_throttle(requester_id, node_int, channel, apiName="trace")
    if throttled:
        return throttled if isinstance(throttled, str) else "⏱️ Bitte etwas langsamer mit !trace."

    dest_label = _node_label(dest_id, node_int)
    job = _TraceJob(dest_id, requester_id, node_int, channel)

    with _STATE_LOCK:
        if requester_id in _PENDING_REQUESTERS:
            return "⏳ Dein Trace steht bereits in der Warteschlange — bitte warten."
        busy = _TRACE_RUNNING or not _TRACE_QUEUE.empty()
        _PENDING_REQUESTERS.add(requester_id)

    _TRACE_QUEUE.put(job)
    _ensure_trace_dispatcher()

    if busy:
        return (
            f"⏳ Trace zu {dest_label} in Warteschlange — "
            "bitte ~65s nach Abschluss der laufenden Trace warten."
        )
    return f"🔍 Trace zu {dest_label} gestartet — Bitte ~30s warten."


def trace_help_text() -> str:
    return (
        "🔍 !trace — Traceroute zu dir (Ergebnis per DM).\n"
        "!trace MHH — Traceroute zu Kurzname MHH\n"
        "!trace !604f8594 — Traceroute per Hex-Node-ID"
    )
