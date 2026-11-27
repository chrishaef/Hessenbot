# Unit tests for link_status (no radio, no Flask).
# Run: python -m pytest modules/test_link_status.py -q
import os
import sys
import threading
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules import link_status as ls


class _ModuleConfig:
    def __init__(self, enabled, loaded=True):
        self.mqtt = types.SimpleNamespace(enabled=enabled)
        self._loaded = loaded

    def HasField(self, name):
        return self._loaded


def _iface(connected=True, mqtt_enabled=True, name="HESS"):
    ev = threading.Event()
    if connected:
        ev.set()
    return types.SimpleNamespace(
        isConnected=ev,
        localNode=types.SimpleNamespace(moduleConfig=_ModuleConfig(mqtt_enabled)),
        getMyNodeInfo=lambda: {"user": {"shortName": name}},
    )


def _sm(iface=None, retry=False):
    return types.SimpleNamespace(
        interface1_enabled=True,
        interface1_type="tcp",
        interface1=iface,
        retry_int1=retry,
        _interface_reconnecting=set(),
    )


class TestLinkStatus(unittest.TestCase):
    def setUp(self):
        ls.reset_for_tests()

    def test_mqtt_transport_detection(self):
        self.assertTrue(ls.packet_via_mqtt_transport({"transport_mechanism": "TRANSPORT_MQTT"}))
        self.assertFalse(ls.packet_via_mqtt_transport({"transport_mechanism": "TRANSPORT_LORA"}))
        self.assertTrue(ls.packet_via_mqtt_transport({"decoded": {"viaMqtt": True}}))
        self.assertFalse(ls.packet_via_mqtt_transport({"transport_mechanism": "TRANSPORT_LORA", "viaMqtt": True}))
        self.assertFalse(ls.packet_via_mqtt_transport("nope"))

    def test_hardware_down_when_interface_missing(self):
        d = ls.collect_link_status(_sm(None, retry=True), now=1000.0)
        hw = d["hardware"][0]
        self.assertEqual(hw["state"], "down")
        self.assertIn("Reconnect", hw["detail"])
        self.assertEqual(d["mqtt"]["state"], "unknown")

    def test_hardware_warn_when_not_connected_event(self):
        d = ls.collect_link_status(_sm(_iface(connected=False)), now=1000.0)
        self.assertEqual(d["hardware"][0]["state"], "warn")

    def test_hardware_ok_and_mqtt_flow(self):
        ls.record_rx({"transport_mechanism": "TRANSPORT_MQTT"}, 1, now=990.0)
        d = ls.collect_link_status(_sm(_iface()), now=1000.0)
        self.assertEqual(d["hardware"][0]["state"], "ok")
        self.assertEqual(d["hardware"][0]["last_rx_age_sec"], 10.0)
        self.assertEqual(d["mqtt"]["state"], "ok")
        self.assertEqual(d["mqtt"]["packet_count"], 1)

    def test_mqtt_stale_is_warn(self):
        ls.record_rx({"transport_mechanism": "TRANSPORT_MQTT"}, 1, now=100.0)
        d = ls.collect_link_status(_sm(_iface()), now=100.0 + ls.MQTT_FLOW_WINDOW_SEC + 5)
        self.assertEqual(d["mqtt"]["state"], "warn")

    def test_mqtt_never_seen_is_warn_and_disabled_is_unknown(self):
        d = ls.collect_link_status(_sm(_iface(mqtt_enabled=True)), now=1000.0)
        self.assertEqual(d["mqtt"]["state"], "warn")
        d = ls.collect_link_status(_sm(_iface(mqtt_enabled=False)), now=1000.0)
        self.assertEqual(d["mqtt"]["state"], "unknown")
        self.assertIn("nicht aktiviert", d["mqtt"]["text"])

    def test_lora_packets_do_not_count_as_mqtt(self):
        ls.record_rx({"transport_mechanism": "TRANSPORT_LORA"}, 1, now=990.0)
        d = ls.collect_link_status(_sm(_iface()), now=1000.0)
        self.assertEqual(d["hardware"][0]["last_rx_age_sec"], 10.0)
        self.assertEqual(d["mqtt"]["state"], "warn")

    def test_html_escaped_and_no_secrets(self):
        d = ls.collect_link_status(_sm(_iface(name="<b>")), now=1000.0)
        self.assertNotIn("<b>", d["html"])
        self.assertIn("&lt;b&gt;", d["html"])

    def test_format_age(self):
        self.assertEqual(ls.format_age(5), "vor 5 s")
        self.assertEqual(ls.format_age(125), "vor 2 min")
        self.assertEqual(ls.format_age(None), "—")


if __name__ == "__main__":
    unittest.main()
