# Unit tests: Admin NodeDB favorites, hops and MQTT/Funk transport column.
# Run: python -m pytest modules/test_node_favorites_hops.py -q
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules import admin_web_ops as ops
from modules import link_status as ls
from modules import node_favorites as nf


class FavoritesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "data", "node_favorites.json")
        patcher = mock.patch.object(nf, "_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        nf.reset_for_tests()

    def test_roundtrip_persists_across_reload(self):
        self.assertTrue(nf.set_favorite(123, True))
        self.assertTrue(nf.set_favorite(456, True))
        self.assertTrue(nf.set_favorite(123, False))
        nf.reset_for_tests()
        self.assertEqual(nf.list_favorites(), [456])
        self.assertTrue(nf.is_favorite(456))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"favorites": [456]})

    def test_invalid_numbers_rejected(self):
        self.assertFalse(nf.set_favorite(0, True))
        self.assertFalse(nf.set_favorite("abc", True))
        self.assertEqual(nf.list_favorites(), [])

    def test_empty_and_corrupt_file_are_tolerated(self):
        os.makedirs(os.path.dirname(self.path))
        open(self.path, "w").close()
        self.assertEqual(nf.list_favorites(), [])
        nf.reset_for_tests()
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(nf.list_favorites(), [])
        self.assertTrue(nf.set_favorite(7, True))

    def test_sort_favorites_first_then_recent(self):
        rows = [
            {"num": 1, "favorite": False, "lastHeard_raw": 300},
            {"num": 2, "favorite": True, "lastHeard_raw": 100},
            {"num": 3, "favorite": True, "lastHeard_raw": 200},
            {"num": 4, "favorite": False, "lastHeard_raw": 400},
        ]
        order = [r["num"] for r in ops.sort_rows_favorites_first(rows)]
        self.assertEqual(order, [3, 2, 4, 1])


class TransportTests(unittest.TestCase):
    def setUp(self):
        ls.reset_for_tests()

    def test_record_rx_tracks_last_transport_per_node(self):
        ls.record_rx({"from": 10, "transport_mechanism": "TRANSPORT_MQTT"}, 1, now=100.0)
        self.assertEqual(ls.last_node_transport(1, 10), (True, 100.0))
        ls.record_rx({"from": 10, "transport_mechanism": "TRANSPORT_LORA"}, 1, now=200.0)
        self.assertEqual(ls.last_node_transport(1, 10), (False, 200.0))
        self.assertIsNone(ls.last_node_transport(2, 10))
        self.assertIsNone(ls.last_node_transport(1, 99))

    def test_viamqtt_flag_without_transport_mechanism(self):
        ls.record_rx({"from": 11, "decoded": {"viaMqtt": True}}, 1, now=1.0)
        self.assertTrue(ls.last_node_transport(1, 11)[0])

    def test_transport_map_is_bounded(self):
        with mock.patch.object(ls, "NODE_TRANSPORT_MAX", 3):
            for i in range(1, 7):
                ls.record_rx({"from": i}, 1, now=float(i))
        self.assertIsNone(ls.last_node_transport(1, 1))
        self.assertIsNotNone(ls.last_node_transport(1, 6))

    def test_resolve_transport_priority(self):
        node = {"lastHeard": 5}
        self.assertEqual(ops.resolve_node_transport((True, 1.0), node), ("mqtt", "live"))
        self.assertEqual(ops.resolve_node_transport((False, 1.0), {"viaMqtt": True}), ("radio", "live"))
        self.assertEqual(ops.resolve_node_transport(None, {"viaMqtt": True}), ("mqtt", "nodeinfo"))
        self.assertEqual(ops.resolve_node_transport(None, node), ("radio", "nodeinfo"))
        self.assertEqual(ops.resolve_node_transport(None, {}), (None, ""))


class HopsTests(unittest.TestCase):
    def test_positive_hopsaway(self):
        self.assertEqual(ops.resolve_node_hops({"hopsAway": 3}, "mqtt"), (3, "nodeinfo"))

    def test_zero_is_direct_only_for_radio(self):
        node = {"hopsAway": 0, "lastHeard": 9}
        self.assertEqual(ops.resolve_node_hops(node, "radio"), (0, "nodeinfo"))
        self.assertEqual(ops.resolve_node_hops(node, "mqtt"), (None, ""))
        self.assertEqual(ops.resolve_node_hops({"hopsAway": 0}, "radio"), (None, ""))

    def test_persistent_fallback_and_unknown(self):
        self.assertEqual(ops.resolve_node_hops({}, "mqtt", 2), (2, "nodedb"))
        self.assertEqual(ops.resolve_node_hops({"hopsAway": 0, "lastHeard": 1}, "mqtt", 2), (2, "nodedb"))
        self.assertEqual(ops.resolve_node_hops({}, None, 0), (None, ""))

    def test_self_has_no_hops(self):
        self.assertEqual(ops.resolve_node_hops({"hopsAway": 2}, "radio", 3, is_self=True), (None, ""))


