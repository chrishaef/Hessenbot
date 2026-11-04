#!/usr/bin/env python3
# Tests für die Cluster-Replikation der BBS-DM-Queue (hessenbot_bbs_dm).
# Run: python -m unittest modules.test_cluster_dm_sync -q
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class FakeCouch:
    """In-memory stand-in for cluster_store.CouchDB."""

    def __init__(self):
        self.dbs = {"hessenbot_bbs_dm": {}}

    def all_docs(self, db):
        return [dict(d) for d in self.dbs.get(db, {}).values()]

    def put(self, db, doc_id, doc):
        stored = dict(doc)
        stored["_id"] = doc_id
        self.dbs.setdefault(db, {})[doc_id] = stored
        return True

    def post(self, db, doc):
        doc_id = f"auto_{len(self.dbs.setdefault(db, {}))}"
        return doc_id if self.put(db, doc_id, doc) else None


class ClusterDmSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        os.makedirs("data", exist_ok=True)

        import modules.bbstools as bbs
        import modules.cluster_store as cs

        self.bbs = bbs
        self.cs = cs
        self.couch = FakeCouch()
        self.bbs.bbs_dm = [self.bbs.make_placeholder_dm()]
        cs._dm_seen_keys = set()

        self._patches = [
            mock.patch.object(cs, "_get_client", return_value=self.couch),
            mock.patch.object(cs, "_my_node_id", return_value="1111"),
            mock.patch.object(
                bbs, "_bbs_ack_settings", return_value=(True, 900, 5, 7200, True)
            ),
            mock.patch.object(bbs, "_notify_sender"),
            mock.patch.object(bbs, "node_known_in_nodedb", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.cs._dm_seen_keys = set()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()

    def _docs(self):
        return self.couch.dbs["hessenbot_bbs_dm"]

    def test_push_new_local_entry(self):
        self.bbs.bbs_post_dm(1001, "hallo welt", 2002, require_user_ack=True)
        self.cs._sync_bbs_dm()
        docs = list(self._docs().values())
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["to"], 1001)
        self.assertEqual(docs[0]["state"], self.bbs.DM_STATE_QUEUED)
        self.assertTrue(docs[0]["dm_key"].startswith("id_"))
        self.assertEqual(docs[0]["origin_node"], "1111")

    def test_pull_remote_entry_into_local_queue(self):
        self.couch.put("hessenbot_bbs_dm", "dm_id_beef", {
            "dm_key": "id_beef", "to": 3003, "body": "remote mail", "from": 4004,
            "require_user_ack": True, "state": "queued", "created_at": 1.0,
            "last_attempt_at": None, "attempt_count": 0, "mesh_acked": None,
            "user_acked": False, "msg_id": "beef", "notify_sender": True,
            "notified_unknown_target": False, "origin_node": "9999",
        })
        self.cs._sync_bbs_dm()
        self.assertEqual(len(self.bbs.bbs_dm), 2)
        entry = self.bbs.bbs_dm[1]
        self.assertEqual(self.bbs.dm_to(entry), 3003)
        self.assertEqual(self.bbs.dm_msg_id(entry), "beef")
        self.assertIsNone(entry["mesh_request_id"])

    def test_pull_skips_terminal_and_resets_delivering(self):
        for state, key in (("acked", "id_dead"), ("delivering", "id_cafe")):
            self.couch.put("hessenbot_bbs_dm", f"dm_{key}", {
                "dm_key": key, "to": 5005, "body": f"mail {state}", "from": 6006,
                "require_user_ack": True, "state": state, "created_at": 1.0,
                "attempt_count": 1, "msg_id": key[3:],
            })
        self.cs._sync_bbs_dm()
        bodies = [self.bbs.dm_body(e) for e in self.bbs.bbs_dm[1:]]
        self.assertEqual(bodies, ["mail delivering"])
        self.assertEqual(self.bbs.bbs_dm[1]["state"], self.bbs.DM_STATE_QUEUED)

    def test_vanished_local_entry_closes_remote_doc(self):
        self.bbs.bbs_post_dm(1001, "wird zugestellt", 2002, require_user_ack=True)
        self.cs._sync_bbs_dm()  # push + remember key
        self.bbs.bbs_dm = [self.bbs.make_placeholder_dm()]  # delivered locally
        self.cs._sync_bbs_dm()
        docs = list(self._docs().values())
        self.assertEqual(docs[0]["state"], "closed")
        self.assertEqual(docs[0]["closed_by"], "1111")
        # And a later round must not pull the closed doc back in
        self.cs._dm_seen_keys = set()
        self.cs._sync_bbs_dm()
        self.assertEqual(len(self.bbs.bbs_dm), 1)

    def test_state_advance_pushed_to_remote(self):
        self.bbs.bbs_post_dm(1001, "ack mail", 2002, require_user_ack=True)
        self.cs._sync_bbs_dm()
        self.bbs.bbs_dm[1]["state"] = self.bbs.DM_STATE_AWAITING_USER_ACK
        self.bbs.bbs_dm[1]["mesh_acked"] = True
        self.bbs.bbs_dm[1]["attempt_count"] = 1
        self.cs._sync_bbs_dm()
        docs = list(self._docs().values())
        self.assertEqual(docs[0]["state"], self.bbs.DM_STATE_AWAITING_USER_ACK)
        self.assertTrue(docs[0]["mesh_acked"])
        self.assertEqual(docs[0]["attempt_count"], 1)


if __name__ == "__main__":
    unittest.main()
