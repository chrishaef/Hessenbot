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


class FavoritesTests(unittest.TestCase):
    def test_sort_favorites_first_then_recent(self):
        rows = [
            {"num": 1, "favorite": False, "lastHeard_raw": 300},
            {"num": 2, "favorite": True, "lastHeard_raw": 100},
            {"num": 3, "favorite": True, "lastHeard_raw": 200},
            {"num": 4, "favorite": False, "lastHeard_raw": 400},
        ]
        order = [r["num"] for r in ops.sort_rows_favorites_first(rows)]
        self.assertEqual(order, [3, 2, 4, 1])


def _fake_sm(nodes, local=None):
    import types

    by_num = {n["num"]: n for n in nodes.values()}
    iface = types.SimpleNamespace(nodes=nodes, nodesByNum=by_num)
    local = local or mock.MagicMock()
    iface.getNode = mock.MagicMock(return_value=local)
    sm = types.SimpleNamespace(interface1=iface, interface1_enabled=True, myNodeNum1=999)
    return sm, iface, local


class RadioFavoriteTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {
            "a": {"num": 100, "user": {"shortName": "AA"}, "lastHeard": 50},
            "b": {"num": 200, "user": {"shortName": "BB"}, "lastHeard": 60, "isFavorite": True},
        }
        self.sm, self.iface, self.local = _fake_sm(self.nodes)

    def _call(self, num, value):
        with mock.patch.object(ops, "_system_mod", return_value=self.sm):
            return ops.set_node_favorite_on_radio(1, num, value)

    def test_set_and_clear_use_admin_calls_and_update_cache(self):
        ok, _ = self._call(100, True)
        self.assertTrue(ok)
        self.local.setFavorite.assert_called_once_with(100)
        self.assertTrue(self.nodes["a"]["isFavorite"])
        ok, _ = self._call(200, False)
        self.assertTrue(ok)
        self.local.removeFavorite.assert_called_once_with(200)
        self.assertNotIn("isFavorite", self.nodes["b"])
        self.assertNotIn("isFavorite", self.iface.nodesByNum[200])

    def test_self_node_rejected(self):
        ok, _ = self._call(999, True)
        self.assertFalse(ok)
        self.local.setFavorite.assert_not_called()

    def test_radio_error_keeps_cache(self):
        self.local.setFavorite.side_effect = RuntimeError("boom")
        ok, msg = self._call(100, True)
        self.assertFalse(ok)
        self.assertIn("boom", msg)
        self.assertNotIn("isFavorite", self.nodes["a"])

    def test_no_interface(self):
        self.sm.interface1 = None
        ok, _ = self._call(100, True)
        self.assertFalse(ok)

    def test_role_hint(self):
        import types

        def iface(role, loaded=True):
            cfg = types.SimpleNamespace(
                HasField=lambda name: loaded, device=types.SimpleNamespace(role=role)
            )
            return types.SimpleNamespace(localNode=types.SimpleNamespace(localConfig=cfg))

        self.assertIsNone(ops.local_device_role_hint(iface(12)))
        self.assertIn("CLIENT_BASE", ops.local_device_role_hint(iface(0)))
        self.assertIsNone(ops.local_device_role_hint(iface(0, loaded=False)))
        self.assertIsNone(ops.local_device_role_hint(None))


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
            "b": {"num": 200, "user": {"shortName": "BB", "longName": "Beta"}, "lastHeard": 60, "hopsAway": 0, "isFavorite": True},
            "c": {"num": 300, "user": {"shortName": "CC", "longName": "Gamma"}},
        }
        sm = types.SimpleNamespace(
            interface1=types.SimpleNamespace(nodes=nodes),
            interface1_enabled=True,
            myNodeNum1=999,
        )
        ls.record_rx({"from": 100, "transport_mechanism": "TRANSPORT_MQTT"}, 1, now=10.0)
        with mock.patch.object(ops, "_system_mod", return_value=sm), \
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

        self.re = re
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
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
        self.sm, self.iface, self.local = _fake_sm(nodes)
        for p in (
            mock.patch.object(ops, "_system_mod", return_value=self.sm),
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

    def test_toggle_requires_csrf_and_writes_to_node(self):
        resp = self.client.post("/nodes/favorite", data={"iface_id": "1", "node_num": "200", "favorite": "1"})
        self.assertEqual(resp.status_code, 302)
        self.local.setFavorite.assert_not_called()

        token, _ = self._token()
        resp = self.client.post(
            "/nodes/favorite",
            data={"iface_id": "1", "node_num": "200", "favorite": "1", "csrf_token": token},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("#node-200"))
        self.local.setFavorite.assert_called_once_with(200)

        _, page = self._token()
        self.assertLess(page.index('id="node-200"'), page.index('id="node-100"'))
        self.assertIn("Hops", page)

        self.client.post(
            "/nodes/favorite",
            data={"iface_id": "1", "node_num": "200", "favorite": "0", "csrf_token": token},
        )
        self.local.removeFavorite.assert_called_once_with(200)

    def test_unauthenticated_post_rejected(self):
        anon = self.client.application.test_client()
        resp = anon.post("/nodes/favorite", data={"iface_id": "1", "node_num": "100", "favorite": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin", resp.headers["Location"])
        self.local.setFavorite.assert_not_called()


if __name__ == "__main__":
    unittest.main()
