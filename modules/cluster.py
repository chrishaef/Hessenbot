"""
Hessenbot Cluster Manager
=========================
Roles
-----
  STANDALONE  Current single-bot behaviour; no cluster connectivity.
              All existing storage (pkl/SQLite) used unchanged.
  MASTER      Serves the sync REST-API and CouchDB replication endpoint.
              Owns the MQTT connection.  Manages the slave registry.
  SLAVE       Connects to master over HTTPS/CouchDB.  Monitors heartbeat.
              Switches to STANDALONE_ACTIVE mode when master unreachable.

Standalone-Active mode (slave failover)
-----------------------------------------
  • Announces itself in the configured Meshtastic channel.
  • Intercepts Meshtastic DMs addressed to the master node-ID,
    decrypts them with the (pre-distributed) master private key,
    and responds FROM ITS OWN identity — no impersonation.
  • Reduces features to whatever local services are reachable
    (see service_health.py).
  • On reconnect: pushes offline changes to master → returns to SLAVE mode.

All configuration is ENV-driven (see .env.*.template).
"""
from __future__ import annotations

import base64
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import requests

from modules.log import logger


# ---------------------------------------------------------------------------
# Role / Mode
# ---------------------------------------------------------------------------

class ClusterRole(str, Enum):
    STANDALONE        = "standalone"   # default — no cluster
    MASTER            = "master"
    SLAVE             = "slave"


class ClusterMode(str, Enum):
    """Runtime operating mode (can differ from role during failover)."""
    NORMAL            = "normal"           # slave: connected to master
    STANDALONE_ACTIVE = "standalone_active"  # slave: master unreachable


# ---------------------------------------------------------------------------
# Config (all from ENV)
# ---------------------------------------------------------------------------

@dataclass
class ClusterConfig:
    role: ClusterRole = ClusterRole.STANDALONE

    # Identity
    node_name: str = "Hessenbot"           # e.g. "Hessenbot FFM"

    # Master connection (slave only)
    master_url: str = ""                   # https://bunker-rz.example.com
    master_api_port: int = 8421            # REST API port on master
    master_couch_port: int = 5984          # CouchDB port on master
    master_user: str = ""
    master_pass: str = ""

    # Master identity (slave only — for DM interception)
    master_node_id: int = 0                # master's Meshtastic node ID (int)
    master_private_key_b64: str = ""       # base64-encoded; set after key-transfer

    # CouchDB (local, both master and slave)
    couch_url: str = "http://localhost:5984"
    couch_user: str = "admin"
    couch_pass: str = "admin"

    # Heartbeat / failover (slave)
    heartbeat_interval: int = 30           # seconds between pings
    failover_threshold: int = 3            # missed pings before standalone-active

    # Mesh announce
    standalone_announce_channel: int = 2   # Meshtastic channel number
    key_announce_interval: int = 3600      # seconds between key announces

    # Service health cache TTL
    service_check_ttl: int = 60

    # Master API auth token (shared secret, slaves present this header)
    api_token: str = ""

    # MQTT monitoring (slave checks broker independently + master reports status)
    mqtt_broker_url: str = ""          # e.g. mqtt://broker.example.com:1883
    mqtt_check_enabled: bool = False   # probe MQTT independently on slave

    @classmethod
    def from_env(cls) -> "ClusterConfig":
        cfg = cls()
        cfg.role = ClusterRole(
            os.environ.get("HESSENBOT_ROLE", "standalone").lower()
        )
        cfg.node_name = os.environ.get("HESSENBOT_NODE_NAME", "Hessenbot")
        cfg.master_url = os.environ.get("HESSENBOT_MASTER_URL", "")
        cfg.master_api_port = int(os.environ.get("HESSENBOT_MASTER_API_PORT", "8421"))
        cfg.master_couch_port = int(os.environ.get("HESSENBOT_MASTER_COUCH_PORT", "5984"))
        cfg.master_user = os.environ.get("HESSENBOT_MASTER_USER", "")
        cfg.master_pass = os.environ.get("HESSENBOT_MASTER_PASS", "")

        raw_node_id = os.environ.get("HESSENBOT_MASTER_NODE_ID", "0").strip()
        if raw_node_id.startswith("!"):
            cfg.master_node_id = int(raw_node_id[1:], 16)
        elif raw_node_id.startswith("0x"):
            cfg.master_node_id = int(raw_node_id, 16)
        else:
            cfg.master_node_id = int(raw_node_id) if raw_node_id else 0

        cfg.master_private_key_b64 = os.environ.get("HESSENBOT_MASTER_PRIVATE_KEY", "")
        cfg.couch_url = os.environ.get("COUCHDB_URL", "http://localhost:5984")
        cfg.couch_user = os.environ.get("COUCHDB_USER", "admin")
        cfg.couch_pass = os.environ.get("COUCHDB_PASS", "admin")
        cfg.heartbeat_interval = int(os.environ.get("HESSENBOT_HEARTBEAT_INTERVAL", "30"))
        cfg.failover_threshold = int(os.environ.get("HESSENBOT_FAILOVER_THRESHOLD", "3"))
        cfg.standalone_announce_channel = int(
            os.environ.get("HESSENBOT_STANDALONE_ANNOUNCE_CHANNEL", "2")
        )
        cfg.key_announce_interval = int(
            os.environ.get("HESSENBOT_KEY_ANNOUNCE_INTERVAL", "3600")
        )
        cfg.service_check_ttl = int(
            os.environ.get("HESSENBOT_SERVICE_CHECK_TTL", "60")
        )
        cfg.api_token = os.environ.get("HESSENBOT_API_TOKEN", "")
        cfg.mqtt_broker_url = os.environ.get("HESSENBOT_MQTT_BROKER_URL", "")
        cfg.mqtt_check_enabled = os.environ.get(
            "HESSENBOT_MQTT_CHECK", "false"
        ).lower() in ("1", "true", "yes")
        return cfg

    @property
    def master_api_base(self) -> str:
        return f"{self.master_url}:{self.master_api_port}"

    @property
    def master_private_key(self) -> Optional[bytes]:
        if not self.master_private_key_b64:
            return None
        try:
            return base64.b64decode(self.master_private_key_b64)
        except Exception:
            return None

    def is_cluster(self) -> bool:
        return self.role != ClusterRole.STANDALONE


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

