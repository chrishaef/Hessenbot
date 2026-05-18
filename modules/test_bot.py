# test_bot.py
# Unit tests for Hessenbot / EU-focused modules
import os
import sys

parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_path)

import unittest
import importlib
import pkgutil
import warnings
from modules.settings import latitudeValue, longitudeValue

warnings.filterwarnings("ignore", category=ResourceWarning)

modules_path = os.path.join(parent_path, 'modules')

CHECKALL = os.path.isfile(os.path.join(parent_path, '.checkall'))

exclude = ['test_bot', 'udp', 'system', 'log', 'gpio', 'web']

try:
    print("\nImporting Core Modules:")
    from modules.log import logger, getPrettyTime
    print("  ✔ Imported 'log'")
    lat = latitudeValue
    lon = longitudeValue
    print(f"  ✔ Location set to Latitude: {lat}, Longitude: {lon}")
    from modules.system import *
    print("  ✔ Imported 'system'")

    print("\nImporting non-excluded modules:")
    for module_name in [m.name for m in pkgutil.iter_modules([modules_path])]:
        if module_name not in exclude:
            importlib.import_module(f'modules.{module_name}')
            print(f"  ✔ Imported '{module_name}'")
except Exception as e:
    print(f"\nError importing modules: {e}")
    print("Run from repo root: python3 modules/test_bot.py")
    exit(1)


def _skip_unless_checkall():
    return unittest.skipUnless(CHECKALL, "Create .checkall in repo root for API tests")


