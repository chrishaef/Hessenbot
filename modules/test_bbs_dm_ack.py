#!/usr/bin/env python3
# Tests für BBS-DM Nutzer-Lesebestätigung (Issue #9) — ohne Radio.
# Run: python -m pytest modules/test_bbs_dm_ack.py -q
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class BbsDmAckTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        os.makedirs("data", exist_ok=True)

        import modules.bbstools as bbs

        self.bbs = bbs
        self.bbs.bbs_dm = [self.bbs.make_placeholder_dm()]
        self.bbs.bbs_messages = list(self.bbs.bbs_messages)  # keep whatever was loaded
        self._ack_patch = mock.patch.object(
            self.bbs,
            "_bbs_ack_settings",
            return_value=(True, 900, 5, 7200, True),
        )
        self._ack_patch.start()
        self._notify = mock.patch.object(self.bbs, "_notify_sender")
        self._notify_mock = self._notify.start()
        self._known = mock.patch.object(self.bbs, "node_known_in_nodedb", return_value=False)
        self._known.start()

    def tearDown(self):
        self._known.stop()
        self._notify.stop()
        self._ack_patch.stop()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def test_migrate_legacy_triple(self):
        entry = self.bbs.migrate_dm_entry([111, "Hallo", 222])
        self.assertEqual(entry["to"], 111)
        self.assertEqual(entry["body"], "Hallo")
        self.assertEqual(entry["from"], 222)
        self.assertFalse(entry["require_user_ack"])
        self.assertEqual(entry["state"], self.bbs.DM_STATE_QUEUED)

    def test_post_normal_unchanged_shape_and_delete(self):
        msg = self.bbs.bbs_post_dm(1001, "normal mail", 2002, require_user_ack=False)
        self.assertIn("gespeichert", msg)
        self.assertEqual(len(self.bbs.bbs_dm), 2)
        entry = self.bbs.bbs_dm[1]
        self.assertFalse(self.bbs.dm_require_user_ack(entry))
        self.assertEqual(self.bbs.dm_body(entry), "normal mail")

        with mock.patch.object(self.bbs, "node_known_in_nodedb", return_value=True), mock.patch.object(
            self.bbs, "_send_dm_to_recipient", return_value=True
        ) as send:
            result = self.bbs.bbs_deliver_entry(entry, device_id=1)
            self.assertEqual(result, "delivered")
            send.assert_called_once()
        self.assertEqual(len(self.bbs.bbs_dm), 1)  # only placeholder

    def test_post_ack_requires_feature_and_msg_id(self):
        self._ack_patch.stop()
        with mock.patch.object(self.bbs, "_bbs_ack_settings", return_value=(False, 900, 5, 7200, True)):
            out = self.bbs.bbs_post_dm(1001, "x", 2002, require_user_ack=True)
            self.assertIn("deaktiviert", out)
        self._ack_patch = mock.patch.object(
            self.bbs, "_bbs_ack_settings", return_value=(True, 900, 5, 7200, True)
        )
        self._ack_patch.start()

        out = self.bbs.bbs_post_dm(1001, "wichtig", 2002, require_user_ack=True)
        self.assertIn("ACK", out)
        entry = self.bbs.bbs_dm[1]
        self.assertTrue(entry["require_user_ack"])
        self.assertTrue(entry["msg_id"])
        self.assertIn(entry["msg_id"], out)

    def test_user_ack_by_id_and_bare_ack(self):
        self.bbs.bbs_post_dm(50, "a", 60, require_user_ack=True)
        entry = self.bbs.bbs_dm[1]
        entry["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        mid = entry["msg_id"]

        # wrong id
        self.assertIn("Keine wartende", self.bbs.bbs_handle_user_ack(50, "zzzz"))

        ok = self.bbs.bbs_handle_user_ack(50, mid)
        self.assertIn("Danke", ok)
        self.assertEqual(len(self.bbs.bbs_dm), 1)

        # bare ack with exactly one pending
        self.bbs.bbs_post_dm(70, "b", 80, require_user_ack=True)
        self.bbs.bbs_dm[1]["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        ok2 = self.bbs.bbs_handle_user_ack(70, None)
        self.assertIn("Danke", ok2)

    def test_bare_ack_ambiguous(self):
        self.bbs.bbs_post_dm(1, "one", 9, require_user_ack=True)
        self.bbs.bbs_post_dm(1, "two", 9, require_user_ack=True)
        for e in self.bbs.bbs_dm[1:]:
            e["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        out = self.bbs.bbs_handle_user_ack(1, None)
        self.assertIn("Mehrere", out)

    def test_parse_ack_command(self):
        self.assertEqual(self.bbs.parse_ack_command("ack"), (True, None))
        self.assertEqual(self.bbs.parse_ack_command("!ack ab12"), (True, "ab12"))
        self.assertEqual(self.bbs.parse_ack_command("ack @foo"), (False, None))
        self.assertEqual(self.bbs.parse_ack_command("ping"), (False, None))

    def test_retry_and_expire(self):
        self.bbs.bbs_post_dm(10, "retry-me", 20, require_user_ack=True)
        entry = self.bbs.bbs_dm[1]
        entry["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        entry["attempt_count"] = 1
        entry["last_attempt_at"] = time.time()
        self.assertFalse(self.bbs._retry_due(entry))
        entry["last_attempt_at"] = time.time() - 1000
        self.assertTrue(self.bbs._retry_due(entry))

        entry["attempt_count"] = 5
        self.assertTrue(self.bbs._is_expired(entry))

        entry["attempt_count"] = 1
        entry["created_at"] = time.time() - 8000
        self.assertTrue(self.bbs._is_expired(entry))

    def test_maintenance_expires(self):
        self.bbs.bbs_post_dm(33, "old", 44, require_user_ack=True)
        entry = self.bbs.bbs_dm[1]
        entry["created_at"] = time.time() - 99999
        entry["attempt_count"] = 5
        entry["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        self.bbs.bbs_ack_maintenance_tick(1)
        self.assertEqual(len(self.bbs.bbs_dm), 1)
        self.assertTrue(
            any("abgelaufen" in str(c) for c in self._notify_mock.call_args_list)
            or self._notify_mock.called
        )

    def test_mesh_ack_hook_notifies(self):
        self.bbs.bbs_post_dm(55, "mesh", 66, require_user_ack=True)
        entry = self.bbs.bbs_dm[1]
        entry["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        self._notify_mock.reset_mock()
        self.bbs.bbs_on_mesh_delivery_result(55, True)
        self.assertTrue(entry["mesh_acked"] is True)
        self.assertTrue(
            any("Node-Empfang bestätigt" in str(c) for c in self._notify_mock.call_args_list)
        )

    def test_load_migrates_and_saves(self):
        import pickle

        legacy = [[1234567890, "Message", 1234567890], [7, "legacy", 8]]
        with open("data/bbsdm.pkl", "wb") as f:
            pickle.dump(legacy, f)
        self.bbs.bbs_dm = []
        self.bbs.load_bbsdm()
        self.assertTrue(self.bbs.is_placeholder_dm(self.bbs.bbs_dm[0], 0))
        self.assertEqual(self.bbs.dm_to(self.bbs.bbs_dm[1]), 7)
        self.assertIsInstance(self.bbs.bbs_dm[1], dict)

    def test_bbspost_ack_parse_via_regex(self):
        import re

        def require_ack(message: str) -> bool:
            at_idx = message.find("@")
            return bool(at_idx > 0 and re.search(r"\back\b", message[:at_idx], flags=re.IGNORECASE))

        self.assertTrue(require_ack("bbspost ack @alice #hi"))
        self.assertTrue(require_ack("!bbspost ACK @!aabbccdd #x"))
        self.assertFalse(require_ack("bbspost @alice #hi"))
        self.assertFalse(require_ack("bbspost @acknode #hi"))


if __name__ == "__main__":
    unittest.main()
