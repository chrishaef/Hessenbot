#!/usr/bin/env python3
# Node Settings sub-tabs (Companion parity): validation, confirm gates and Admin-API writes.
# Run: python -m pytest modules/test_admin_node_config.py -q

from __future__ import annotations

import base64
import unittest
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from meshtastic.protobuf import admin_pb2, config_pb2, localonly_pb2
from werkzeug.datastructures import MultiDict

from modules import admin_node_config as anc


class _FormSerializer(HTMLParser):
    """Collect what a browser would submit for each <form> (unchanged values)."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: List[List[Tuple[str, str]]] = []
        self._cur: Optional[List[Tuple[str, str]]] = None
        self._select: Optional[str] = None
        self._select_value: Optional[str] = None
        self._textarea: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs_list: List[Tuple[str, Optional[str]]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if tag == "form":
            self._cur = []
        elif self._cur is None:
            return
        elif tag in ("input", "select", "textarea") and "disabled" in attrs:
            return
        elif tag == "input" and "name" in attrs and "readonly" not in attrs:
            kind = attrs.get("type", "text")
            if kind == "checkbox":
                if "checked" in attrs:
                    self._cur.append((attrs["name"], attrs.get("value", "on")))
            else:
                self._cur.append((attrs["name"], attrs.get("value", "")))
        elif tag == "select":
            self._select, self._select_value = attrs.get("name"), None
        elif tag == "option" and self._select is not None:
            if "selected" in attrs or self._select_value is None:
                self._select_value = attrs.get("value", "")
        elif tag == "textarea":
            self._textarea, self._text = attrs.get("name"), []

    def handle_endtag(self, tag: str) -> None:
        if self._cur is None:
            return
        if tag == "select" and self._select is not None:
            self._cur.append((self._select, self._select_value or ""))
            self._select = None
        elif tag == "textarea" and self._textarea is not None:
            self._cur.append((self._textarea, "".join(self._text)))
            self._textarea = None
        elif tag == "form":
            self.forms.append(self._cur)
            self._cur = None

    def handle_data(self, data: str) -> None:
        if self._textarea is not None:
            self._text.append(data)


def forms_of(html_text: str) -> List[MultiDict]:
    p = _FormSerializer()
    p.feed(html_text)
    return [MultiDict(f) for f in p.forms]


def with_values(form: MultiDict, **values: Any) -> MultiDict:
    out = MultiDict(form)
    for key, val in values.items():
        out.setlist(key, val if isinstance(val, list) else [str(val)])
    return out


class FakeIface:
    def __init__(self) -> None:
        self.metadata = None
        self.user: Dict[str, Any] = {"longName": "Hessenbot", "shortName": "HB", "id": "!00000001"}
        self.nodesByNum: Dict[int, Dict[str, Any]] = {1: {"num": 1, "user": self.user}}

    def getMyNodeInfo(self) -> Dict[str, Any]:
        return self.nodesByNum[1]


class FakeNode:
    def __init__(self) -> None:
        self.localConfig = localonly_pb2.LocalConfig()
        self.moduleConfig = localonly_pb2.LocalModuleConfig()
        self.iface = FakeIface()
        self.sent: List[admin_pb2.AdminMessage] = []
        self.responder = None
        self.answer_config_requests = True
        # Simulated device state that differs from the bot cache: {(kind, section): message}
        self.device_override: Dict[Tuple[str, str], Any] = {}
        self.localConfig.lora.region = config_pb2.Config.LoRaConfig.RegionCode.Value("EU_868")
        self.localConfig.lora.use_preset = True
        self.localConfig.lora.tx_enabled = True
        self.localConfig.lora.tx_power = 14
        self.localConfig.lora.hop_limit = 3

    def ensureSessionKey(self) -> None:
        pass

    def _sendAdmin(self, p, wantResponse=True, onResponse=None, adminIndex=0):
        variant = p.WhichOneof("payload_variant")
        if variant in ("get_config_request", "get_module_config_request"):
            if onResponse is not None and self.answer_config_requests:
                onResponse(self._config_response(variant, getattr(p, variant)))
            return
        self.sent.append(p)
        if onResponse is not None and self.responder is not None:
            onResponse(self.responder(p))

    def _config_response(self, variant: str, num: int) -> Dict[str, Any]:
        kind = "config" if variant == "get_config_request" else "module"
        section = next(s for s in anc._section_names(kind) if anc.section_request_enum(kind, s) == num)
        raw = admin_pb2.AdminMessage()
        target = raw.get_config_response if kind == "config" else raw.get_module_config_response
        source = self.device_override.get((kind, section))
        if source is None:
            source = getattr(self.localConfig if kind == "config" else self.moduleConfig, section)
        getattr(target, section).CopyFrom(source)
        return {"decoded": {"admin": {"raw": raw}}}


class NodeConfigTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.node = FakeNode()
        patcher = mock.patch.object(anc, "_node_for_iface", lambda iface_id: (self.node, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def section_form(self, tab: str) -> MultiDict:
        spec = anc.tab_by_key(tab)
        html_text = anc.build_config_tab_html(spec, self.node, iface_id=1, read_strings=False)
        return forms_of(html_text)[0]


class TabLayoutTests(unittest.TestCase):
    def test_companion_sections_present(self) -> None:
        keys = [t.key for t in anc.available_tabs()]
        for key in ("overview", "user", "channels", "device", "position", "power", "network", "display",
                    "lora", "bluetooth", "security", "mqtt", "serial", "external_notification",
                    "store_forward", "range_test", "telemetry", "canned_message", "audio", "remote_hardware",
                    "neighbor_info", "ambient_lighting", "detection_sensor", "paxcounter", "admin"):
            self.assertIn(key, keys)
        self.assertEqual(keys[-1], "admin")

    def test_every_protobuf_section_has_a_tab(self) -> None:
        keys = {(t.kind, t.section) for t in anc.available_tabs()}
        for name in anc._section_names("config"):
            self.assertIn(("config", name), keys)
        for name in anc._section_names("module"):
            self.assertIn(("module", name), keys)

    def test_every_field_has_german_metadata(self) -> None:
        missing = []
        for spec in anc.available_tabs():
            if spec.kind not in ("config", "module"):
                continue
            desc = (localonly_pb2.LocalConfig if spec.kind == "config" else localonly_pb2.LocalModuleConfig)
            sub = desc.DESCRIPTOR.fields_by_name[spec.section].message_type
            for ref in anc.iter_section_fields(sub):
                if f"{spec.section}.{ref.path}" not in anc.FIELD_META:
                    missing.append(f"{spec.section}.{ref.path}")
                self.assertTrue(anc.field_meta(spec.section, ref.path).label)
        if missing:
            # Newer meshtastic protobufs than FIELD_META: UI falls back to the field name; add labels.
            self.skipTest(f"Ohne deutsches Label: {', '.join(missing)}")

    def test_unknown_tab_falls_back_to_overview(self) -> None:
        self.assertEqual(anc.tab_by_key("does-not-exist").key, "overview")
        self.assertEqual(anc.tab_by_key(None).key, "overview")


class RoundTripTests(NodeConfigTestBase):
    def test_unchanged_submit_is_noop_for_every_section(self) -> None:
        self.node.localConfig.network.ipv4_config.ip = anc.ip_to_int("192.168.1.10")
        self.node.localConfig.security.admin_key.append(b"\x01" * 32)
        self.node.localConfig.lora.ignore_incoming.extend([0x1234ABCD])
        self.node.localConfig.position.position_flags = 1 | 2 | 128
        self.node.localConfig.lora.frequency_offset = 1.5
        self.node.localConfig.network.wifi_psk = "geheim"
        for spec in anc.available_tabs():
            if spec.kind not in ("config", "module"):
                continue
            with self.subTest(section=spec.section):
                form = self.section_form(spec.key)
                ok, msg = anc.apply_section(1, spec.key, form)
                self.assertTrue(ok, msg)
                self.assertIn("keine Änderungen", msg)
        self.assertEqual(self.node.sent, [])

    def test_secret_not_rendered(self) -> None:
        self.node.localConfig.network.wifi_psk = "supersecret"
        self.node.localConfig.security.private_key = b"\x07" * 32
        for tab in ("network", "security"):
            html_text = anc.build_config_tab_html(anc.tab_by_key(tab), self.node, iface_id=1, read_strings=False)
            self.assertNotIn("supersecret", html_text)
            self.assertNotIn(base64.b64encode(b"\x07" * 32).decode(), html_text)

    def test_values_are_html_escaped(self) -> None:
        self.node.localConfig.network.wifi_ssid = '"><script>x</script>'
        html_text = anc.build_config_tab_html(anc.tab_by_key("network"), self.node, iface_id=1, read_strings=False)
        self.assertNotIn("<script>x</script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)


class LoraValidationTests(NodeConfigTestBase):
    def test_tx_power_above_eu_safe_requires_confirm(self) -> None:
        form = with_values(self.section_form("lora"), **{"f__tx_power": 22})
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertIn("Warnung bestätigen", msg)
        self.assertEqual(self.node.sent, [])
        self.assertEqual(self.node.localConfig.lora.tx_power, 14)

    def test_tx_power_confirmed_is_written_unclamped(self) -> None:
        form = with_values(self.section_form("lora"), **{"f__tx_power": 30, "confirm__tx_power": "1"})
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertTrue(ok, msg)
        self.assertEqual(len(self.node.sent), 1)
        self.assertEqual(self.node.sent[0].set_config.lora.tx_power, 30)
        self.assertEqual(self.node.localConfig.lora.tx_power, 30)

    def test_tx_power_out_of_range_rejected_not_clamped(self) -> None:
        form = with_values(self.section_form("lora"), **{"f__tx_power": 31, "confirm__tx_power": "1"})
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertIn("0 und 30", msg)
        self.assertEqual(self.node.sent, [])

    def test_tx_power_zero_means_region_max_and_needs_confirm(self) -> None:
        form = with_values(self.section_form("lora"), f__tx_power=0)
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertIn("27 dBm", msg)
        self.assertEqual(self.node.sent, [])
        ok, msg = anc.apply_section(1, "lora", with_values(form, confirm__tx_power="1"))
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_config.lora.tx_power, 0)

    def test_overview_and_lora_tab_share_tx_power_rules(self) -> None:
        from modules import admin_web_ops as ops

        self.assertIs(ops.plan_tx_power_change, anc.plan_tx_power_change)
        self.assertIs(ops.TX_POWER_WARNING_TEXT, anc.TX_POWER_WARNING_TEXT)
        self.assertIs(anc.FIELD_META["lora.tx_power"].danger_when, anc.tx_power_needs_confirm)
        for old, new in ((14, 0), (14, 15), (14, 30), (0, 14), (30, 14), (14, 14), (0, 0)):
            needs = anc.tx_power_needs_confirm(old, new)
            self.assertEqual(needs, anc.plan_tx_power_change(old, str(new), False)[1] is not None, (old, new))

    def test_tx_power_low_value_needs_no_confirm(self) -> None:
        form = with_values(self.section_form("lora"), **{"f__tx_power": 10})
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_config.lora.tx_power, 10)

    def test_region_change_requires_confirm(self) -> None:
        us = config_pb2.Config.LoRaConfig.RegionCode.Value("US")
        form = with_values(self.section_form("lora"), **{"f__region": us})
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertIn("Region", msg)
        ok, msg = anc.apply_section(1, "lora", with_values(form, confirm__region="1"))
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_config.lora.region, us)

    def test_tx_disable_requires_confirm(self) -> None:
        form = self.section_form("lora")
        form.poplist("f__tx_enabled")
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertIn("TX", msg)

    def test_hop_limit_range(self) -> None:
        ok, msg = anc.apply_section(1, "lora", with_values(self.section_form("lora"), f__hop_limit=8))
        self.assertFalse(ok)
        self.assertIn("0 und 7", msg)

    def test_one_error_blocks_whole_section(self) -> None:
        form = with_values(self.section_form("lora"), f__hop_limit=5, f__tx_power="abc")
        ok, _ = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertEqual(self.node.sent, [])
        self.assertEqual(self.node.localConfig.lora.hop_limit, 3)

    def test_custom_modem_requires_valid_params(self) -> None:
        form = self.section_form("lora")
        form.poplist("f__use_preset")
        ok, msg = anc.apply_section(1, "lora", with_values(form, confirm__use_preset="1"))
        self.assertFalse(ok)
        self.assertIn("Spreading Factor", msg)

    def test_ignore_incoming_list(self) -> None:
        form = with_values(self.section_form("lora"), f__ignore_incoming="!0000abcd, 42")
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertTrue(ok, msg)
        self.assertEqual(list(self.node.sent[0].set_config.lora.ignore_incoming), [0xABCD, 42])
        too_many = with_values(self.section_form("lora"), f__ignore_incoming="1,2,3,4")
        ok, msg = anc.apply_section(1, "lora", too_many)
        self.assertFalse(ok)
        self.assertIn("höchstens 3", msg)

    def test_fields_not_submitted_are_untouched(self) -> None:
        self.node.localConfig.lora.sx126x_rx_boosted_gain = True
        form = MultiDict([("present", "hop_limit"), ("f__hop_limit", "4")])
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertTrue(ok, msg)
        sent = self.node.sent[0].set_config.lora
        self.assertEqual(sent.hop_limit, 4)
        self.assertTrue(sent.sx126x_rx_boosted_gain)
        self.assertEqual(sent.tx_power, 14)


class OtherSectionTests(NodeConfigTestBase):
    def test_static_ip_little_endian(self) -> None:
        self.assertEqual(anc.int_to_ip(anc.ip_to_int("10.0.0.1")), "10.0.0.1")
        self.assertEqual(anc.ip_to_int("1.0.0.0"), 1)
        form = with_values(self.section_form("network"), **{"f__ipv4_config.gateway": "192.168.0.1"})
        ok, msg = anc.apply_section(1, "network", form)
        self.assertTrue(ok, msg)
        self.assertEqual(anc.int_to_ip(self.node.sent[0].set_config.network.ipv4_config.gateway), "192.168.0.1")
        bad = with_values(self.section_form("network"), **{"f__ipv4_config.dns": "300.1.1.1"})
        self.assertFalse(anc.apply_section(1, "network", bad)[0])

    def test_secret_empty_keeps_and_clear_empties(self) -> None:
        self.node.localConfig.network.wifi_psk = "alt"
        ok, _ = anc.apply_section(1, "network", with_values(self.section_form("network"), f__wifi_ssid="Netz"))
        self.assertTrue(ok)
        self.assertEqual(self.node.sent[-1].set_config.network.wifi_psk, "alt")
        ok, _ = anc.apply_section(1, "network", with_values(self.section_form("network"), clear__wifi_psk="1"))
        self.assertTrue(ok)
        self.assertEqual(self.node.sent[-1].set_config.network.wifi_psk, "")

    def test_wifi_disable_needs_confirm(self) -> None:
        self.node.localConfig.network.wifi_enabled = True
        form = self.section_form("network")
        form.poplist("f__wifi_enabled")
        self.assertFalse(anc.apply_section(1, "network", form)[0])
        self.assertTrue(anc.apply_section(1, "network", with_values(form, confirm__wifi_enabled="1"))[0])

    def test_position_flags_bitmask(self) -> None:
        form = with_values(self.section_form("position"), f__position_flags=["1", "128"])
        ok, msg = anc.apply_section(1, "position", form)
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_config.position.position_flags, 129)

    def test_managed_mode_requires_admin_key_and_confirm(self) -> None:
        form = with_values(self.section_form("security"), f__is_managed="1", confirm__is_managed="1")
        ok, msg = anc.apply_section(1, "security", form)
        self.assertFalse(ok)
        self.assertIn("Admin-Schlüssel", msg)
        key = base64.b64encode(b"\x02" * 32).decode()
        form = with_values(form, f__admin_key=key, confirm__admin_key="1")
        ok, msg = anc.apply_section(1, "security", form)
        self.assertTrue(ok, msg)
        sec = self.node.sent[0].set_config.security
        self.assertTrue(sec.is_managed)
        self.assertEqual(list(sec.admin_key), [b"\x02" * 32])

    def test_new_private_key_clears_public_key(self) -> None:
        self.node.localConfig.security.private_key = b"\x01" * 32
        self.node.localConfig.security.public_key = b"\x02" * 32
        new_key = base64.b64encode(b"\x03" * 32).decode()
        form = with_values(self.section_form("security"), f__private_key=new_key)
        self.assertFalse(anc.apply_section(1, "security", form)[0])
        ok, msg = anc.apply_section(1, "security", with_values(form, confirm__private_key="1"))
        self.assertTrue(ok, msg)
        sec = self.node.sent[0].set_config.security
        self.assertEqual(sec.private_key, b"\x03" * 32)
        self.assertEqual(sec.public_key, b"")

    def test_unchanged_security_keeps_keypair(self) -> None:
        self.node.localConfig.security.private_key = b"\x01" * 32
        self.node.localConfig.security.public_key = b"\x02" * 32
        form = with_values(self.section_form("security"), f__debug_log_api_enabled="1")
        ok, msg = anc.apply_section(1, "security", form)
        self.assertTrue(ok, msg)
        sec = self.node.sent[0].set_config.security
        self.assertEqual((sec.private_key, sec.public_key), (b"\x01" * 32, b"\x02" * 32))

    def test_private_key_has_no_clear_option(self) -> None:
        self.node.localConfig.security.private_key = b"\x01" * 32
        html_text = anc.build_config_tab_html(anc.tab_by_key("security"), self.node, iface_id=1)
        self.assertNotIn('name="clear__private_key"', html_text)
        form = with_values(self.section_form("security"), clear__private_key="1")
        ok, msg = anc.apply_section(1, "security", form)
        self.assertTrue(ok, msg)
        self.assertIn("keine Änderungen", msg)

    def test_admin_key_length_checked(self) -> None:
        form = with_values(self.section_form("security"), f__admin_key=base64.b64encode(b"x" * 10).decode(),
                           confirm__admin_key="1")
        ok, msg = anc.apply_section(1, "security", form)
        self.assertFalse(ok)
        self.assertIn("32 Byte", msg)

    def test_bluetooth_fixed_pin_needs_six_digits(self) -> None:
        fixed = config_pb2.Config.BluetoothConfig.PairingMode.Value("FIXED_PIN")
        form = with_values(self.section_form("bluetooth"), f__mode=fixed, f__fixed_pin=123)
        self.assertFalse(anc.apply_section(1, "bluetooth", form)[0])
        ok, msg = anc.apply_section(1, "bluetooth", with_values(form, f__fixed_pin=123456))
        self.assertTrue(ok, msg)

    def test_mqtt_nested_map_report(self) -> None:
        form = with_values(self.section_form("mqtt"), **{
            "f__enabled": "1",
            "f__map_report_settings.publish_interval_secs": 3600,
            "f__map_report_settings.position_precision": 14,
        })
        ok, msg = anc.apply_section(1, "mqtt", form)
        self.assertTrue(ok, msg)
        mqtt = self.node.sent[0].set_module_config.mqtt
        self.assertTrue(mqtt.enabled)
        self.assertEqual(mqtt.map_report_settings.publish_interval_secs, 3600)
        self.assertEqual(self.node.moduleConfig.mqtt.map_report_settings.position_precision, 14)

    def test_range_test_sender_needs_confirm(self) -> None:
        form = with_values(self.section_form("range_test"), f__sender=60)
        self.assertFalse(anc.apply_section(1, "range_test", form)[0])
        self.assertTrue(anc.apply_section(1, "range_test", with_values(form, confirm__sender="1"))[0])

    def test_remote_hardware_pins(self) -> None:
        form = with_values(self.section_form("remote_hardware"), f__available_pins="12;Relais;DIGITAL_WRITE\n4;Tür;digital_read")
        ok, msg = anc.apply_section(1, "remote_hardware", form)
        self.assertTrue(ok, msg)
        pins = self.node.sent[0].set_module_config.remote_hardware.available_pins
        self.assertEqual([(p.gpio_pin, p.name) for p in pins], [(12, "Relais"), (4, "Tür")])
        bad = with_values(self.section_form("remote_hardware"), f__available_pins="12;Relais")
        self.assertFalse(anc.apply_section(1, "remote_hardware", bad)[0])

    def test_module_without_lib_writeconfig_uses_admin_message(self) -> None:
        if "statusmessage" not in anc._section_names("module"):
            self.skipTest("statusmessage not in installed protobufs")
        form = with_values(self.section_form("statusmessage"), f__node_status="Bot online")
        ok, msg = anc.apply_section(1, "statusmessage", form)
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_module_config.statusmessage.node_status, "Bot online")

    def test_paxcounter_negative_threshold(self) -> None:
        form = with_values(self.section_form("paxcounter"), f__wifi_threshold=-80)
        ok, msg = anc.apply_section(1, "paxcounter", form)
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_module_config.paxcounter.wifi_threshold, -80)

    def test_string_maxlen_rejected(self) -> None:
        form = with_values(self.section_form("mqtt"), f__root="x" * 40)
        ok, msg = anc.apply_section(1, "mqtt", form)
        self.assertFalse(ok)
        self.assertIn("maximal 31", msg)

    def test_special_tab_not_accepted_as_section(self) -> None:
        self.assertFalse(anc.apply_section(1, "admin", MultiDict())[0])

    def test_role_gate_covers_sleeping_and_hidden_roles(self) -> None:
        role = config_pb2.Config.DeviceConfig.Role
        for name in ("ROUTER", "ROUTER_LATE", "TRACKER", "SENSOR", "TAK_TRACKER", "CLIENT_HIDDEN", "LOST_AND_FOUND"):
            self.assertTrue(anc.role_change_needs_confirm(0, role.Value(name)), name)
        for name in ("CLIENT", "CLIENT_MUTE", "TAK", "CLIENT_BASE"):
            self.assertFalse(anc.role_change_needs_confirm(2, role.Value(name)), name)
        form = with_values(self.section_form("device"), f__role=role.Value("TRACKER"))
        self.assertFalse(anc.apply_section(1, "device", form)[0])

    def test_deprecated_fields_are_read_only(self) -> None:
        html_text = anc.build_config_tab_html(anc.tab_by_key("device"), self.node, iface_id=1)
        self.assertNotIn('name="present" value="is_managed"', html_text)
        self.assertIn("nur Anzeige", html_text)
        form = with_values(self.section_form("device"), f__is_managed="1", confirm__is_managed="1")
        form.add("present", "is_managed")
        ok, msg = anc.apply_section(1, "device", form)
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent, [])

    def test_canned_message_enabled_stays_editable(self) -> None:
        form = with_values(self.section_form("canned_message"), f__enabled="1")
        ok, msg = anc.apply_section(1, "canned_message", form)
        self.assertTrue(ok, msg)
        self.assertTrue(self.node.sent[0].set_module_config.canned_message.enabled)

    def test_mqtt_password_not_rendered(self) -> None:
        self.node.moduleConfig.mqtt.password = "mqtt-geheim"
        html_text = anc.build_config_tab_html(anc.tab_by_key("mqtt"), self.node, iface_id=1)
        self.assertNotIn("mqtt-geheim", html_text)


class StaleCacheTests(NodeConfigTestBase):
    def test_section_reread_before_write_rejects_external_change(self) -> None:
        form = with_values(self.section_form("lora"), f__hop_limit=5)
        changed = config_pb2.Config.LoRaConfig()
        changed.CopyFrom(self.node.localConfig.lora)
        changed.tx_power = 20
        self.node.device_override[("config", "lora")] = changed
        ok, msg = anc.apply_section(1, "lora", form)
        self.assertFalse(ok)
        self.assertIn("seit dem Laden", msg)
        self.assertEqual(self.node.sent, [])
        self.assertEqual(self.node.localConfig.lora.tx_power, 20)
        ok, msg = anc.apply_section(1, "lora", with_values(self.section_form("lora"), f__hop_limit=5))
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_config.lora.tx_power, 20)
        self.assertEqual(self.node.sent[0].set_config.lora.hop_limit, 5)

    def test_unanswered_reread_falls_back_with_note(self) -> None:
        self.node.answer_config_requests = False
        form = with_values(self.section_form("lora"), f__hop_limit=5)
        with mock.patch.object(anc, "REFRESH_TIMEOUT_S", 0.05):
            ok, msg = anc.apply_section(1, "lora", form)
        self.assertTrue(ok, msg)
        self.assertIn("Abgleich mit der Node", msg)

    def test_refresh_link_reads_device_on_get(self) -> None:
        changed = config_pb2.Config.LoRaConfig()
        changed.CopyFrom(self.node.localConfig.lora)
        changed.hop_limit = 6
        self.node.device_override[("config", "lora")] = changed
        html_text = anc.build_config_tab_html(anc.tab_by_key("lora"), self.node, iface_id=1, refresh=True)
        self.assertIn("gerade von der Node gelesen", html_text)
        self.assertEqual(self.node.localConfig.lora.hop_limit, 6)

    def test_request_enum_for_every_section(self) -> None:
        for kind in ("config", "module"):
            for section in anc._section_names(kind):
                self.assertIsNotNone(anc.section_request_enum(kind, section), section)


class CsrfAndDispatchTests(NodeConfigTestBase):
    def test_dispatch_rejects_missing_or_wrong_token(self) -> None:
        session: Dict[str, Any] = {}
        token = anc.ensure_csrf_token(session)
        form = MultiDict({"action": "admin_action", "admin_op": "factory_reset_device",
                          "confirm_admin": "1", "confirm_word": "RESET"})
        ok, msg = anc.dispatch_post(1, form, session)
        self.assertFalse(ok)
        self.assertIn("Sicherheits-Token", msg)
        form["csrf_token"] = "x" * len(token)
        self.assertFalse(anc.dispatch_post(1, form, session)[0])
        self.assertFalse(anc.dispatch_post(1, form, {})[0])
        self.assertEqual(self.node.sent, [])
        form["csrf_token"] = token
        self.assertTrue(anc.dispatch_post(1, form, session)[0])
        self.assertEqual(self.node.sent[0].factory_reset_device, 1)

    def test_unknown_action_rejected(self) -> None:
        session: Dict[str, Any] = {}
        token = anc.ensure_csrf_token(session)
        for action in ("", "bogus"):
            ok, msg = anc.dispatch_post(1, MultiDict({"action": action, "csrf_token": token}), session)
            self.assertFalse(ok)
            self.assertIn("Unbekannte Aktion", msg)

    def test_token_injected_into_every_post_form(self) -> None:
        html_text = anc.inject_csrf(anc.build_admin_tab_html(self.node, iface_id=1), "tok123")
        self.assertEqual(html_text.count('<form method="post"'), html_text.count('name="csrf_token" value="tok123"'))
        self.assertGreater(html_text.count('name="csrf_token"'), 0)


class LibraryContractTests(unittest.TestCase):
    def test_send_admin_signature(self) -> None:
        import inspect

        from meshtastic.node import Node

        params = inspect.signature(Node._sendAdmin).parameters
        for name in ("p", "wantResponse", "onResponse", "adminIndex"):
            self.assertIn(name, params)


class OverviewOwnerTests(unittest.TestCase):
    """Overview form must not reset owner flags or bypass the role gate."""

    def setUp(self) -> None:
        from modules import admin_web_ops as ops

        self.ops = ops
        self.node = mock.Mock()
        self.node.localConfig = localonly_pb2.LocalConfig()
        self.node.localConfig.position.fixed_position = True
        self.owner_calls: List[Dict[str, Any]] = []

        def set_owner(long_name=None, short_name=None, is_licensed=False, is_unmessagable=None):
            self.owner_calls.append({"long_name": long_name, "short_name": short_name,
                                     "is_licensed": is_licensed, "is_unmessagable": is_unmessagable})

        self.node.setOwner = set_owner
        settings = dict(_OVERVIEW_SETTINGS, is_licensed=True, is_unmessagable=True, latitude=50.1,
                        longitude=8.6, altitude_m=120)
        for target, value in (
            ("_local_node_for_iface", lambda iface_id: (self.node, None)),
            ("fetch_local_node_settings", lambda iface_id: (None, dict(settings))),
        ):
            p = mock.patch.object(ops, target, value)
            p.start()
            self.addCleanup(p.stop)

    def _form(self, **extra: str) -> Dict[str, str]:
        form = {"action": "save_overview", "short_name": "NEU", "long_name": "Neuer Name", "role": "0",
                "rebroadcast_mode": "0", "node_info_broadcast_secs": "10800", "position_broadcast_secs": "900",
                "latitude": "50.1", "longitude": "8.6", "altitude_m": "120"}
        form.update(extra)
        return form

    def test_rename_keeps_licensed_and_unmessagable(self) -> None:
        ok, msg = self.ops.apply_local_node_settings(1, self._form())
        self.assertTrue(ok, msg)
        self.assertEqual(self.owner_calls[0]["is_licensed"], True)
        self.assertEqual(self.owner_calls[0]["is_unmessagable"], True)

    def test_router_role_needs_confirm(self) -> None:
        ok, msg = self.ops.apply_local_node_settings(1, self._form(role="2"))
        self.assertFalse(ok)
        self.assertIn("Rolle", msg)
        self.assertEqual(self.owner_calls, [])
        ok, msg = self.ops.apply_local_node_settings(1, self._form(role="2", confirm__role="1"))
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.localConfig.device.role, 2)


class OwnerTests(NodeConfigTestBase):
    def test_owner_render_roundtrip_noop(self) -> None:
        form = forms_of(anc.build_user_tab_html(self.node.iface.user, iface_id=1))[0]
        ok, msg = anc.apply_owner(1, form)
        self.assertTrue(ok, msg)
        self.assertIn("keine Änderungen", msg)

    def test_owner_change(self) -> None:
        form = MultiDict({"long_name": "Neuer Name", "short_name": "NN", "is_unmessagable": "1"})
        ok, msg = anc.apply_owner(1, form)
        self.assertTrue(ok, msg)
        owner = self.node.sent[0].set_owner
        self.assertEqual((owner.long_name, owner.short_name, owner.is_unmessagable), ("Neuer Name", "NN", True))

    def test_short_name_too_long(self) -> None:
        ok, msg = anc.apply_owner(1, MultiDict({"long_name": "X", "short_name": "ABCDE"}))
        self.assertFalse(ok)
        self.assertIn("Kurzname", msg)

    def test_ham_mode_requires_confirm(self) -> None:
        form = MultiDict({"long_name": "DL0ABC", "short_name": "DL0", "is_licensed": "1"})
        ok, msg = anc.apply_owner(1, form)
        self.assertFalse(ok)
        self.assertIn("Amateurfunk", msg)
        form["confirm__is_licensed"] = "1"
        ok, msg = anc.apply_owner(1, form)
        self.assertFalse(ok)
        self.assertIn("„HAM“", msg)
        self.assertEqual(self.node.sent, [])
        form["confirm_word_ham"] = "ham"
        self.assertTrue(anc.apply_owner(1, form)[0])
        self.assertTrue(self.node.sent[0].set_owner.is_licensed)

    def test_ham_warning_lists_firmware_side_effects(self) -> None:
        for phrase in ("PSK aller Kanäle", "Admin-Kanal", "Schlüsselpaar", "Regionslimit"):
            self.assertIn(phrase, anc.HAM_WARNING)

    def test_owner_save_updates_local_cache(self) -> None:
        ok, _ = anc.apply_owner(1, MultiDict({"long_name": "Neu", "short_name": "NEU"}))
        self.assertTrue(ok)
        self.assertEqual(self.node.iface.nodesByNum[1]["user"]["longName"], "Neu")


class StringsAndAdminTests(NodeConfigTestBase):
    def test_canned_messages_join_and_limit(self) -> None:
        ok, msg = anc.apply_canned_messages(1, MultiDict({"canned_messages": "Hallo\n\nBin unterwegs\r\nOK"}))
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].set_canned_message_module_messages, "Hallo|Bin unterwegs|OK")
        ok, msg = anc.apply_canned_messages(1, MultiDict({"canned_messages": "x" * 201}))
        self.assertFalse(ok)
        self.assertIn("nichts abgeschnitten", msg)

    def test_ringtone_limit(self) -> None:
        self.assertFalse(anc.apply_ringtone(1, MultiDict({"ringtone": "a" * 231}))[0])
        self.assertTrue(anc.apply_ringtone(1, MultiDict({"ringtone": "24:d=32,o=5,b=565:f6"}))[0])
        self.assertEqual(self.node.sent[0].set_ringtone_message, "24:d=32,o=5,b=565:f6")

    def test_request_admin_string_reads_response(self) -> None:
        def responder(p):
            raw = admin_pb2.AdminMessage(get_canned_message_module_messages_response="A|B")
            return {"decoded": {"admin": {"raw": raw}}}

        self.node.responder = responder
        val, err = anc.request_admin_string(self.node, "get_canned_message_module_messages_request",
                                            "get_canned_message_module_messages_response", timeout=0.5)
        self.assertIsNone(err)
        self.assertEqual(val, "A|B")

    def test_request_admin_string_times_out(self) -> None:
        val, err = anc.request_admin_string(self.node, "get_ringtone_request", "get_ringtone_response",
                                            timeout=0.05)
        self.assertIsNone(val)
        self.assertIn("Timeout", err or "")

    def test_reboot_requires_confirm(self) -> None:
        self.assertFalse(anc.apply_admin_action(1, MultiDict({"admin_op": "reboot", "seconds": "5"}))[0])
        ok, msg = anc.apply_admin_action(1, MultiDict({"admin_op": "reboot", "seconds": "7", "confirm_admin": "1"}))
        self.assertTrue(ok, msg)
        self.assertEqual(self.node.sent[0].reboot_seconds, 7)

    def test_factory_reset_requires_word(self) -> None:
        form = MultiDict({"admin_op": "factory_reset_config", "confirm_admin": "1"})
        ok, msg = anc.apply_admin_action(1, form)
        self.assertFalse(ok)
        self.assertIn("RESET", msg)
        form["confirm_word"] = "RESET"
        self.assertTrue(anc.apply_admin_action(1, form)[0])
        self.assertEqual(self.node.sent[0].factory_reset_config, 1)

    def test_nodedb_reset_and_set_time(self) -> None:
        self.assertTrue(anc.apply_admin_action(1, MultiDict({"admin_op": "nodedb_reset", "confirm_admin": "1"}))[0])
        self.assertTrue(self.node.sent[0].nodedb_reset)
        self.assertTrue(anc.apply_admin_action(1, MultiDict({"admin_op": "set_time"}))[0])
        self.assertGreater(self.node.sent[1].set_time_only, 0)

    def test_unknown_admin_op(self) -> None:
        self.assertFalse(anc.apply_admin_action(1, MultiDict({"admin_op": "rm -rf"}))[0])

    def test_admin_tab_renders(self) -> None:
        html_text = anc.build_admin_tab_html(self.node, iface_id=1)
        for a in anc.ADMIN_ACTIONS:
            self.assertIn(f'value="{a.key}"', html_text)

    def test_nav_marks_active_tab(self) -> None:
        nav = anc.build_tab_nav_html("lora", iface_id=1, ifaces=[1, 2], base_url="/node-settings")
        self.assertIn('class="nav-link py-1 px-2 active" href="/node-settings?iface=1&amp;tab=lora"', nav)
        self.assertIn("iface=2&amp;tab=lora", nav)


class ChannelModuleSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        from meshtastic.protobuf import channel_pb2
        from modules import admin_web_ops as ops

        self.ops = ops
        self.written: List[int] = []
        ch = channel_pb2.Channel(index=1, role=2)
        ch.settings.name = "MeshHessen"
        node = mock.Mock()
        node.channels = [channel_pb2.Channel(index=0, role=1), ch]
        node.getChannelByChannelIndex = lambda i: node.channels[i]
        node.writeChannel = lambda i: self.written.append(i)
        self.channel = ch
        for target, value in (
            ("_local_node_for_iface", lambda iface_id: (node, None)),
            ("_system_mod", lambda: mock.Mock()),
        ):
            p = mock.patch.object(ops, target, value)
            p.start()
            self.addCleanup(p.stop)

    def _form(self, **extra: str) -> Dict[str, str]:
        form = {"channel_index": "1", "name": "MeshHessen", "role": "2", "is_muted_present": "1"}
        form.update(extra)
        return form

    def test_position_precision_and_mute_saved(self) -> None:
        ok, msg = self.ops.apply_local_channel_settings(1, self._form(position_precision="13", is_muted="1"))
        self.assertTrue(ok, msg)
        self.assertEqual(self.written, [1])
        self.assertEqual(self.channel.settings.module_settings.position_precision, 13)
        self.assertTrue(self.channel.settings.module_settings.is_muted)

    def test_position_precision_out_of_range(self) -> None:
        ok, msg = self.ops.apply_local_channel_settings(1, self._form(position_precision="33"))
        self.assertFalse(ok)
        self.assertIn("0 und 32", msg)
        self.assertEqual(self.written, [])


_OVERVIEW_SETTINGS: Dict[str, Any] = {
    "iface_id": 1, "iface_type": "tcp", "node_num": 1, "node_id_hex": "!00000001",
    "short_name": "HB", "long_name": "Hessenbot", "is_licensed": False, "role": 0, "role_name": "CLIENT",
    "rebroadcast_mode": 0, "rebroadcast_name": "ALL", "node_info_broadcast_secs": 10800,
    "position_broadcast_secs": 900, "fixed_position": True, "latitude": 50.1, "longitude": 8.6,
    "altitude_m": 120, "config_latitude": 50.1, "config_longitude": 8.6, "lora_region": "EU_868",
    "lora_modem_preset": "SHORT_SLOW", "lora_channel_num": 0, "is_unmessagable": False,
    # Keys added by PR #18 (TX power in Overview); harmless before it lands.
    "lora_tx_power": 14, "lora_tx_enabled": True,
}
_CHANNELS: List[Dict[str, Any]] = [{
    "index": 0, "name": "", "name_display": "ShortSlow", "label": "ShortSlow", "role": 1, "role_name": "PRIMARY",
    "psk_label": "default", "psk_value": "default", "uplink": False, "downlink": False, "empty": False,
    "position_precision": 13, "is_muted": False,
}]


class RouteTests(NodeConfigTestBase):
    def setUp(self) -> None:
        super().setUp()
        from modules import admin_web_ops as ops
        from modules.admin_web import create_app

        app = create_app(alert_path="alert.txt", news_path="alert.txt", log_dir="logs",
                         admin_username="admin", admin_password="pw", secret_key="test-secret")
        app.config["RATELIMIT_ENABLED"] = False
        for target, value in (
            ("iter_radio_interfaces", lambda: [1]),
            ("fetch_local_node_settings", lambda iface_id: (None, dict(_OVERVIEW_SETTINGS))),
            ("fetch_local_channels", lambda iface_id: (None, [dict(c) for c in _CHANNELS])),
        ):
            p = mock.patch.object(ops, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = app
        self.client = app.test_client()
        self.token = "t" * 43
        with self.client.session_transaction() as sess:
            sess["_user_id"] = "admin"
            sess["_fresh"] = True
            sess[anc.CSRF_SESSION_KEY] = self.token

    def test_session_cookie_samesite(self) -> None:
        self.assertEqual(self.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertEqual(self.app.config["REMEMBER_COOKIE_SAMESITE"], "Lax")

    def test_rendered_forms_carry_session_token(self) -> None:
        for tab in ("overview", "channels", "lora", "user", "admin"):
            body = self.client.get(f"/node-settings?iface=1&tab={tab}").get_data(as_text=True)
            self.assertGreater(body.count(f'name="csrf_token" value="{self.token}"'), 0, tab)
            self.assertEqual(body.count('<form method="post"'), body.count('name="csrf_token"'), tab)

    def test_post_without_token_is_rejected(self) -> None:
        resp = self.client.post("/node-settings?iface=1&tab=admin", data={
            "action": "admin_action", "iface_id": "1", "admin_op": "factory_reset_device",
            "confirm_admin": "1", "confirm_word": "RESET",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.node.sent, [])

    def test_every_tab_renders(self) -> None:
        with mock.patch.object(anc, "request_admin_string", lambda *a, **k: ("A|B", None)):
            for spec in anc.available_tabs():
                with self.subTest(tab=spec.key):
                    resp = self.client.get(f"/node-settings?iface=1&tab={spec.key}")
                    self.assertEqual(resp.status_code, 200)
                    body = resp.get_data(as_text=True)
                    self.assertIn("node-settings-tabs", body)
                    self.assertNotIn("Seite konnte nicht geladen werden", body)
                    self.assertIn(f"tab={spec.key}\" aria-current", body)

    def test_overview_and_channels_content(self) -> None:
        body = self.client.get("/node-settings?iface=1").get_data(as_text=True)
        self.assertIn('name="short_name"', body)
        self.assertEqual(body.count("Schnittstelle:"), 1)
        body = self.client.get("/node-settings?iface=1&tab=channels").get_data(as_text=True)
        self.assertIn('name="position_precision"', body)
        self.assertIn('name="is_muted"', body)

    def test_post_section_redirects_back_to_tab(self) -> None:
        resp = self.client.post("/node-settings?iface=1&tab=lora", data={
            "action": "save_section", "iface_id": "1", "section_tab": "lora",
            "present": "hop_limit", "f__hop_limit": "5", "csrf_token": self.token,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tab=lora", resp.headers["Location"])
        self.assertEqual(self.node.sent[0].set_config.lora.hop_limit, 5)


if __name__ == "__main__":
    unittest.main()
