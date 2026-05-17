# Unwrap meshtasticd --sim / MQTT SIMULATOR_APP (Compressed) envelopes for bot handlers.
# SimRadio wraps real mesh payloads: inner portnum + raw protobuf bytes (not "fake" nodes).

from __future__ import annotations

import base64
from typing import Any, Dict, Optional, Tuple

from google.protobuf import json_format
from google.protobuf.message import DecodeError

from modules.log import logger

try:
    from meshtastic import protocols as MESHTASTIC_PROTOCOLS
    from meshtastic.protobuf import portnums_pb2
except ImportError:  # pragma: no cover
    MESHTASTIC_PROTOCOLS = {}
    portnums_pb2 = None


def _coerce_payload_bytes(value: Any) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except Exception:
            return value.encode("utf-8", errors="surrogateescape")
    return None


def _portnum_to_int(portnum: Any) -> Optional[int]:
    if portnum is None or portnums_pb2 is None:
        return None
    if isinstance(portnum, int):
        return portnum
    if isinstance(portnum, str):
        name = portnum.strip()
        if name.isdigit():
            return int(name)
        if not name.endswith("_APP") and name in ("TEXT_MESSAGE",):
            name = f"{name}_APP"
        try:
            return int(portnums_pb2.PortNum.Value(name))
        except ValueError:
            return None
    return None


def _portnum_to_name(portnum: Any) -> str:
    pn = _portnum_to_int(portnum)
    if pn is None:
        return str(portnum or "")
    return portnums_pb2.PortNum.Name(pn)


def _apply_inner_decoded(
    decoded: Dict[str, Any], port_int: int, raw: bytes
) -> bool:
    handler = MESHTASTIC_PROTOCOLS.get(port_int)
    port_name = portnums_pb2.PortNum.Name(port_int)
    decoded["portnum"] = port_name
    decoded["payload"] = raw

    if port_int == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
        try:
            decoded["text"] = raw.decode("utf-8")
        except Exception:
            decoded["text"] = raw.decode("utf-8", errors="replace")
        return True

    if handler is None or handler.protobufFactory is None:
        return port_int in (
            portnums_pb2.PortNum.TEXT_MESSAGE_COMPRESSED_APP,
        )

    try:
        pb = handler.protobufFactory()
        pb.ParseFromString(raw)
    except DecodeError:
        return False

    inner = json_format.MessageToDict(pb, preserving_proto_field_name=True)
    if handler.name:
        decoded[handler.name] = inner
    return True


def unwrap_sim_tunnel_packet(packet: Dict[str, Any]) -> Tuple[bool, str]:
    """
    If packet is a SIMULATOR_APP (Compressed) tunnel from meshtasticd sim/MQTT, replace
    decoded with the inner port + payload (in-place).

    Returns (success, inner_port_name_or_reason).
    """
    decoded = packet.get("decoded")
    if not isinstance(decoded, dict):
        return False, ""
    if decoded.get("portnum") != "SIMULATOR_APP":
        return False, ""

    sim = decoded.get("simulator")
    if not isinstance(sim, dict):
        return False, "SIMULATOR_APP without simulator body"

    inner_port_raw = sim.get("portnum", sim.get("portNum"))
    raw = _coerce_payload_bytes(sim.get("data", sim.get("payload")))
    if raw is None or not raw:
        return False, "empty tunnel payload"

    port_int = _portnum_to_int(inner_port_raw)
    if port_int is None:
        return False, f"unknown inner port {inner_port_raw!r}"

    inner_name = _portnum_to_name(port_int)
    if not _apply_inner_decoded(decoded, port_int, raw):
        logger.debug(
            "System: Sim/MQTT tunnel unwrap failed inner=%s len=%s",
            inner_name,
            len(raw),
        )
        return False, inner_name

    decoded["simTunnel"] = True
    decoded.pop("simulator", None)
    return True, inner_name
