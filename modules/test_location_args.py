# Lightweight unit tests for place/coord/grid message args (avoids full system/radio init).
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_path)

# Stub optional deps missing in bare environments so locationdata imports cleanly.
for _name in ("maidenhead", "bs4", "geopy", "geopy.geocoders"):
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        if _name == "geopy.geocoders":
            _mod.Nominatim = MagicMock()
        if _name == "maidenhead":
            _mod.to_maiden = MagicMock(return_value="JO40")
            _mod.to_location = MagicMock(return_value=(50.020833, 8.041667))
        sys.modules[_name] = _mod
if "geopy" in sys.modules:
    sys.modules["geopy"].geocoders = sys.modules["geopy.geocoders"]


class TestLocationArgs(unittest.TestCase):
    def test_parse_lat_lon_from_text(self):
        from modules.locationdata import parse_lat_lon_from_text

        self.assertEqual(parse_lat_lon_from_text("50.34 8.76"), (50.34, 8.76))
        self.assertEqual(parse_lat_lon_from_text("50.34,8.76"), (50.34, 8.76))
        self.assertEqual(parse_lat_lon_from_text("50.34, 8.76"), (50.34, 8.76))
        self.assertEqual(parse_lat_lon_from_text("50,34 8,76"), (50.34, 8.76))
        self.assertIsNone(parse_lat_lon_from_text(""))
        self.assertIsNone(parse_lat_lon_from_text("Friedberg"))
        self.assertIsNone(parse_lat_lon_from_text("91 8.76"))

    def test_parse_maidenhead_from_text(self):
        from modules.locationdata import parse_maidenhead_from_text

        hit = parse_maidenhead_from_text("JO40AA")
        self.assertIsNotNone(hit)
        lat, lon, label = hit
        self.assertEqual(label, "JO40AA")
        self.assertAlmostEqual(lat, 50.020833, places=4)
        self.assertAlmostEqual(lon, 8.041667, places=4)

        hit4 = parse_maidenhead_from_text("jo40")
        self.assertIsNotNone(hit4)
        self.assertEqual(hit4[2], "JO40")

        self.assertIsNotNone(parse_maidenhead_from_text("grid:JO40AA"))
        self.assertIsNone(parse_maidenhead_from_text("Friedberg"))
        self.assertIsNone(parse_maidenhead_from_text("JO"))
        self.assertIsNone(parse_maidenhead_from_text("ZZ99AA"))

    def test_extract_location_arg(self):
        from modules.locationdata import extract_location_arg

        self.assertEqual(extract_location_arg("!wx Friedberg", ("wx",)), "Friedberg")
        self.assertEqual(extract_location_arg("!blitz 50.34 8.76", ("blitz",)), "50.34 8.76")
        self.assertEqual(extract_location_arg("!wx JO40AA", ("wx",)), "JO40AA")
        self.assertEqual(
            extract_location_arg("!satpass 25544 Frankfurt", ("satpass",), skip_numeric=True),
            "Frankfurt",
        )
        self.assertEqual(extract_location_arg("!wx", ("wx",)), "")
        self.assertEqual(extract_location_arg("wx?", ("wx",)), "")

    def test_resolve_message_location_coords_and_fallback(self):
        from modules.locationdata import resolve_message_location

        lat_r, lon_r, source, label = resolve_message_location(
            "!wx 50.34 8.76", 123, 1, command_tokens=("wx",)
        )
        self.assertEqual(source, "arg-coords")
        self.assertAlmostEqual(lat_r, 50.34)
        self.assertAlmostEqual(lon_r, 8.76)
        self.assertIn("50.34", label)

        lat_r, lon_r, source, label = resolve_message_location(
            "!wx JO40AA", 123, 1, command_tokens=("wx",)
        )
        self.assertEqual(source, "arg-grid")
        self.assertEqual(label, "JO40AA")
        self.assertAlmostEqual(lat_r, 50.020833, places=4)

        fake_system = types.ModuleType("modules.system")
        fake_system.get_node_location_with_source = lambda *a, **k: [50.1, 8.2, True]
        with patch.dict(sys.modules, {"modules.system": fake_system}):
            lat_r, lon_r, source, label = resolve_message_location(
                "!wx", 123, 1, command_tokens=("wx",)
            )
            self.assertEqual(source, "gps")
            self.assertEqual(lat_r, 50.1)
            self.assertEqual(label, "")

        with patch("modules.locationdata.geocode_place_name", return_value=None):
            lat_r, lon_r, source, label = resolve_message_location(
                "!blitz NirgendwoXYZ123", 123, 1, command_tokens=("blitz",)
            )
            self.assertEqual(source, "error")
            self.assertIsNone(lat_r)
            self.assertIn("nicht gefunden", label)

        with patch(
            "modules.locationdata.geocode_place_name",
            return_value=(50.33, 8.75, "Friedberg, Hessen"),
        ):
            lat_r, lon_r, source, label = resolve_message_location(
                "!blitz Friedberg", 123, 1, command_tokens=("blitz",)
            )
            self.assertEqual(source, "arg-place")
            self.assertEqual(label, "Friedberg, Hessen")
            self.assertAlmostEqual(lat_r, 50.33)


if __name__ == "__main__":
    unittest.main()
