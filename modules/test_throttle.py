# Unit tests for command throttling (no radio / no ephem).
import os
import sys
import unittest

parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_path)


def _not_admin(_node_id):
    return False


def _is_admin(_node_id):
    return True


class TestCommandThrottle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prefer UTF-8 template so settings load on CI / Windows (local config.ini
        # may be latin-1).
        cls._cfg = os.path.join(parent_path, "config.ini")
        cls._had_cfg = None
        if os.path.isfile(cls._cfg):
            with open(cls._cfg, "rb") as f:
                cls._had_cfg = f.read()
        tpl = os.path.join(parent_path, "config.template")
        with open(tpl, "rb") as src, open(cls._cfg, "wb") as dst:
            dst.write(src.read())

    @classmethod
    def tearDownClass(cls):
        if cls._had_cfg is None:
            try:
                os.remove(cls._cfg)
            except OSError:
                pass
        else:
            with open(cls._cfg, "wb") as f:
                f.write(cls._had_cfg)

    def setUp(self):
        import modules.cmd_throttle as ct
        import modules.settings as st

        self.ct = ct
        self.st = st
        ct.reset_rate_limit()
        st.cmdRateLimitEnabled = True
        st.cmdRateLimitMax = 3
        st.cmdRateLimitWindow = 60
        st.cmdRateLimitNotifyOnce = True
        st.cmdExpensiveCooldownSec = 45
        st.cmdExpensiveCommands = ["wx", "warning", "blitz"]

    def tearDown(self):
        self.ct.reset_rate_limit()

    def test_extract_command_token(self):
        self.assertEqual(self.ct.extract_command_token("!wx Fulda"), "wx")
        self.assertEqual(self.ct.extract_command_token("ping?"), "ping")
        self.assertEqual(self.ct.extract_command_token(""), "")

    def test_global_notify_once_then_silent(self):
        node = "424242"
        self.assertIsNone(self.ct.check_command_throttle(node, "ping", is_admin=_not_admin))
        self.assertIsNone(self.ct.check_command_throttle(node, "ping", is_admin=_not_admin))
        self.assertIsNone(self.ct.check_command_throttle(node, "test", is_admin=_not_admin))
        msg = self.ct.check_command_throttle(node, "cmd", is_admin=_not_admin)
        self.assertEqual(msg, "⏱️ Bitte etwas langsamer.")
        silent = self.ct.check_command_throttle(node, "cmd", is_admin=_not_admin)
        self.assertEqual(silent, "")

    def test_expensive_cooldown_notify_then_silent(self):
        node = "111"
        self.assertIsNone(self.ct.check_command_throttle(node, "wx", is_admin=_not_admin))
        again = self.ct.check_command_throttle(node, "wx", is_admin=_not_admin)
        self.assertIsNotNone(again)
        self.assertIn("!wx", again)
        self.assertIn("s wieder", again)
        silent = self.ct.check_command_throttle(node, "wx", is_admin=_not_admin)
        self.assertEqual(silent, "")

    def test_admin_exempt(self):
        node = "999"
        for _ in range(10):
            self.assertIsNone(self.ct.check_command_throttle(node, "wx", is_admin=_is_admin))

    def test_snapshot_and_reset(self):
        node = "555"
        self.ct.check_command_throttle(node, "ping", is_admin=_not_admin)
        self.ct.check_command_throttle(node, "wx", is_admin=_not_admin)
        rows = self.ct.get_rate_limit_snapshot()
        self.assertTrue(any(r["node_id"] == node for r in rows))
        n = self.ct.reset_rate_limit(node)
        self.assertEqual(n, 1)
        rows2 = self.ct.get_rate_limit_snapshot()
        self.assertFalse(any(r["node_id"] == node for r in rows2))


if __name__ == "__main__":
    unittest.main()
