# Unit tests for Blitzwatch prefs / command parsing (no radio).
import os
import sys
import tempfile
import types
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
        self._path_patch = patch.object(bw, "_db_path", return_value=self.db)
        self._path_patch.start()
        bw.initialize_blitzwatch_database()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _fake_system_gps(self, pos=(50.5, 9.6, None)):
        fake_system = types.ModuleType("modules.system")
        fake_system._nodedb_fresh_position = lambda *a, **k: pos
        return fake_system

    def test_default_prefs_enabled(self):
        prefs = self.bw.get_node_prefs(12345)
        self.assertTrue(prefs["enabled"])
        self.assertEqual(prefs["radius_km"], 8)
        self.assertEqual(prefs["home_mode"], "gps")
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
        import modules.settings as st

        st.blitz_watch_enabled = True
        st.location_enabled = True
        with patch.dict(sys.modules, {"modules.system": self._fake_system_gps()}):
            out = self.bw.handle_blitzwatch_command("!blitzwatch off", 42, 1)
            self.assertIn("AUS", out)
            self.assertFalse(self.bw.get_node_prefs(42)["enabled"])

            out = self.bw.handle_blitzwatch_command("!blitzwatch on", 42, 1)
            self.assertIn("AN", out)

            out = self.bw.handle_blitzwatch_command("!blitzwatch 5km", 42, 1)
            self.assertIn("5 km", out)
            self.assertEqual(self.bw.get_node_prefs(42)["radius_km"], 5)

            out = self.bw.handle_blitzwatch_command("!blitzwatch?", 42, 1)
            self.assertIn("Einstellen", out)
            self.assertIn("!blitzwatch on", out)
            self.assertIn("home Friedberg", out)
            self.assertNotIn("Warnung für deine Node", out)

            out = self.bw.handle_blitzwatch_command("!blitzwatch", 42, 1)
            self.assertIn("Warnung für deine Node", out)
            self.assertIn("!blitzwatch?", out)
            self.assertIn("5 km", out)

    def test_home_fixed_and_gps(self):
        import modules.settings as st

        st.blitz_watch_enabled = True
        st.location_enabled = True
        with patch.dict(sys.modules, {"modules.system": self._fake_system_gps()}):
            out = self.bw.handle_blitzwatch_command(
                "!blitzwatch home JO40AA", 7, 1
            )
            self.assertIn("Home Fix", out)
            prefs = self.bw.get_node_prefs(7)
            self.assertEqual(prefs["home_mode"], "fixed")
            self.assertIsNotNone(prefs["home_lat"])
            self.assertEqual(prefs["home_label"], "JO40AA")

            out = self.bw.handle_blitzwatch_command("!blitzwatch home gps", 7, 1)
            self.assertIn("GPS", out)
            prefs = self.bw.get_node_prefs(7)
            self.assertEqual(prefs["home_mode"], "gps")
            self.assertIsNone(prefs["home_lat"])

    def test_add_max_three_del_and_slot_radius(self):
        import modules.settings as st

        st.blitz_watch_enabled = True
        st.location_enabled = True
        with patch.dict(sys.modules, {"modules.system": self._fake_system_gps()}):
            with patch(
                "modules.locationdata.geocode_place_name",
                side_effect=[
                    (50.1, 8.7, "Frankfurt"),
                    (51.0, 9.0, "Kassel"),
                    (50.0, 8.0, "Darmstadt"),
                    (49.9, 8.6, "Mainz"),
                ],
            ):
                out = self.bw.handle_blitzwatch_command(
                    "!blitzwatch add Frankfurt", 11, 1
                )
                self.assertIn("Zusatzort 1", out)
                out = self.bw.handle_blitzwatch_command(
                    "!blitzwatch add 5km Kassel", 11, 1
                )
                self.assertIn("Zusatzort 2", out)
                locs = self.bw.list_locations(11)
                self.assertEqual(len(locs), 2)
                self.assertEqual(locs[1]["radius_km"], 5)

                self.bw.handle_blitzwatch_command("!blitzwatch add Darmstadt", 11, 1)
                self.assertEqual(self.bw.count_locations(11), 3)

                out = self.bw.handle_blitzwatch_command(
                    "!blitzwatch add Mainz", 11, 1
                )
                self.assertIn("Maximal 3", out)

            out = self.bw.handle_blitzwatch_command("!blitzwatch 2 3km", 11, 1)
            self.assertIn("3 km", out)
            loc2 = [x for x in self.bw.list_locations(11) if x["slot"] == 2][0]
            self.assertEqual(loc2["radius_km"], 3)

            out = self.bw.handle_blitzwatch_command("!blitzwatch del 2", 11, 1)
            self.assertIn("gelöscht", out)
            slots = {x["slot"] for x in self.bw.list_locations(11)}
            self.assertEqual(slots, {1, 3})

            # Re-add uses free slot 2 (stable numbering)
            with patch(
                "modules.locationdata.geocode_place_name",
                return_value=(50.2, 8.5, "Bad Homburg"),
            ):
                out = self.bw.handle_blitzwatch_command(
                    "!blitzwatch add Bad Homburg", 11, 1
                )
                self.assertIn("Zusatzort 2", out)

    def test_add_coords(self):
        import modules.settings as st

        st.blitz_watch_enabled = True
        st.location_enabled = True
        with patch.dict(sys.modules, {"modules.system": self._fake_system_gps()}):
            out = self.bw.handle_blitzwatch_command(
                "!blitzwatch add 50.34 8.76", 22, 1
            )
            self.assertIn("Zusatzort 1", out)
            loc = self.bw.list_locations(22)[0]
            self.assertAlmostEqual(loc["lat"], 50.34, places=2)
            self.assertAlmostEqual(loc["lon"], 8.76, places=2)

    def test_candidates_fixed_home_without_gps(self):
        import modules.settings as st

        st.blitz_watch_cooldown_sec = 3600
        self.bw.set_home_fixed(55, 50.0, 8.0, "Relais", radius_km=6)
        self.bw.add_location(55, 51.0, 9.0, "Anlage", 4)

        fake_system = types.ModuleType("modules.system")
        fake_system._nodedb_fresh_position = lambda *a, **k: None
        fake_system.get_name_from_number = lambda *a, **k: "N55"
        fake_system.interface1_enabled = True
        fake_iface = types.SimpleNamespace(nodes={"x": {"num": 55}})
        fake_system.interface1 = fake_iface
        for i in range(2, 10):
            setattr(fake_system, f"interface{i}_enabled", False)

        with patch.dict(sys.modules, {"modules.system": fake_system}):
            # modules.system already imported inside bw helpers via import — patch module attr
            with patch("modules.system._nodedb_fresh_position", return_value=None), patch(
                "modules.system.get_name_from_number", return_value="N55"
            ):
                # Re-bind collect to use our fake interfaces via modules.system
                import modules.system as sysmod

                sysmod.interface1_enabled = True
                sysmod.interface1 = fake_iface
                for i in range(2, 10):
                    setattr(sysmod, f"interface{i}_enabled", False)
                    setattr(sysmod, f"myNodeNum{i}", None)
                sysmod.myNodeNum1 = 1

                cands = self.bw._collect_watch_candidates(1)
                kinds = {(c["kind"], c.get("slot")) for c in cands if c["node_id"] == 55}
                self.assertIn(("home", 0), kinds)
                self.assertIn(("extra", 1), kinds)
                home = [c for c in cands if c["kind"] == "home" and c["node_id"] == 55][0]
                self.assertEqual(home["radius_km"], 6)
                self.assertEqual(home["label"], "Relais")

    def test_channel_meta_cooldown(self):
        self.bw.set_meta(self.bw.META_CHANNEL_TS, "100.0")
        self.assertEqual(self.bw.get_meta(self.bw.META_CHANNEL_TS), "100.0")

    def test_migration_adds_home_columns(self):
        """Old DB without home_* columns still works after init."""
        import sqlite3

        path = self.db
        os.remove(path)
        conn = sqlite3.connect(path)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE blitzwatch (
                node_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                radius_km INTEGER NOT NULL DEFAULT 8,
                last_alert_ts REAL NOT NULL DEFAULT 0
            )"""
        )
        c.execute(
            "INSERT INTO blitzwatch (node_id, enabled, radius_km) VALUES (1, 1, 7)"
        )
        conn.commit()
        conn.close()

        self.assertTrue(self.bw.initialize_blitzwatch_database())
        prefs = self.bw.get_node_prefs(1)
        self.assertEqual(prefs["radius_km"], 7)
        self.assertEqual(prefs["home_mode"], "gps")
        self.bw.set_home_fixed(1, 50.0, 8.0, "X")
        prefs = self.bw.get_node_prefs(1)
        self.assertEqual(prefs["home_mode"], "fixed")


if __name__ == "__main__":
    unittest.main()
