# Unit tests for !trace formatting (no radio).
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_path)


class TestTraceFormat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # settings.py may create an empty config.ini on first import; seed from template.
        cfg = os.path.join(parent_path, "config.ini")
        tpl = os.path.join(parent_path, "config.template")
        cls._had_cfg = None
        if os.path.isfile(cfg):
            with open(cfg, "rb") as f:
                cls._had_cfg = f.read()
        if os.path.isfile(tpl):
            with open(tpl, "rb") as src, open(cfg, "wb") as dst:
                dst.write(src.read())
        # Import after config exists so modules.system side effects succeed.
        import modules.trace as trace  # noqa: F401

        cls.trace = trace

    @classmethod
    def tearDownClass(cls):
        cfg = os.path.join(parent_path, "config.ini")
        if cls._had_cfg is None:
            try:
                os.remove(cfg)
            except OSError:
                pass
        else:
            with open(cfg, "wb") as f:
                f.write(cls._had_cfg)

    def setUp(self):
        self._label = patch.object(
            self.trace,
            "_node_label",
            side_effect=lambda n, _i: f"N{int(n):08x}" if n is not None else "N?",
        )
        self._local = patch.object(self.trace, "_local_node_num", return_value=0x100)
        self._hops = patch.object(self.trace, "record_mesh_hops_from_trace")
        self._label.start()
        self._local.start()
        self._hops.start()
        self.addCleanup(self._label.stop)
        self.addCleanup(self._local.stop)
        self.addCleanup(self._hops.stop)

    def test_format_valid_route_discovery_payload(self):
        from meshtastic import mesh_pb2

        rd = mesh_pb2.RouteDiscovery()
        rd.route.extend([0x22222222])
        rd.snr_towards.extend([8, 12])  # hop + final
        payload = rd.SerializeToString()
        packet = {
            "from": 0x22222222,
            "to": 0x100,
            "hopStart": 3,
            "decoded": {"portnum": "TRACEROUTE_APP", "payload": payload},
        }
        text = self.trace.format_traceroute_packet(packet, node_int=1, dest_id=0x22222222)
        self.assertIn("Trace →", text)
        self.assertIn("Hin:", text)
        self.assertNotIn("fehlgeschlagen", text)
        self.assertNotIn("unlesbar", text)

    def test_format_prefers_predecoded_traceroute_dict(self):
        packet = {
            "from": 0xABCDEF01,
            "to": 0x100,
            "hopStart": 2,
            "decoded": {
                "portnum": "TRACEROUTE_APP",
                # Corrupt payload must be ignored when traceroute dict is present.
                "payload": b"\xff\xff\xff\xff",
                "traceroute": {
                    "route": [],
                    "snrTowards": [16],
                    "raw": object(),
                },
            },
        }
        text = self.trace.format_traceroute_packet(packet, node_int=1, dest_id=0xABCDEF01)
        self.assertIn("Direktverbindung", text)

    def test_routing_app_max_retransmit_not_parsed_as_route_discovery(self):
        from meshtastic import mesh_pb2

        routing = mesh_pb2.Routing()
        routing.error_reason = mesh_pb2.Routing.Error.MAX_RETRANSMIT
        # Nested route_request is what historically DecodeError'd as RouteDiscovery.
        routing.route_request.route.extend([0x11111111])

        packet = {
            "from": 0x1,
            "to": 0x100,
            "decoded": {
                "portnum": "ROUTING_APP",
                "payload": routing.SerializeToString(),
                "routing": {"errorReason": "MAX_RETRANSMIT"},
            },
        }
        text = self.trace.format_traceroute_packet(packet, node_int=1, dest_id=0xABCDEF01)
        self.assertIn("Routing-Fehler", text)
        self.assertIn("MAX_RETRANSMIT", text)
        self.assertNotIn("Error parsing message", text)
        self.assertNotIn("Wire format", text)

    def test_corrupt_payload_returns_german_unreadable_message(self):
        packet = {
            "from": 0x1,
            "to": 0x100,
            "decoded": {
                "portnum": "TRACEROUTE_APP",
                "payload": b"\xff\xff\xff\xff",
            },
        }
        text = self.trace.format_traceroute_packet(packet, node_int=1, dest_id=0xABCDEF01)
        self.assertIn("Antwort unlesbar", text)
        self.assertNotIn("Error parsing message", text)

    def test_routing_route_request_bytes_alone_would_decodeerror(self):
        """Document root cause: Routing.route_request ≠ RouteDiscovery wire layout."""
        from meshtastic import mesh_pb2
        from google.protobuf.message import DecodeError

        routing = mesh_pb2.Routing()
        routing.route_request.route.extend([0x11111111])
        payload = routing.SerializeToString()
        with self.assertRaises(DecodeError) as ctx:
            mesh_pb2.RouteDiscovery().ParseFromString(payload)
        self.assertIn("RouteDiscovery", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