class TestBot(unittest.TestCase):
    def test_example(self):
        self.assertEqual(1 + 1, 2)

    def test_packet_dedup_by_id(self):
        from modules import packet_dedup

        packet_dedup._seen.clear()
        packet_dedup._stats["dropped"] = 0
        packet_dedup._stats["accepted"] = 0
        pkt = {
            "from": 1234567890,
            "id": 42,
            "to": 0,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"!cmd"},
        }
        self.assertFalse(packet_dedup.should_drop_duplicate_packet(pkt))
        self.assertTrue(packet_dedup.should_drop_duplicate_packet(pkt))
        pkt2 = dict(pkt)
        pkt2["id"] = 43
        self.assertFalse(packet_dedup.should_drop_duplicate_packet(pkt2))

    def test_load_bbsdb(self):
        from modules.bbstools import load_bbsdb
        self.assertTrue(load_bbsdb())

    def test_bbs_list_messages(self):
        from modules.bbstools import bbs_list_messages
        messages = bbs_list_messages()
        self.assertIsInstance(messages, str)

    def test_initialize_checklist_database(self):
        from modules.checklist import initialize_checklist_database, process_checklist_command
        self.assertTrue(initialize_checklist_database())
        result = process_checklist_command(0, 'checklist', name="none", location="none")
        self.assertIsInstance(result, str)

    def test_initialize_inventory_database(self):
        from modules.inventory import initialize_inventory_database, process_inventory_command
        self.assertTrue(initialize_inventory_database())
        result = process_inventory_command(0, 'inventory', name="none")
        self.assertIsInstance(result, str)

    def test_init_news_sources(self):
        from modules.filemon import initNewsSources
        self.assertTrue(initNewsSources())

    def test_get_nina_alerts(self):
        from modules.globalalert import get_nina_alerts
        alerts = get_nina_alerts()
        self.assertIsInstance(alerts, str)

    def test_build_warning_messages(self):
        from modules.globalalert import build_warning_messages, WARNING_NONE_MSG
        parts = build_warning_messages(lat, lon, from_gps=True)
        self.assertIsInstance(parts, list)
        self.assertTrue(len(parts) > 0)
        self.assertIsInstance(parts[0], str)

    def test_extract_search_terms(self):
        from modules.llm import extract_search_terms
        terms = extract_search_terms("What is Python programming?")
        self.assertIsInstance(terms, list)
        self.assertTrue(len(terms) > 0)

    def test_get_moon_phase(self):
        from modules.space import get_moon
        self.assertIsInstance(get_moon(lat, lon), str)

    def test_get_sun_times(self):
        from modules.space import get_sun
        self.assertIsInstance(get_sun(lat, lon), str)

    def test_hf_band_conditions(self):
        from modules.space import hf_band_conditions
        self.assertIsInstance(hf_band_conditions(), str)

    def test_get_wikipedia_summary(self):
        from modules.wiki import get_wikipedia_summary
        self.assertIsInstance(get_wikipedia_summary("Python", location=(lat, lon)), str)

    def test_get_openskynetwork(self):
        from modules.locationdata import get_openskynetwork
        self.assertIsInstance(get_openskynetwork(lat, lon), str)

    def test_initalize_qrz_database(self):
        from modules.qrz import initalize_qrz_database
        self.assertTrue(initalize_qrz_database())

    def test_import_radio_module(self):
        import modules.radio  # noqa: F401

    def test_get_rss_feed(self):
        from modules.rss import get_rss_feed
        self.assertIsInstance(get_rss_feed(''), str)

    def test_check_callsign_match(self):
        from modules.radio import check_callsign_match
        self.assertTrue(check_callsign_match("CQ K7MHI CN87", []))
        self.assertTrue(check_callsign_match("CQ K7MHI CN87", ["K7MHI"]))
        self.assertFalse(check_callsign_match("CQ W1AW FN31", ["K7MHI"]))

    @_skip_unless_checkall()
    def test_send_ollama_query(self):
        from modules.llm import send_ollama_query
        self.assertIsInstance(send_ollama_query("Hello, Ollama!"), str)

    @_skip_unless_checkall()
    def test_get_wiki_context(self):
        from modules.llm import get_wiki_context
        self.assertIsInstance(get_wiki_context("Python programming language"), str)

    @_skip_unless_checkall()
    def test_handledxcluster(self):
        from modules.dxspot import handledxcluster
        response = handledxcluster("DX band=20m mode=SSB of=K7MHI", nodeID=0, deviceID='testdevice')
        self.assertIsInstance(response, str)

    def test_resolve_mesh_node_target(self):
        from modules.system import resolve_mesh_node_target

        nid, err = resolve_mesh_node_target("loc !00a1b2c3", 1)
        self.assertIsNone(err)
        self.assertEqual(nid, 0x00A1B2C3)
        nid, err = resolve_mesh_node_target("loc", 1, default_id=12345)
        self.assertEqual(nid, 12345)
        self.assertIsNone(err)
        nid, err = resolve_mesh_node_target("loc unknownnode", 1)
        self.assertEqual(nid, 0)
        self.assertIn("nicht", (err or "").lower())

    @_skip_unless_checkall()
    def test_where_am_i(self):
        from modules.locationdata import where_am_i
        self.assertIsInstance(where_am_i(lat, lon), str)

    @_skip_unless_checkall()
    def test_getRepeaterBook(self):
        from modules.locationdata import getRepeaterBook
        self.assertIsInstance(getRepeaterBook(lat, lon), str)

    @_skip_unless_checkall()
    def test_get_wx_meteo(self):
        from modules.wx_meteo import get_wx_meteo
        self.assertIsInstance(get_wx_meteo(lat, lon), str)

    @_skip_unless_checkall()
    def test_get_metar(self):
        from modules.metar import get_metar
        result = get_metar(lat, lon)
        self.assertIsInstance(result, str)
        self.assertIn("METAR", result)

    def test_parse_metar_icao(self):
        from modules.metar import parse_metar_icao_from_message, normalize_icao

        self.assertEqual(normalize_icao("eddf"), "EDDF")
        self.assertIsNone(normalize_icao("ED"))
        self.assertEqual(parse_metar_icao_from_message("!metar EDDF"), "EDDF")
        self.assertEqual(parse_metar_icao_from_message("metar ethf"), "ETHF")
        self.assertIsNone(parse_metar_icao_from_message("!metar"))

    def test_uv_risk_de(self):
        from modules.wx_extra import _uv_risk_de

        self.assertEqual(_uv_risk_de(2), "niedrig")
        self.assertEqual(_uv_risk_de(7), "hoch")

    @_skip_unless_checkall()
    def test_get_uv_regen_blitz(self):
        from modules.wx_extra import get_blitz, get_regen, get_uv

        for fn, tag in ((get_uv, "UV"), (get_regen, "REGEN"), (get_blitz, "BLITZ")):
            result = fn(lat, lon)
            self.assertIsInstance(result, str)
            self.assertIn(tag, result)

    def test_metar_decode_help(self):
        from modules.metar import get_metar_decode_help

        text = get_metar_decode_help()
        self.assertIn("CAVOK", text)
        self.assertIn("Q1016", text)
        self.assertIn("!metar EDDF", text)

    @_skip_unless_checkall()
    def test_get_metar_by_icao(self):
        from modules.metar import get_metar_by_icao
        result = get_metar_by_icao("EDDF")
        self.assertIsInstance(result, str)
        self.assertIn("METAR", result)
        self.assertIn("EDDF", result)

    @_skip_unless_checkall()
    def test_get_flood_openmeteo(self):
        from modules.wx_meteo import get_flood_openmeteo
        self.assertIsInstance(get_flood_openmeteo(lat, lon), str)

    @_skip_unless_checkall()
    def test_getNextSatellitePass(self):
        from modules.space import getNextSatellitePass
        self.assertIsInstance(getNextSatellitePass('25544', lat, lon), str)


if __name__ == '__main__':
    if not CHECKALL:
        print("\nNote: Extended API tests are skipped. Create '.checkall' in the repo root to enable them.\n")
    unittest.main()
