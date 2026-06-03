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

    def test_dm_chunk_wants_delivery_ack(self):
        from modules.system import dm_chunk_wants_delivery_ack

        self.assertFalse(dm_chunk_wants_delivery_ack(0, 0, want_ack_all=False))
        self.assertTrue(dm_chunk_wants_delivery_ack(0, 1, want_ack_all=True))
        self.assertTrue(dm_chunk_wants_delivery_ack(12345, 0, want_ack_on_dm=True))
        self.assertFalse(dm_chunk_wants_delivery_ack(12345, 1, want_ack_on_dm=True))
        self.assertFalse(dm_chunk_wants_delivery_ack(12345, 0, want_ack_on_dm=False))

    def test_detect_missing_cmd_bang(self):
        from unittest.mock import patch
        from modules.system import detect_missing_cmd_bang

        traps = ("ping", "wx", "cmd", "bbspost")
        with patch("modules.system.cmdBang", True), patch("modules.system.trap_list", traps):
            self.assertEqual(detect_missing_cmd_bang("ping"), "ping")
            self.assertEqual(detect_missing_cmd_bang("wx"), "wx")
            self.assertEqual(detect_missing_cmd_bang("cmd?"), "cmd")
            self.assertEqual(detect_missing_cmd_bang("Ping"), "Ping")
            self.assertIsNone(detect_missing_cmd_bang("!ping"))
            self.assertIsNone(detect_missing_cmd_bang("!wx test"))
            self.assertIsNone(detect_missing_cmd_bang("hallo"))
            self.assertIsNone(detect_missing_cmd_bang(""))
        with patch("modules.system.cmdBang", False), patch("modules.system.trap_list", traps):
            self.assertIsNone(detect_missing_cmd_bang("ping"))

    def test_missing_cmd_bang_hint_text(self):
        from modules.locale_de import missing_cmd_bang_hint

        hint = missing_cmd_bang_hint("ping")
        self.assertIn("!ping", hint)
        self.assertIn("!cmd", hint)

    def test_collect_messages_reads_rotated_meshbot_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        line_y = (
            "2026-05-30 23:56:03,123 |     INFO | Device:1 Channel:1|#1MeshHessen "
            "ReceivedChannel: gestern abends From: Chris\n"
        )
        line_t = (
            "2026-05-31 12:42:00,456 |     INFO | Device:1 Channel:1|#1MeshHessen "
            "Ignoring Message: heute mittag From: Pete\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meshbot.log.2026-05-30"), "w", encoding="utf-8") as f:
                f.write(line_y)
            with open(os.path.join(td, "meshbot.log"), "w", encoding="utf-8") as f:
                f.write(line_t)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=80)
        self.assertIsNone(err)
        texts = [m.get("text", "") for m in msgs]
        self.assertIn("gestern abends", texts)
        self.assertIn("heute mittag", texts)
        self.assertEqual(msgs[-1].get("text"), "heute mittag")

    def test_collect_messages_finds_dms_in_busy_channel_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        channel_noise = (
            "2026-05-31 12:00:00,100 |     INFO | Device:1 Channel:1|#1MeshHessen "
            "Ignoring Message: chatter From: Node{i}\n"
        )
        dm_in = (
            "2026-05-31 12:45:00,200 |     INFO | Device:1 Channel:0 "
            "Received DM: !ping From: Chris\n"
        )
        dm_out = (
            "2026-05-31 12:45:01,300 |     INFO | Device:1 req.ACK Sending DM: "
            "pong To: Chris\n"
        )
        dm_missing = (
            "2026-05-31 12:46:00,400 |     INFO | Device:1 Channel:0 "
            "Received DM (missing !): ping From: Chris\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                for i in range(3000):
                    f.write(channel_noise.format(i=i))
                f.write(dm_in)
                f.write(dm_out)
                f.write(dm_missing)
            msgs, err = collect_messages(td, kind="dm", limit=80)
        self.assertIsNone(err)
        texts = [m.get("text", "") for m in msgs]
        self.assertIn("!ping", texts)
        self.assertIn("pong", texts)
        self.assertIn("ping", texts)

    def test_dm_peer_id_name_fallback(self):
        from modules.admin_mesh_chat import collect_messages, dm_peer_id

        self.assertEqual(dm_peer_id({"long": "Chris"}), "n:chris")
        self.assertEqual(dm_peer_id({"id": "42424242"}), "42424242")
        self.assertEqual(dm_peer_id({"hex": "!0284a8c8"}), "!0284a8c8")

        import os
        import tempfile

        line = (
            "2026-05-31 12:45:00,200 |     INFO | Device:1 Channel:0 "
            "Received DM: !ping From: Chris\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(line)
            msgs, err = collect_messages(td, kind="dm", limit=10)
        self.assertIsNone(err)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(dm_peer_id(msgs[0]), "n:chris")

    def test_channel_feed_orders_in_before_out_same_second(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        lines = (
            "2026-06-01 20:57:25,100 |     INFO | Device:1 Channel:1|Mesh Hessen "
            "ReceivedChannel: test From: Chris\n"
            "2026-06-01 20:57:25,200 |     INFO | Device:1 Channel:1|Mesh Hessen "
            "SendingChannel: Chris [!deadbeef] QSL reply\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(lines)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=20)
        self.assertIsNone(err)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].get("dir"), "in")
        self.assertEqual(msgs[0].get("text"), "test")
        self.assertEqual(msgs[1].get("dir"), "out")

    def test_channel_feed_dedup_meshbot_and_messages_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        mesh = (
            "2026-06-01 21:00:00,100 |     INFO | Device:1 Channel:1|Mesh Hessen "
            "Ignoring Message: Hallo Welt From: TaunusMesh\n"
        )
        msglog = (
            "2026-06-01 21:00:00,150 | Device:1 Channel:1|Mesh Hessen | "
            "TaunusMesh | meshhessen.de | Hallo Welt\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meshbot.log"), "w", encoding="utf-8") as f:
                f.write(mesh)
            with open(os.path.join(td, "messages.log"), "w", encoding="utf-8") as f:
                f.write(msglog)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=20)
        self.assertIsNone(err)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].get("text"), "Hallo Welt")

    def test_channel_feed_dedup_received_channel_and_delayed_messages_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        mesh = (
            "2026-06-01 21:16:46,100 |     INFO | Device:1 Channel:1|Mesh Hessen "
            "ReceivedChannel: Test From: Chris\n"
            "2026-06-01 21:16:46,200 |     INFO | Device:1 Channel:1|Mesh Hessen "
            "SendingChannel: Chris [!deadbeef] QSL reply\n"
        )
        msglog = (
            "2026-06-01 21:16:48,150 | Device:1 Channel:1|Mesh Hessen | "
            "Chris | Test\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meshbot.log"), "w", encoding="utf-8") as f:
                f.write(mesh)
            with open(os.path.join(td, "messages.log"), "w", encoding="utf-8") as f:
                f.write(msglog)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=20)
        self.assertIsNone(err)
        incoming = [m for m in msgs if m.get("dir") == "in"]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].get("text"), "Test")
        self.assertEqual(len(msgs), 2)

    def test_resolve_dest_node_numeric_and_hex(self):
        from modules.admin_mesh_chat import resolve_dest_node

        num, err = resolve_dest_node("42424242", 1)
        self.assertIsNone(err)
        self.assertEqual(num, 42424242)

        num, err = resolve_dest_node("!0284a8c8", 1)
        self.assertIsNone(err)
        self.assertEqual(num, 0x0284A8C8)

        num, err = resolve_dest_node("", 1)
        self.assertIsNone(num)
        self.assertIn("Empfänger", err or "")

    def test_channel_feed_dedup_realm_prefix_and_short_name(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        body = (
            "Man soll auch keine Pizza in den Teilchenbeschleuniger werfen. "
            "Trotzdem musste erst ein Schild aufgestellt werden."
        )
        mesh = (
            "2026-06-03 21:30:57,100 |     INFO | Device:1 Channel:1|Mesh Hessen "
            f"Ignoring Message: {body} From: TaunusMesh\n"
        )
        msglog = (
            "2026-06-03 21:30:57,150 | Device:1 Channel:1|Mesh Hessen | "
            f"TaunusMesh | meshhessen.de | {body}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meshbot.log"), "w", encoding="utf-8") as f:
                f.write(mesh)
            with open(os.path.join(td, "messages.log"), "w", encoding="utf-8") as f:
                f.write(msglog)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=20)
        self.assertIsNone(err)
        incoming = [m for m in msgs if m.get("dir") == "in"]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].get("text"), body)

    def test_dm_feed_dedup_meshbot_and_messages_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        mesh = (
            "2026-06-01 12:00:00,100 |     INFO | Device:1 Channel:0 "
            "Received DM: !ping From: Chris mobil 📲 *meshhessen.de*\n"
        )
        msglog = (
            "2026-06-01 12:00:02,150 | Device:1 Channel:0 | "
            "Chris 🌐🛰️ *meshhessen.de* | DM | ping\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meshbot.log"), "w", encoding="utf-8") as f:
                f.write(mesh)
            with open(os.path.join(td, "messages.log"), "w", encoding="utf-8") as f:
                f.write(msglog)
            msgs, err = collect_messages(td, kind="dm", limit=20)
        self.assertIsNone(err)
        incoming = [m for m in msgs if m.get("dir") == "in"]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].get("text"), "!ping")

    def test_dm_feed_dedup_outgoing_web_and_bot_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import (
            _RING,
            _RING_LOCK,
            _merge_events,
            collect_messages,
            record_optimistic,
        )

        mesh = (
            "2026-06-01 12:01:00,200 |     INFO | Device:1 req.ACK "
            "Sending DM: Hallo zurück To: Chris mobil 📲 *meshhessen.de*\n"
        )
        with _RING_LOCK:
            _RING.clear()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(mesh)
            msgs, err = collect_messages(td, kind="dm", limit=20)
        self.assertIsNone(err)
        record_optimistic(
            {
                "time": "2026-06-01T12:01:00",
                "time_short": "12:01:00",
                "dir": "out",
                "kind": "dm",
                "channel": 0,
                "channel_label": "DM",
                "device": 1,
                "text": "Hallo zurück",
                "id": "1127983492",
                "short": "Web-Admin",
                "long": "Hessenbot Web-Admin",
                "source": "web",
            }
        )
        merged = _merge_events(msgs, [])
        outgoing = [m for m in merged if m.get("dir") == "out"]
        self.assertEqual(len(outgoing), 1)
        with _RING_LOCK:
            _RING.clear()

    def test_channel_feed_dedup_outgoing_web_and_bot_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import (
            _RING,
            _RING_LOCK,
            _merge_events,
            collect_messages,
            record_optimistic,
        )

        mesh = (
            "2026-06-01 21:30:00,200 |     INFO | Device:1 Channel:1|Mesh Hessen "
            "req.ACK SendingChannel: Hallo vom Admin Panel\n"
        )
        with _RING_LOCK:
            _RING.clear()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(mesh)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=20)
        self.assertIsNone(err)
        record_optimistic(
            {
                "time": "2026-06-01T21:30:00",
                "time_short": "21:30:00",
                "dir": "out",
                "kind": "channel",
                "channel": 1,
                "channel_label": "Mesh Hessen",
                "device": 1,
                "text": "Hallo vom Admin Panel",
                "short": "Web-Admin",
                "long": "Hessenbot Web-Admin",
                "source": "web",
            }
        )
        merged = _merge_events(msgs, [])
        outgoing = [m for m in merged if m.get("dir") == "out"]
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0].get("short"), "Web-Admin")
        self.assertEqual(outgoing[0].get("source"), "web")
        with _RING_LOCK:
            _RING.clear()

    def test_public_dashboard_dedup_meshbot_and_messages_log(self):
        import os
        import tempfile
        from modules.web_dashboard import parse_meshbot_log

        body = "Oh aehm. Temporale Verzerrung in der chrona ordina."
        mesh = (
            "2026-06-03 22:22:27,100 |     INFO | Device:1 Channel:1|Mesh Hessen "
            f"Ignoring Message: {body} From: TaunusMesh\n"
        )
        msglog = (
            "2026-06-03 22:22:27,150 | Device:1 Channel:1|Mesh Hessen | "
            f"TaunusMesh | meshhessen.de | {body}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meshbot.log"), "w", encoding="utf-8") as f:
                f.write(mesh)
            with open(os.path.join(td, "messages.log"), "w", encoding="utf-8") as f:
                f.write(msglog)
            stats = parse_meshbot_log(os.path.join(td, "meshbot.log"))
        incoming = [
            m
            for m in stats.get("recent_messages") or []
            if m.get("kind") == "channel" and m.get("dir") == "in"
        ]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].get("text"), body)

    def test_collect_messages_finds_bot_sends_in_busy_channel_log(self):
        import os
        import tempfile
        from modules.admin_mesh_chat import collect_messages

        noise = (
            "2026-05-31 12:00:00,100 |     INFO | Device:1 Channel:1|#1MeshHessen "
            "Ignoring Message: chatter From: Node{i}\n"
        )
        bot_reply = (
            "2026-05-31 12:45:01,300 |     INFO | Device:1 Channel:1|#1MeshHessen "
            "req.ACK SendingChannel: !ping Antwort From Bot\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                for i in range(5000):
                    f.write(noise.format(i=i))
                f.write(bot_reply)
            msgs, err = collect_messages(td, kind="channel", channel=1, limit=80)
        self.assertIsNone(err)
        out_texts = [m.get("text", "") for m in msgs if m.get("dir") == "out"]
        self.assertTrue(any("Antwort" in t for t in out_texts), out_texts)

    def test_packet_dedup_by_id(self):
        from modules import packet_dedup

        packet_dedup._seen.clear()
        packet_dedup._enrichment.clear()
        packet_dedup._stats["dropped"] = 0
        packet_dedup._stats["accepted"] = 0
        packet_dedup._stats["hop_enriched_wait"] = 0
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

    def test_wait_for_hop_enrichment_merges_late_udp(self):
        import threading
        import time

        import modules.settings as st
        from modules import packet_dedup

        st.packet_dedup_hop_wait_ms = 200
        packet_dedup._seen.clear()
        packet_dedup._enrichment.clear()
        packet_dedup._stats["dropped"] = 0
        packet_dedup._stats["accepted"] = 0
        packet_dedup._stats["hop_enriched_wait"] = 0

        mqtt_pkt = {
            "from": 1,
            "id": 99,
            "to": 2,
            "hopStart": 3,
            "hopLimit": 3,
            "hopsAway": 0,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"!ping", "viaMqtt": True},
            "transport_mechanism": "mqtt",
        }
        udp_pkt = {
            "from": 1,
            "id": 99,
            "to": 2,
            "hopStart": 5,
            "hopLimit": 3,
            "hopsAway": 0,
            "rxSnr": 12.0,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"!ping", "viaMqtt": False},
            "transport_mechanism": "udp",
        }
        self.assertFalse(packet_dedup.should_drop_duplicate_packet(mqtt_pkt))

        def late_udp():
            time.sleep(0.05)
            packet_dedup.should_drop_duplicate_packet(udp_pkt)

        t = threading.Thread(target=late_udp)
        t.start()
        merged = packet_dedup.wait_for_hop_enrichment(mqtt_pkt)
        t.join()

        self.assertTrue(merged)
        self.assertEqual(mqtt_pkt["hopStart"], 5)
        self.assertEqual(mqtt_pkt["rxSnr"], 12.0)

    def test_wait_skipped_when_hop_metadata_rich(self):
        import time

        import modules.settings as st
        from modules import packet_dedup

        st.packet_dedup_hop_wait_ms = 200
        packet_dedup._seen.clear()
        packet_dedup._enrichment.clear()

        pkt = {
            "from": 2,
            "id": 100,
            "to": 3,
            "hopStart": 5,
            "hopLimit": 3,
            "hopsAway": 0,
            "decoded": {"portnum": "TEXT_MESSAGE_APP", "payload": b"!ping"},
        }
        t0 = time.time()
        self.assertFalse(packet_dedup.wait_for_hop_enrichment(pkt))
        self.assertLess(time.time() - t0, 0.05)

    def test_faq_pki_log_scan(self):
        import os
        import tempfile

        from modules.web_faq_pki_check import scan_pki_log_for_node

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "2025-01-01 | WARNING | System: PKI Routing Error "
                    "Reason:PKI_UNKNOWN_PUBKEY RequesterNode:424242\n"
                )
            r = scan_pki_log_for_node("424242", td)
            self.assertTrue(r["ok"])
            self.assertEqual(r["summary"], "problems_found")

    def test_dm_delivery_stats_24h_parse(self):
        import os
        import tempfile
        from datetime import datetime

        from modules.dm_delivery_stats import parse_dm_delivery_stats_24h

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    f"{ts},000 | INFO | System: DM delivery confirmed Device:1 "
                    "To:x Node:111 RequestId:1\n"
                    f"{ts},000 | WARNING | System: DM delivery failed (PKI) Device:1 "
                    "To:x Node:222 Reason:PKI_UNKNOWN_PUBKEY RequestId:2\n"
                    f"{ts},000 | WARNING | System: DM delivery failed Device:1 "
                    "To:x Node:333 Reason:TIMEOUT RequestId:3\n"
                )
            r = parse_dm_delivery_stats_24h(td)
            self.assertEqual(r["confirmed"], 1)
            self.assertEqual(r["failed_pki"], 1)
            self.assertEqual(r["failed_other"], 1)

    def test_dm_delivery_fail_streak_alert(self):
        from modules import dm_delivery_stats as dds

        dds._fail_streak.clear()
        dds._warned_pairs.clear()
        dds.record_dm_delivery_outcome(1, 424242, success=False, is_pki=True)
        dds.record_dm_delivery_outcome(1, 424242, success=False, is_pki=True)
        self.assertNotIn((1, 424242), dds._warned_pairs)
        dds.record_dm_delivery_outcome(1, 424242, success=False, is_pki=True)
        self.assertIn((1, 424242), dds._warned_pairs)
        dds.record_dm_delivery_outcome(1, 424242, success=True)
        self.assertNotIn((1, 424242), dds._fail_streak)

    def test_faq_pki_log_scan_dm_delivery(self):
        import os
        import tempfile

        from modules.web_faq_pki_check import scan_pki_log_for_node

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "meshbot.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(
                    "2025-01-01 | WARNING | System: DM delivery failed (PKI) Device:1 "
                    "To:!0192a3b4 Node:424242 Reason:PKI_UNKNOWN_PUBKEY RequestId:99\n"
                )
            r = scan_pki_log_for_node("424242", td)
            self.assertTrue(r["ok"])
            self.assertEqual(r["summary"], "problems_found")
            self.assertTrue(any("DM delivery" in h["reason"] for h in r["hits"]))

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