config: ClusterConfig = ClusterConfig()          # loaded in init()
mode: ClusterMode = ClusterMode.NORMAL            # current runtime mode
_missed_heartbeats: int = 0
_heartbeat_thread: Optional[threading.Thread] = None
_key_announce_thread: Optional[threading.Thread] = None
_mode_change_callbacks: List[Callable[[ClusterMode], None]] = []
_send_fn: Optional[Callable] = None              # injected from mesh_bot
_slave_registry: Dict[str, Dict] = {}            # master side: node_id → info
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init(send_message_fn: Optional[Callable] = None) -> None:
    """
    Call once at bot startup.
    send_message_fn(msg, channel, interface_num) — injects the Meshtastic
    send function so cluster can broadcast without importing mesh_bot.
    """
    global config, _send_fn
    config = ClusterConfig.from_env()
    _send_fn = send_message_fn

    if not config.is_cluster():
        logger.info("Cluster: role=standalone — cluster features disabled")
        return

    # Register master URL as a health-check service
    if config.master_url:
        from modules.service_health import register_service, set_ttl
        register_service("master", f"{config.master_api_base}/cluster/ping")
        set_ttl(config.service_check_ttl)

    logger.info(
        f"Cluster: starting — role={config.role.value} "
        f"node='{config.node_name}'"
    )

    if config.role == ClusterRole.SLAVE:
        _start_heartbeat()

    if config.role == ClusterRole.MASTER:
        _load_slave_registry()

    _start_key_announce()


# ---------------------------------------------------------------------------
# Heartbeat (slave)
# ---------------------------------------------------------------------------

def _start_heartbeat() -> None:
    global _heartbeat_thread
    _heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, daemon=True, name="cluster-heartbeat"
    )
    _heartbeat_thread.start()
    logger.info(
        f"Cluster: heartbeat started — interval={config.heartbeat_interval}s "
        f"threshold={config.failover_threshold}"
    )


