#!/usr/bin/env python3
"""Configure the local meshtasticd node through the Meshtastic Python API (TCP, localhost:4403).

Runs inside the Hessenbot venv (meshtastic is in requirements.txt). Channel PSKs are read from a
spec file (0600) - never from argv - and are never printed in clear text.

Subcommands:
    info                       print node id / owner (one `key=value` per line)
    channels                   print current channels (PSK as short fingerprint)
    inspect SPEC               like `channels`, exit 10 if SPEC would overwrite a different, in-use channel
    verify SPEC                after `apply`: channels and LoRa values must match SPEC;
                               exit 11 on any mismatch, exit 12 if TX is enabled although SPEC disables it
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
import os
import sys
import time
from typing import Any, Optional

EXIT_CONFLICT = 10
EXIT_MISMATCH = 11
EXIT_TX_UNSAFE = 12
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
        if "only_if_name" in ch and not isinstance(ch["only_if_name"], str):
            raise ValueError("only_if_name must be a string")
    lora = spec.get("lora", {})
    if "tx_power" in lora and not 0 <= int(lora["tx_power"]) <= 30:
        raise ValueError("tx_power must be 0..30 dBm")


def _disable_applies(have: Optional[dict[str, Any]], want: dict[str, Any]) -> bool:
    """A DISABLED entry with only_if_name only touches a channel that still carries that name."""
    if not have or have["role"] == "DISABLED":
        return False
    only = want.get("only_if_name")
    return only is None or have["name"] == only


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


def channel_mismatches(current: list[dict[str, Any]], spec: dict[str, Any]) -> list[str]:
    """Wanted channels that are absent or differ on the node (strict, for post-apply verification)."""
    by_idx = {c["index"]: c for c in current}
    out: list[str] = []
    for want in spec.get("channels", []):
        idx = int(want["index"])
        have = by_idx.get(idx)
        if want["role"] == "DISABLED":
            if _disable_applies(have, want):
                out.append(f"channel #{idx}: still active, expected DISABLED")
            continue
        if not have or have["role"] == "DISABLED":
            out.append(f"channel #{idx}: missing, expected {want['role']} '{want.get('name', '')}'")
            continue
        want_psk = psk_fingerprint(decode_psk(want.get("psk", "default")))
        if have["role"] != want["role"]:
            out.append(f"channel #{idx}: role {have['role']} != {want['role']}")
        if want.get("name", "") and have["name"] != want["name"]:
            out.append(f"channel #{idx}: name '{have['name']}' != '{want['name']}'")
        if have["psk_fp"] != want_psk:
            out.append(f"channel #{idx}: PSK fingerprint {have['psk_fp']} != {want_psk}")
    return out


def lora_mismatches(current: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """LoRa values from SPEC that the node does not report (current: region, modem_preset, tx_power, tx_enabled)."""
    want = spec.get("lora") or {}
    out: list[str] = []
    for key in ("region", "modem_preset"):
        if key in want and current.get(key) != want[key]:
            out.append(f"lora.{key}: {current.get(key)} != {want[key]}")
    if "tx_power" in want and int(current.get("tx_power", -1)) != int(want["tx_power"]):
        out.append(f"lora.tx_power: {current.get('tx_power')} != {want['tx_power']}")
    if "tx_enabled" in want and bool(current.get("tx_enabled")) != bool(want["tx_enabled"]):
        out.append(f"lora.tx_enabled: {str(bool(current.get('tx_enabled'))).lower()} != {str(bool(want['tx_enabled'])).lower()}")
    return out


def tx_unsafe(current: dict[str, Any], spec: dict[str, Any]) -> bool:
    """True when the node transmits although SPEC wants TX off (antenna not confirmed)."""
    want = spec.get("lora") or {}
    return "tx_enabled" in want and not bool(want["tx_enabled"]) and bool(current.get("tx_enabled"))


def read_lora(iface) -> dict[str, Any]:
    _, config_pb2 = _pb()
    enum = config_pb2.Config.LoRaConfig
    lora = iface.localNode.localConfig.lora
    return {
        "region": enum.RegionCode.Name(lora.region),
        "modem_preset": enum.ModemPreset.Name(lora.modem_preset),
        "tx_power": int(lora.tx_power),
        "tx_enabled": bool(lora.tx_enabled),
    }


def cmd_verify(iface, spec: dict[str, Any]) -> int:
    chans = read_channels(iface)
    print_channels(chans)
    current = read_lora(iface)
    print(
        f"lora region={current['region']} preset={current['modem_preset']} "
        f"tx_power={current['tx_power']} tx_enabled={str(current['tx_enabled']).lower()}"
    )
    problems = channel_mismatches(chans, spec) + lora_mismatches(current, spec)
    for line in problems:
        print(f"ABWEICHUNG {line}")
    if tx_unsafe(current, spec):
        print("TX-GATE VERLETZT: tx_enabled=true obwohl keine Antenne bestaetigt wurde")
        return EXIT_TX_UNSAFE
    return EXIT_MISMATCH if problems else 0


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


def _pace() -> None:
    """Admin packets sent in one burst overflow the node's queue and are dropped silently."""
    time.sleep(float(os.environ.get("HESSENBOT_NODE_PACE", "1.0")))


def apply_spec(iface, spec: dict[str, Any]) -> None:
    channel_pb2, config_pb2 = _pb()
    node = iface.localNode
    begin = getattr(node, "beginSettingsTransaction", None)
    commit = getattr(node, "commitSettingsTransaction", None)
    if begin:
        begin()
        _pace()

    owner = spec.get("owner") or {}
    if owner.get("long"):
        node.setOwner(long_name=owner["long"], short_name=owner.get("short") or None)
        _pace()

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
        _pace()

    for want in spec.get("channels", []):
        idx = int(want["index"])
        ch = node.channels[idx]
        if want["role"] == "DISABLED":
            have = {"role": channel_pb2.Channel.Role.Name(ch.role), "name": ch.settings.name}
            if not _disable_applies(have, want):
                continue
            ch.role = channel_pb2.Channel.Role.Value("DISABLED")
            ch.settings.name = ""
            ch.settings.psk = b""
        else:
            ch.role = channel_pb2.Channel.Role.Value(want["role"])
            ch.settings.name = want.get("name", "")
            ch.settings.psk = decode_psk(want.get("psk", "default"))
        node.writeChannel(idx)
        _pace()

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
    print(f"tx_power={lora.tx_power}")
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
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("spec")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("spec")
    p_apply.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    spec: dict[str, Any] = {}
    if args.cmd in ("inspect", "apply", "verify"):
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        validate_spec(spec)

    iface = _connect(args.host)
    try:
        if args.cmd == "info":
            return cmd_info(iface)
        if args.cmd == "verify":
            return cmd_verify(iface, spec)
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
