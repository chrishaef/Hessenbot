#!/usr/bin/env python3
"""Configure the local meshtasticd node through the Meshtastic Python API (TCP, localhost:4403).

Runs inside the Hessenbot venv (meshtastic is in requirements.txt). Channel PSKs are read from a
spec file (0600) - never from argv - and are never printed in clear text.

Subcommands:
    info                       print node id / owner (one `key=value` per line)
    channels                   print current channels (PSK as short fingerprint)
    inspect SPEC               like `channels`, exit 10 if SPEC would overwrite a different, in-use channel
    apply SPEC [--force]       write owner, LoRa config and channels from SPEC

SPEC (JSON):
    {"owner": {"long": "...", "short": "..."},            # optional
     "lora": {"region": "EU_868", "modem_preset": "SHORT_SLOW", "tx_power": 27, "tx_enabled": false},
     "channels": [{"index": 0, "role": "PRIMARY", "name": "", "psk": "default"},
                  {"index": 1, "role": "SECONDARY", "name": "Mesh Hessen", "psk": "<base64>"}]}
`psk` "default" means the Meshtastic default key (0x01); an empty name on the primary follows the preset.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from typing import Any, Optional

EXIT_CONFLICT = 10
DEFAULT_PSK = b"\x01"
CHANNEL_NAME_MAX = 11


def decode_psk(value: str) -> bytes:
    if value == "default":
        return DEFAULT_PSK
    if value == "none":
        return b""
    raw = base64.b64decode(value, validate=True)
    if len(raw) not in (1, 16, 32):
        raise ValueError("PSK must decode to 1, 16 or 32 bytes")
    return raw


def psk_fingerprint(psk: bytes) -> str:
    if psk in (b"", DEFAULT_PSK):
        return "default" if psk else "none"
    return hashlib.sha256(psk).hexdigest()[:8]


def validate_spec(spec: dict[str, Any]) -> None:
    seen: set[int] = set()
    for ch in spec.get("channels", []):
        idx = int(ch["index"])
        if not 0 <= idx <= 7 or idx in seen:
            raise ValueError(f"invalid or duplicate channel index {idx}")
        seen.add(idx)
        if ch["role"] not in ("PRIMARY", "SECONDARY", "DISABLED"):
            raise ValueError(f"invalid role {ch['role']!r}")
        if len(ch.get("name", "").encode("utf-8")) > CHANNEL_NAME_MAX:
            raise ValueError(f"channel name too long (max {CHANNEL_NAME_MAX}): {ch['name']!r}")
        decode_psk(ch.get("psk", "default"))
    lora = spec.get("lora", {})
    if "tx_power" in lora and not 0 <= int(lora["tx_power"]) <= 30:
        raise ValueError("tx_power must be 0..30 dBm")


def find_conflicts(current: list[dict[str, Any]], spec: dict[str, Any]) -> list[str]:
    """Indices where an in-use channel differs from what SPEC wants to write."""
    by_idx = {c["index"]: c for c in current}
    out: list[str] = []
    for want in spec.get("channels", []):
        idx = int(want["index"])
        have = by_idx.get(idx)
        if not have or have["role"] == "DISABLED":
            continue
        want_psk = psk_fingerprint(decode_psk(want.get("psk", "default")))
        same = (
            have["role"] == want["role"]
            and have["name"] == want.get("name", "")
            and have["psk_fp"] == want_psk
        )
        if not same and want["role"] != "DISABLED":
            out.append(f"#{idx} {have['role']} '{have['name']}' -> {want['role']} '{want.get('name', '')}'")
    return out


def _pb():
    try:
        from meshtastic.protobuf import channel_pb2, config_pb2  # type: ignore
    except ImportError:  # older meshtastic releases
        from meshtastic import channel_pb2, config_pb2  # type: ignore
    return channel_pb2, config_pb2


def _connect(host: str, timeout: int = 60):
    from meshtastic.tcp_interface import TCPInterface  # type: ignore

    deadline = time.time() + timeout
    last: Optional[Exception] = None
    while time.time() < deadline:
        try:
            return TCPInterface(hostname=host)
        except Exception as exc:  # noqa: BLE001 - connection races while meshtasticd restarts
            last = exc
            time.sleep(2)
    raise RuntimeError(f"could not connect to meshtasticd on {host}: {last}")


def read_channels(iface) -> list[dict[str, Any]]:
    channel_pb2, _ = _pb()
    out = []
    for ch in iface.localNode.channels or []:
        role = channel_pb2.Channel.Role.Name(ch.role)
        out.append(
            {
                "index": ch.index,
                "role": role,
                "name": ch.settings.name,
                "psk_fp": psk_fingerprint(bytes(ch.settings.psk)) if role != "DISABLED" else "-",
            }
        )
    return out


def print_channels(chans: list[dict[str, Any]]) -> None:
    for c in chans:
        if c["role"] == "DISABLED":
            continue
        name = c["name"] or "(folgt Preset)"
        print(f"#{c['index']} {c['role']:<9} name={name} psk={c['psk_fp']}")


def apply_spec(iface, spec: dict[str, Any]) -> None:
    channel_pb2, config_pb2 = _pb()
    node = iface.localNode
    begin = getattr(node, "beginSettingsTransaction", None)
    commit = getattr(node, "commitSettingsTransaction", None)
    if begin:
        begin()

    owner = spec.get("owner") or {}
    if owner.get("long"):
        node.setOwner(long_name=owner["long"], short_name=owner.get("short") or None)

    lora_spec = spec.get("lora") or {}
    if lora_spec:
        lora = node.localConfig.lora
        enum = config_pb2.Config.LoRaConfig
        if "region" in lora_spec:
            lora.region = enum.RegionCode.Value(lora_spec["region"])
        if "modem_preset" in lora_spec:
            lora.use_preset = True
            lora.modem_preset = enum.ModemPreset.Value(lora_spec["modem_preset"])
        if "tx_power" in lora_spec:
            lora.tx_power = int(lora_spec["tx_power"])
        if "tx_enabled" in lora_spec:
            lora.tx_enabled = bool(lora_spec["tx_enabled"])
        node.writeConfig("lora")

    for want in spec.get("channels", []):
        idx = int(want["index"])
        ch = node.channels[idx]
        ch.role = channel_pb2.Channel.Role.Value(want["role"])
        ch.settings.name = want.get("name", "")
        ch.settings.psk = decode_psk(want.get("psk", "default"))
        node.writeChannel(idx)

    if commit:
        commit()


def cmd_info(iface) -> int:
    info = iface.getMyNodeInfo() or {}
    user = info.get("user", {})
    print(f"node_id={user.get('id', '')}")
    print(f"long_name={user.get('longName', '')}")
    print(f"short_name={user.get('shortName', '')}")
    lora = iface.localNode.localConfig.lora
    _, config_pb2 = _pb()
    enum = config_pb2.Config.LoRaConfig
    print(f"region={enum.RegionCode.Name(lora.region)}")
    print(f"modem_preset={enum.ModemPreset.Name(lora.modem_preset)}")
    print(f"tx_enabled={str(lora.tx_enabled).lower()}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    sub.add_parser("channels")
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("spec")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("spec")
    p_apply.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    spec: dict[str, Any] = {}
    if args.cmd in ("inspect", "apply"):
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        validate_spec(spec)

    iface = _connect(args.host)
    try:
        if args.cmd == "info":
            return cmd_info(iface)
        chans = read_channels(iface)
        if args.cmd == "channels":
            print_channels(chans)
            return 0
        conflicts = find_conflicts(chans, spec)
        if args.cmd == "inspect":
            print_channels(chans)
            for line in conflicts:
                print(f"KONFLIKT {line}")
            return EXIT_CONFLICT if conflicts else 0
        if conflicts and not args.force:
            print("refusing to overwrite existing channels without --force:", file=sys.stderr)
            for line in conflicts:
                print(f"  {line}", file=sys.stderr)
            return EXIT_CONFLICT
        apply_spec(iface, spec)
        print("applied")
        return 0
    finally:
        try:
            iface.close()
        except Exception:  # noqa: BLE001 - node may have rebooted after a config write
            pass


if __name__ == "__main__":
    sys.exit(main())