def _heartbeat_loop() -> None:
    global _missed_heartbeats, mode
    while True:
        time.sleep(config.heartbeat_interval)
        master_ok, mqtt_ok = _ping_master()
        cluster_ok = master_ok and mqtt_ok

        if cluster_ok:
            if mode == ClusterMode.STANDALONE_ACTIVE:
                _switch_mode(ClusterMode.NORMAL)
            _missed_heartbeats = 0
        else:
            _missed_heartbeats += 1
            reason = []
            if not master_ok:
                reason.append("master nicht erreichbar")
            if not mqtt_ok:
                reason.append("MQTT ausgefallen")
            logger.warning(
                f"Cluster: {', '.join(reason)} "
                f"({_missed_heartbeats}/{config.failover_threshold})"
            )
            if (
                _missed_heartbeats >= config.failover_threshold
                and mode == ClusterMode.NORMAL
            ):
                _switch_mode(ClusterMode.STANDALONE_ACTIVE)


def _ping_master() -> tuple[bool, bool]:
    """
    Returns (master_reachable, mqtt_ok).
    master_reachable: REST API ping succeeded.
    mqtt_ok: master reports MQTT up, or slave's own MQTT probe passes.
    If MQTT monitoring is disabled, mqtt_ok is always True.
    """
    master_ok = False
    mqtt_ok = True  # assume ok unless we can check

    try:
        url = f"{config.master_api_base}/cluster/ping"
        r = requests.get(
            url,
            headers=_auth_headers(),
            timeout=max(config.heartbeat_interval // 2, 5),
        )
        if r.status_code == 200:
            master_ok = True
            try:
                data = r.json()
                # Master reports its own MQTT status in the ping response
                if "mqtt_ok" in data:
                    mqtt_ok = bool(data["mqtt_ok"])
            except Exception:
                pass
    except Exception:
        master_ok = False

    # Independent MQTT probe on slave side (optional)
    if config.mqtt_check_enabled and config.mqtt_broker_url:
        mqtt_ok = mqtt_ok and _probe_mqtt()

    return master_ok, mqtt_ok


def _probe_mqtt() -> bool:
    """
    Lightweight TCP connectivity check to the MQTT broker.
    Parses mqtt[s]://host:port or tcp://host:port.
    """
    import socket
    url = config.mqtt_broker_url
    try:
        # Strip scheme
        if "://" in url:
            url = url.split("://", 1)[1]
        if "/" in url:
            url = url.split("/")[0]
        host, _, port_str = url.partition(":")
        port = int(port_str) if port_str else 1883
        with socket.create_connection((host, port), timeout=5):
            return True
    except Exception:
        logger.debug(f"Cluster: MQTT probe failed ({config.mqtt_broker_url})")
        return False


# ---------------------------------------------------------------------------
# Mode switching
# ---------------------------------------------------------------------------

def _switch_mode(new_mode: ClusterMode) -> None:
    global mode
    with _lock:
        if mode == new_mode:
            return
        old_mode = mode
        mode = new_mode

    logger.warning(
        f"Cluster: mode change {old_mode.value} → {new_mode.value}"
    )

    if new_mode == ClusterMode.STANDALONE_ACTIVE:
        _announce_standalone()
    elif new_mode == ClusterMode.NORMAL:
        _announce_reconnected()
        _push_offline_delta()

    for cb in _mode_change_callbacks:
        try:
            cb(new_mode)
        except Exception as e:
            logger.error(f"Cluster: mode callback error: {e}")


def register_mode_callback(fn: Callable[[ClusterMode], None]) -> None:
    """Register a function called on every mode change."""
    _mode_change_callbacks.append(fn)


def is_standalone_active() -> bool:
    return mode == ClusterMode.STANDALONE_ACTIVE


def is_normal() -> bool:
    return mode == ClusterMode.NORMAL or config.role == ClusterRole.STANDALONE


# ---------------------------------------------------------------------------
# Mesh announcements
# ---------------------------------------------------------------------------

def _announce_standalone() -> None:
    msg = (
        f"📡 {config.node_name} läuft im Standalone-Modus "
        f"(Master nicht erreichbar). Ich beantworte Anfragen stellvertretend."
    )
    _send(msg, channel=config.standalone_announce_channel)


def _announce_reconnected() -> None:
    msg = (
        f"✅ {config.node_name} wieder mit Master verbunden. "
        f"Normalbetrieb."
    )
    _send(msg, channel=config.standalone_announce_channel)


def _send(msg: str, channel: int = 0) -> None:
    if _send_fn:
        try:
            _send_fn(msg, channel)
        except Exception as e:
            logger.error(f"Cluster: mesh send failed: {e}")


# ---------------------------------------------------------------------------
# Key announce
# ---------------------------------------------------------------------------

def _start_key_announce() -> None:
    global _key_announce_thread
    _key_announce_thread = threading.Thread(
        target=_key_announce_loop, daemon=True, name="cluster-key-announce"
    )
    _key_announce_thread.start()


def _key_announce_loop() -> None:
    # Wait a bit before first announce so the interface is ready
    time.sleep(60)
    while True:
        _do_key_announce()
        time.sleep(config.key_announce_interval)


def _do_key_announce() -> None:
    try:
        from modules.system import get_my_node_info
        info = get_my_node_info()
        pub_key_b64 = info.get("publicKey", "")
        if not pub_key_b64:
            return
        msg = (
            f"🔑 {config.node_name} · PublicKey: {pub_key_b64[:24]}…"
        )
        _send(msg, channel=config.standalone_announce_channel)
        logger.debug(f"Cluster: key announced on ch{config.standalone_announce_channel}")
    except Exception as e:
        logger.debug(f"Cluster: key announce failed: {e}")


# ---------------------------------------------------------------------------
# Master DM interception (slave standalone-active mode)
# ---------------------------------------------------------------------------

def should_intercept(packet: Dict[str, Any]) -> bool:
    """
    Returns True if this packet is a DM addressed to the master node
    and we have the master private key.
    Only active when slave is in STANDALONE_ACTIVE mode.
    """
    if not is_standalone_active():
        return False
    if config.master_node_id == 0:
        return False
    if config.master_private_key is None:
        return False
    to_id = packet.get("to", 0)
    return int(to_id) == config.master_node_id


def decrypt_master_packet(packet: Dict[str, Any]) -> Optional[str]:
    """
    Attempts to decrypt a packet addressed to master using master's private key.
    Returns the plaintext message string, or None on failure.

    NOTE: Meshtastic PKI uses Curve25519/ECDH. The Python meshtastic library
    performs decryption internally using the radio's stored key. To decrypt
    foreign packets in software, we must replicate the key-exchange here.
    Implementation uses the meshtastic mesh_pb2 protobuf + cryptography library.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import google.protobuf.message

        raw = packet.get("raw")
        if raw is None:
            return None

        master_priv_bytes = config.master_private_key
        if not master_priv_bytes:
            return None

        # Reconstruct private key
        priv_key = X25519PrivateKey.from_private_bytes(master_priv_bytes)

        # Extract sender public key from packet / NodeDB
        from_id = packet.get("from", 0)
        sender_pub_b64 = _get_node_public_key(from_id)
        if not sender_pub_b64:
            logger.debug(f"Cluster: no public key for sender {from_id:x}")
            return None

        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        sender_pub_bytes = base64.b64decode(sender_pub_b64)
        sender_pub = X25519PublicKey.from_public_bytes(sender_pub_bytes)

        # ECDH shared secret
        shared = priv_key.exchange(sender_pub)

        # Derive AES key (Meshtastic uses first 16 bytes of SHA256(shared))
        import hashlib
        aes_key = hashlib.sha256(shared).digest()[:16]

        # Decrypt (Meshtastic PKI DM uses AES-128-CTR, nonce = packet_id || from_id)
        # packet_id is 32-bit, from_id 32-bit, nonce padded to 16 bytes
        packet_id = packet.get("id", 0)
        nonce = (
            packet_id.to_bytes(8, "little")
            + from_id.to_bytes(8, "little")
        )

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        cipher = Cipher(
            algorithms.AES(aes_key),
            modes.CTR(nonce)
        )
        dec = cipher.decryptor()
        encrypted_payload = raw.get("encrypted", b"")
        plaintext = dec.update(encrypted_payload) + dec.finalize()

        # Parse as MeshPacket decoded
        from meshtastic import mesh_pb2
        data = mesh_pb2.Data()
        data.ParseFromString(plaintext)
        return data.payload.decode("utf-8", errors="replace")

    except Exception as e:
        logger.debug(f"Cluster: master packet decrypt failed: {e}")
        return None


def _get_node_public_key(node_id: int) -> Optional[str]:
    try:
        from modules.system import get_name_from_number
        # Try nodedb first
        try:
            from modules.nodedb import get_node_info
            info = get_node_info(node_id)
            if info:
                return info.get("publicKey")
        except ImportError:
            pass
        # Fallback: interface nodes dict
        import modules.settings as st
        iface = getattr(st, "interface1", None)
        if iface and hasattr(iface, "nodesByNum"):
            node = iface.nodesByNum.get(node_id, {})
            return node.get("user", {}).get("publicKey")
    except Exception:
        pass
    return None


def proxy_response(original_text: str, from_id: int) -> str:
    """
    Wraps a command response to clearly mark it as a proxy/stellvertreter reply.
    The slave answers with its own key — NOT impersonating the master.
    """
    return f"📡 {config.node_name} (Stellvertreter):\n{original_text}"


# ---------------------------------------------------------------------------
# Slave registry (master side)
# ---------------------------------------------------------------------------

def _load_slave_registry() -> None:
    global _slave_registry
    try:
        from modules.cluster_store import load_slave_registry
        _slave_registry = load_slave_registry()
        logger.info(
            f"Cluster: loaded {len(_slave_registry)} slave(s) from registry"
        )
    except Exception as e:
        logger.warning(f"Cluster: could not load slave registry: {e}")
        _slave_registry = {}


def authorize_slave(
    node_id: str,
    name: str,
    public_key_b64: str = "",
    transfer_master_key: bool = False,
) -> Dict:
    """Authorize a slave at runtime. Returns the slave record."""
    record = {
        "node_id": node_id,
        "name": name,
        "public_key": public_key_b64,
        "authorized": True,
        "authorized_at": time.time(),
        "last_seen": None,
        "mode": "unknown",
        "master_key_transferred": False,
    }
    if transfer_master_key:
        record["master_key_b64"] = config.master_private_key_b64
        record["master_key_transferred"] = True

    with _lock:
        _slave_registry[node_id] = record
    try:
        from modules.cluster_store import save_slave_registry
        save_slave_registry(_slave_registry)
    except Exception as e:
        logger.error(f"Cluster: could not persist slave registry: {e}")
    logger.info(f"Cluster: slave '{name}' ({node_id}) authorized")
    return record


def deauthorize_slave(node_id: str) -> bool:
    with _lock:
        if node_id not in _slave_registry:
            return False
        _slave_registry[node_id]["authorized"] = False
    try:
        from modules.cluster_store import save_slave_registry
        save_slave_registry(_slave_registry)
    except Exception as e:
        logger.error(f"Cluster: could not persist slave registry: {e}")
    logger.info(f"Cluster: slave {node_id} deauthorized")
    return True


def get_slave_registry() -> Dict[str, Dict]:
    with _lock:
        return dict(_slave_registry)


def update_slave_heartbeat(node_id: str, slave_mode: str) -> None:
    with _lock:
        if node_id in _slave_registry:
            _slave_registry[node_id]["last_seen"] = time.time()
            _slave_registry[node_id]["mode"] = slave_mode


def is_slave_authorized(node_id: str) -> bool:
    with _lock:
        rec = _slave_registry.get(node_id)
        return bool(rec and rec.get("authorized"))


# ---------------------------------------------------------------------------
# Sync (slave → master delta push on reconnect)
# ---------------------------------------------------------------------------

def _push_offline_delta() -> None:
    """Called when a slave reconnects. Pushes locally accumulated changes."""
    try:
        from modules.cluster_store import push_outbox
        pushed = push_outbox()
        if pushed:
            logger.info(f"Cluster: pushed {pushed} offline change(s) to master")
    except Exception as e:
        logger.warning(f"Cluster: offline delta push failed: {e}")


# ---------------------------------------------------------------------------
# REST API helpers (slave → master)
# ---------------------------------------------------------------------------

def _auth_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if config.api_token:
        headers["X-Cluster-Token"] = config.api_token
    return headers


def master_get(path: str, **kwargs) -> Optional[requests.Response]:
    try:
        url = f"{config.master_api_base}{path}"
        return requests.get(url, headers=_auth_headers(), timeout=10, **kwargs)
    except Exception as e:
        logger.debug(f"Cluster: GET {path} failed: {e}")
        return None


def master_post(path: str, json: Any = None, **kwargs) -> Optional[requests.Response]:
    try:
        url = f"{config.master_api_base}{path}"
        return requests.post(
            url, json=json, headers=_auth_headers(), timeout=10, **kwargs
        )
    except Exception as e:
        logger.debug(f"Cluster: POST {path} failed: {e}")
        return None
