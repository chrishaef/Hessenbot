#!/usr/bin/env python3
# Tests für die Service-API (/api/v1/dm, /api/v1/whoami) — ohne Radio, ohne Netz.
# Run: python -m pytest modules/test_service_api.py -q
import os
import sys
import types
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import modules as modules_pkg
    from modules.admin_web import create_app
    from modules import service_api as sapi
    FLASK_OK = True
    IMPORT_ERR = None
except Exception as e:  # Flask-Stack fehlt (lokale Minimal-Umgebung) → Suite skippt
    FLASK_OK = False
    IMPORT_ERR = e

TOKEN = "test-token-123"


def _make_app(*, token: str = TOKEN, enabled: bool = True):
    sapi.configure(
        enabled=enabled,
        token_hash=sapi.hash_token(token) if token else "",
        env_token="",
        log_dir="logs",
    )
    return create_app(
        alert_path="alert.txt",
        news_path="alert.txt",
        log_dir="logs",
        admin_username="admin",
        admin_password="pw",
        secret_key="test-secret",
    )


def _chat_stub(resolve=(0x11223344, None), send=(True, "Nachricht gesendet.")):
    stub = types.SimpleNamespace()
    stub.default_mesh_interface = lambda: 1
    stub.default_mesh_channel = lambda: 2
    stub.resolve_dest_node = mock.Mock(return_value=resolve)
    stub.send_mesh_message = mock.Mock(return_value=send)
    return stub


def _patched_chat(chat):
    # Beide Auflösungswege abdecken: sys.modules UND Paket-Attribut — je nachdem,
    # ob ein anderer Test das echte Modul schon importiert hat.
    return (
        mock.patch.dict(sys.modules, {"modules.admin_mesh_chat": chat}),
        mock.patch.object(modules_pkg, "admin_mesh_chat", chat, create=True),
    )


