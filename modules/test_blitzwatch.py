# Unit tests for Blitzwatch prefs / command parsing (no radio).
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_path)


class TestBlitzwatch(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmpdir.name, "blitzwatch.db")
        import modules.blitzwatch as bw

        self.bw = bw
        # Point module at temp DB
        self._path_patch = patch.object(bw, "_db_path", return_value=self.db)
        self._path_patch.start()
        bw.initialize_blitzwatch_database()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_default_prefs_enabled(self):
        prefs = self.bw.get_node_prefs(12345)
        self.assertTrue(prefs["enabled"])
        self.assertEqual(prefs["radius_km"], 8)
        self.assertFalse(prefs["in_db"])

    def test_opt_out_and_radius(self):
        self.bw.set_node_enabled(99, False)
        prefs = self.bw.get_node_prefs(99)
        self.assertFalse(prefs["enabled"])
        self.assertTrue(prefs["in_db"])

        prefs = self.bw.set_node_radius(99, 5)
        self.assertTrue(prefs["enabled"])
        self.assertEqual(prefs["radius_km"], 5)

        prefs = self.bw.set_node_radius(99, 99)
        self.assertEqual(prefs["radius_km"], 10)

    def test_clamp_radius(self):
        self.assertEqual(self.bw.clamp_radius_km(0), 1)
        self.assertEqual(self.bw.clamp_radius_km(3), 3)
        self.assertEqual(self.bw.clamp_radius_km(50), 10)

    def test_command_on_off_radius(self):
        import types

        import modules.settings as st

        st.blitz_watch_enabled = True
        st.location_enabled = True
        fake_system = types.ModuleType("modules.system")
        fake_system._nodedb_fresh_position = lambda *a, **k: (50.5, 9.6, None)
        with patch.dict(sys.modules, {"modules.system": fake_system}):
            out = self.bw.handle_blitzwatch_command("!blitzwatch off", 42, 1)
            self.assertIn("AUS", out)
            self.assertFalse(self.bw.get_node_prefs(42)["enabled"])

            out = self.bw.handle_blitzwatch_command("!blitzwatch on", 42, 1)
            self.assertIn("AN", out)

            out = self.bw.handle_blitzwatch_command("!blitzwatch 5km", 42, 1)
            self.assertIn("5 km", out)
            self.assertEqual(self.bw.get_node_prefs(42)["radius_km"], 5)

            out = self.bw.handle_blitzwatch_command("!blitzwatch?", 42, 1)
            self.assertIn("blitzwatch", out.lower())
            self.assertIn("Radius: 5 km", out)

    def test_channel_meta_cooldown(self):
        self.bw.set_meta(self.bw.META_CHANNEL_TS, "100.0")
        self.assertEqual(self.bw.get_meta(self.bw.META_CHANNEL_TS), "100.0")


if __name__ == "__main__":
    unittest.main()