class RowsTests(unittest.TestCase):
    def setUp(self):
        ls.reset_for_tests()

    def test_list_node_rows_fields_and_search(self):
        import types

        nodes = {
            "a": {"num": 100, "user": {"shortName": "AA", "longName": "Alpha"}, "lastHeard": 50, "hopsAway": 2},
            "b": {"num": 200, "user": {"shortName": "BB", "longName": "Beta"}, "lastHeard": 60, "hopsAway": 0},
            "c": {"num": 300, "user": {"shortName": "CC", "longName": "Gamma"}},
        }
        sm = types.SimpleNamespace(
            interface1=types.SimpleNamespace(nodes=nodes),
            interface1_enabled=True,
            myNodeNum1=999,
        )
        ls.record_rx({"from": 100, "transport_mechanism": "TRANSPORT_MQTT"}, 1, now=10.0)
        with mock.patch.object(ops, "_system_mod", return_value=sm), \
                mock.patch.object(nf, "favorites_set", return_value={200}), \
                mock.patch.object(ops, "_map_position_for_node", return_value=(False, None, None)), \
                mock.patch.object(ops, "_enrich_blitzwatch_rows"):
            err, rows = ops.list_node_rows(1)
        self.assertIsNone(err)
        by = {r["num"]: r for r in rows}
        self.assertEqual((by[100]["transport"], by[100]["hops"]), ("mqtt", 2))
        self.assertEqual((by[200]["transport"], by[200]["hops"]), ("radio", 0))
        self.assertTrue(by[200]["favorite"])
        self.assertIsNone(by[300]["transport"])
        self.assertIsNone(by[300]["hops"])
        self.assertIn("—", by[300]["transport_html"])
        self.assertIn("MQTT", by[100]["transport_html"])
        self.assertIn("Funk", by[200]["transport_html"])
        self.assertIn("Direkt", by[200]["hops_html"])
        text = ops.nodedb_row_search_text(by[200])
        self.assertIn("favorit", text)
        self.assertIn("funk", text)


class FavoriteRouteTests(unittest.TestCase):
    def setUp(self):
        import re
        import types

        self.re = re
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "node_favorites.json")
        for p in (
            mock.patch.object(nf, "_path", return_value=path),
        ):
            p.start()
            self.addCleanup(p.stop)
        nf.reset_for_tests()
        ls.reset_for_tests()
        from modules.admin_web import create_app

        app = create_app(
            alert_path=os.path.join(self.tmp.name, "alert.txt"),
            news_path=os.path.join(self.tmp.name, "news.txt"),
            log_dir=self.tmp.name,
            admin_username="u",
            admin_password="p",
            secret_key="test-secret",
        )
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.client.post("/admin", data={"username": "u", "password": "p"})
        nodes = {
            "a": {"num": 100, "user": {"shortName": "AA", "longName": "Alpha"}, "lastHeard": 50, "hopsAway": 1},
            "b": {"num": 200, "user": {"shortName": "BB", "longName": "Beta"}, "lastHeard": 60},
        }
        sm = types.SimpleNamespace(
            interface1=types.SimpleNamespace(nodes=nodes), interface1_enabled=True, myNodeNum1=999
        )
        for p in (
            mock.patch.object(ops, "_system_mod", return_value=sm),
            mock.patch.object(ops, "_map_position_for_node", return_value=(False, None, None)),
            mock.patch.object(ops, "_enrich_blitzwatch_rows"),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _token(self):
        html_text = self.client.get("/nodes").get_data(as_text=True)
        m = self.re.search(r'name="csrf_token" value="([^"]+)"', html_text)
        self.assertIsNotNone(m)
        return m.group(1), html_text

    def test_toggle_requires_csrf_and_persists(self):
        resp = self.client.post("/nodes/favorite", data={"iface_id": "1", "node_num": "100", "favorite": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(nf.list_favorites(), [])

        token, _ = self._token()
        resp = self.client.post(
            "/nodes/favorite",
            data={"iface_id": "1", "node_num": "100", "favorite": "1", "csrf_token": token},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("#node-100"))
        self.assertEqual(nf.list_favorites(), [100])

        _, page = self._token()
        self.assertLess(page.index('id="node-100"'), page.index('id="node-200"'))
        self.assertIn("Hops", page)

        self.client.post(
            "/nodes/favorite",
            data={"iface_id": "1", "node_num": "100", "favorite": "0", "csrf_token": token},
        )
        self.assertEqual(nf.list_favorites(), [])

    def test_unauthenticated_post_rejected(self):
        anon = self.client.application.test_client()
        resp = anon.post("/nodes/favorite", data={"iface_id": "1", "node_num": "100", "favorite": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin", resp.headers["Location"])
        self.assertEqual(nf.list_favorites(), [])


if __name__ == "__main__":
    unittest.main()
