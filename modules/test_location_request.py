# Unit tests for location_request (no radio).
import os
import sys
import time
import unittest
from unittest.mock import patch

parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_path)


class TestLocationRequest(unittest.TestCase):
    def setUp(self):
        import modules.cmd_throttle as ct
        import modules.location_request as lr
        import modules.settings as st

        self.lr = lr
        self.st = st
        ct.reset_rate_limit()
        with lr._lock:
            lr._pending.clear()
            lr._last_request_ts.clear()
        st.location_request_enabled = True
        st.location_request_timeout_sec = 25
        st.location_request_cooldown_sec = 60

    def tearDown(self):
        with self.lr._lock:
            self.lr._pending.clear()
            self.lr._last_request_ts.clear()

    def test_hint_texts(self):
        from modules.locale_de import location_request_ack, location_request_timeout_hint

        self.assertIn("warten", location_request_ack().lower())
        self.assertIn("Fulda", location_request_timeout_hint("wx", "weather"))
        self.assertIn("GPS", location_request_timeout_hint("whereami", "gps_only"))

    def test_args_skip_request(self):
        built = []

        def build(lat, lon, source, label):
            built.append((lat, lon, source))
            return "ok"

        with patch.object(self.lr, "_fire_position_request"):
            result = self.lr.resolve_or_request_location(
                "!wx 50.34 8.76",
                123,
                1,
                command_tokens=("wx",),
                cmd_key="wx",
                build_response=build,
            )
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[2], "arg-coords")
        self.assertFalse(self.lr.has_pending(123))

    def test_defer_when_missing(self):
        def build(lat, lon, source, label):
            return f"{lat},{lon}"

        with (
            patch.object(self.lr, "lookup_known_node_location", return_value=None),
            patch.object(self.lr, "_fire_position_request"),
            patch.object(self.lr, "_send_ack"),
            patch.object(self.lr, "_watch_pending"),
        ):
            result = self.lr.resolve_or_request_location(
                "!wx",
                4242,
                1,
                command_tokens=("wx",),
                cmd_key="wx",
                build_response=build,
                channel=0,
                is_dm=True,
            )
        self.assertIsNone(result)
        self.assertTrue(self.lr.has_pending(4242))

    def test_complete_idempotent(self):
        done = []

        def build(lat, lon, source, label):
            done.append(1)
            return "done"

        with self.lr._lock:
            self.lr._pending["99"] = {
                "node_id": 99,
                "device_id": 1,
                "channel": 0,
                "is_dm": True,
                "reply_id": None,
                "cmd_key": "wx",
                "timeout_kind": "weather",
                "build_response": build,
                "started": time.time(),
            }
        with patch.object(self.lr, "_send_text"):
            self.assertTrue(self.lr.try_complete_pending_location(99, lat=50.1, lon=8.2))
            self.assertFalse(self.lr.try_complete_pending_location(99, lat=50.1, lon=8.2))
        self.assertEqual(len(done), 1)


if __name__ == "__main__":
    unittest.main()