@unittest.skipUnless(FLASK_OK, f"Flask-Stack nicht installiert: {IMPORT_ERR}")
class ServiceApiTests(unittest.TestCase):
    def tearDown(self):
        sapi.configure(enabled=False, token_hash="", env_token="", log_dir="logs")
        sapi.clear_memory_logs()

    def test_api_disabled_without_token(self):
        c = _make_app(token="", enabled=False).test_client()
        r = c.post("/api/v1/dm", json={"node_id": "!11223344", "text": "hi"})
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.get_json()["ok"])
        self.assertEqual(r.get_json()["error"], "api_disabled")
        r = c.get("/api/v1/whoami")
        self.assertEqual(r.status_code, 503)

    def test_unauthorized_wrong_or_missing_token(self):
        c = _make_app(token=TOKEN).test_client()
        r = c.post("/api/v1/dm", json={"node_id": "!11223344", "text": "hi"})
        self.assertEqual(r.status_code, 401)
        r = c.post(
            "/api/v1/dm",
            json={"node_id": "!11223344", "text": "hi"},
            headers={"Authorization": "Bearer falsch"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"], "unauthorized")

    def test_unauthorized_wrong_length_token_is_401_not_500(self):
        c = _make_app(token=TOKEN).test_client()
        r = c.post(
            "/api/v1/dm",
            json={"node_id": "!11223344", "text": "hi"},
            headers={"Authorization": "Bearer x"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"], "unauthorized")

    def test_validation_errors(self):
        c = _make_app(token=TOKEN).test_client()
        hdr = {"Authorization": f"Bearer {TOKEN}"}
        r = c.post("/api/v1/dm", data="kein json", headers=hdr, content_type="text/plain")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "json_body_required")
        r = c.post("/api/v1/dm", json={"text": "hi"}, headers=hdr)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "node_id_required")
        r = c.post("/api/v1/dm", json={"node_id": "!11223344"}, headers=hdr)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "text_required")
        r = c.post(
            "/api/v1/dm",
            json={"node_id": "!11223344", "text": "hi", "channel": "zwei"},
            headers=hdr,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "invalid_channel_or_interface")
        r = c.post(
            "/api/v1/dm",
            json={"node_id": "!11223344", "text": "x" * 501},
            headers=hdr,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "text_too_long")

    def test_send_ok_with_defaults(self):
        c = _make_app(token=TOKEN).test_client()
        chat = _chat_stub()
        p1, p2 = _patched_chat(chat)
        with p1, p2:
            r = c.post(
                "/api/v1/dm",
                json={"node_id": "!11223344", "text": "Hallo Node"},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["dest_node"], 0x11223344)
        self.assertEqual(body["dest_node_id"], "!11223344")
        chat.resolve_dest_node.assert_called_once_with("!11223344", 1)
        chat.send_mesh_message.assert_called_once_with(
            "Hallo Node", channel=2, interface=1, dest_node=0x11223344
        )
        logs = sapi.recent_logs(5)
        self.assertTrue(logs)
        self.assertEqual(logs[0]["status"], 200)
        self.assertEqual(logs[0]["endpoint"], "/api/v1/dm")

    def test_send_failure_returns_502(self):
        c = _make_app(token=TOKEN).test_client()
        chat = _chat_stub(send=(False, "Senden fehlgeschlagen — siehe meshbot.log."))
        p1, p2 = _patched_chat(chat)
        with p1, p2:
            r = c.post(
                "/api/v1/dm",
                json={"node_id": "!11223344", "text": "hi"},
                headers={"X-Api-Token": TOKEN},  # Header-Alternative mittesten
            )
        self.assertEqual(r.status_code, 502)
        self.assertFalse(r.get_json()["ok"])

    def test_dest_not_resolved(self):
        c = _make_app(token=TOKEN).test_client()
        chat = _chat_stub(resolve=(None, "Empfänger nicht in NodeDB gefunden (foo)."))
        p1, p2 = _patched_chat(chat)
        with p1, p2:
            r = c.post(
                "/api/v1/dm",
                json={"node_id": "foo", "text": "hi"},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "dest_not_resolved")
        chat.send_mesh_message.assert_not_called()

    def test_whoami_filters_uninitialized_interfaces(self):
        c = _make_app(token=TOKEN).test_client()
        sm = types.SimpleNamespace(myNodeNum1=0x0A0B0C0D, myNodeNum2=777)
        ops = types.SimpleNamespace(iter_radio_interfaces=lambda: [1, 2])
        with mock.patch.dict(
            sys.modules, {"modules.system": sm, "modules.admin_web_ops": ops}
        ), mock.patch.object(modules_pkg, "system", sm, create=True), mock.patch.object(
            modules_pkg, "admin_web_ops", ops, create=True
        ):
            r = c.get("/api/v1/whoami", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["radios"],
            [{"interface": 1, "node_num": 0x0A0B0C0D, "node_id": "!0a0b0c0d"}],
        )

    def test_bearer_case_insensitive_prefix(self):
        c = _make_app(token=TOKEN).test_client()
        chat = _chat_stub()
        p1, p2 = _patched_chat(chat)
        with p1, p2:
            r = c.post(
                "/api/v1/dm",
                json={"node_id": "!11223344", "text": "hi"},
                headers={"Authorization": f"bearer {TOKEN}"},
            )
        self.assertEqual(r.status_code, 200)

    def test_hash_helpers(self):
        self.assertTrue(sapi._safe_compare("abc", "abc"))
        self.assertFalse(sapi._safe_compare("abc", "ab"))
        self.assertFalse(sapi._safe_compare("abc", "abd"))
        digest = sapi.hash_token("secret")
        self.assertEqual(len(digest), 64)
        plain = "migrate-me"
        cfg = {"webAdmin": {"api_token": plain}}
        self.assertTrue(sapi.migrate_plaintext_token_if_needed(cfg))
        self.assertEqual(cfg["webAdmin"]["api_token_hash"], sapi.hash_token(plain))
        self.assertEqual(cfg["webAdmin"]["api_token"], "")
        self.assertIn("api_enabled", cfg["webAdmin"])


if __name__ == "__main__":
    unittest.main()
