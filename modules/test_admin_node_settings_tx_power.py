#!/usr/bin/env python3
# Admin Node Settings: lora.tx_power (no hard cap, confirmation above the EU-safe level).
# Run: python -m pytest modules/test_admin_node_settings_tx_power.py -q

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from modules import admin_web_ops as ops


@pytest.mark.parametrize(
    "current,raw,confirmed,expected",
    [
        (14, "", False, (None, None)),
        (14, None, False, (None, None)),
        (14, "14", False, (None, None)),
        (22, "22", False, (None, None)),
        (14, "10", False, (10, None)),
        (14, "14", True, (None, None)),
        (14, "22", True, (22, None)),
        (14, "30", True, (30, None)),
        (14, "max", True, (30, None)),
        (14, "0", False, (0, None)),
        (30, "14", False, (14, None)),
        (30, "20", True, (20, None)),
    ],
)
def test_plan_tx_power_change_accepts_valid_values(current, raw, confirmed, expected):
    assert ops.plan_tx_power_change(current, raw, confirmed) == expected


@pytest.mark.parametrize("current,raw", [(14, "15"), (14, "22"), (14, "30"), (14, "max"), (30, "20")])
def test_plan_tx_power_change_requires_confirmation_above_eu_safe(current, raw):
    value, err = ops.plan_tx_power_change(current, raw, False)
    assert value is None
    assert err and "bestätigen" in err and "EU-868" in err


@pytest.mark.parametrize("raw", ["-1", "31", "abc", "14.5"])
def test_plan_tx_power_change_rejects_invalid(raw):
    value, err = ops.plan_tx_power_change(14, raw, True)
    assert value is None and err


class _FakeNode:
    def __init__(self, tx_power: int) -> None:
        self.localConfig = SimpleNamespace(
            device=SimpleNamespace(role=0, rebroadcast_mode=0, node_info_broadcast_secs=900),
            position=SimpleNamespace(
                position_broadcast_secs=900,
                position_broadcast_smart_enabled=False,
                gps_enabled=False,
                fixed_position=True,
            ),
            lora=SimpleNamespace(tx_power=tx_power, tx_enabled=True),
        )
        self.written: List[str] = []

    def writeConfig(self, name: str) -> None:
        self.written.append(name)

    def setOwner(self, **_kw: Any) -> None:
        raise AssertionError("owner unchanged")

    def setFixedPosition(self, *_a: Any) -> None:
        raise AssertionError("position unchanged")


def _settings(tx_power: int) -> Dict[str, Any]:
    return {
        "short_name": "HB",
        "long_name": "Hessenbot",
        "role": 0,
        "rebroadcast_mode": 0,
        "node_info_broadcast_secs": 900,
        "position_broadcast_secs": 900,
        "fixed_position": True,
        "latitude": 50.1,
        "longitude": 8.6,
        "altitude_m": None,
        "lora_tx_power": tx_power,
    }


def _form(**extra: str) -> Dict[str, str]:
    base = {
        "short_name": "HB",
        "long_name": "Hessenbot",
        "role": "0",
        "rebroadcast_mode": "0",
        "node_info_broadcast_secs": "900",
        "position_broadcast_secs": "900",
        "latitude": "50.1",
        "longitude": "8.6",
        "altitude_m": "",
    }
    base.update(extra)
    return base


def _apply(monkeypatch, node: _FakeNode, form: Dict[str, str]):
    monkeypatch.setattr(ops, "_local_node_for_iface", lambda _i: (node, None))
    monkeypatch.setattr(
        ops, "fetch_local_node_settings", lambda _i: (None, _settings(node.localConfig.lora.tx_power))
    )
    return ops.apply_local_node_settings(1, form)


def test_apply_high_tx_power_needs_confirmation_and_writes_nothing(monkeypatch):
    node = _FakeNode(14)
    ok, msg = _apply(monkeypatch, node, _form(tx_power="30"))
    assert not ok and "bestätigen" in msg
    assert node.localConfig.lora.tx_power == 14 and node.written == []


def test_apply_high_tx_power_with_confirmation_is_not_clamped(monkeypatch):
    node = _FakeNode(14)
    ok, msg = _apply(monkeypatch, node, _form(tx_power="30", tx_power_confirm="1"))
    assert ok, msg
    assert node.localConfig.lora.tx_power == 30
    assert node.written == ["lora"]
    assert "30 dBm" in msg


def test_apply_lowering_tx_power_needs_no_confirmation(monkeypatch):
    node = _FakeNode(27)
    ok, msg = _apply(monkeypatch, node, _form(tx_power="14"))
    assert ok, msg
    assert node.localConfig.lora.tx_power == 14 and node.written == ["lora"]


def test_apply_without_tx_power_field_leaves_lora_untouched(monkeypatch):
    node = _FakeNode(27)
    ok, msg = _apply(monkeypatch, node, _form())
    assert ok and msg == "Keine Änderungen."
    assert node.written == []


def test_node_settings_form_shows_tx_power_field_and_warning():
    settings = {
        **_settings(22),
        "iface_type": "tcp",
        "node_num": 1,
        "node_id_hex": "!00000001",
        "config_latitude": 50.1,
        "config_longitude": 8.6,
        "lora_region": "EU_868",
        "lora_modem_preset": "SHORT_SLOW",
        "lora_channel_num": 0,
        "lora_tx_enabled": True,
    }
    out = ops.build_node_settings_html(settings, iface_id=1, ifaces=[1], form_action="/node-settings")
    assert 'name="tx_power"' in out and 'value="22"' in out and 'max="30"' in out
    assert 'name="tx_power_confirm"' in out
    assert "EU-868" in out and "RAK13302" in out
