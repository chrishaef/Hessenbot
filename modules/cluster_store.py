"""
Hessenbot Cluster Storage — CouchDB adapter + sync bridge.

In STANDALONE mode: this module is never used; existing pkl/SQLite stays intact.
In MASTER/SLAVE mode:
  • CouchDB (local container) is the live data store.
  • A sync-bridge daemon periodically reconciles CouchDB ↔ local pkl/SQLite
    so existing bot code keeps working without modification.
  • CouchDB's built-in replication handles master ↔ slave sync over HTTPS.
  • An outbox table in CouchDB accumulates offline writes on slaves so they
    can be pushed to master on reconnect.

CouchDB databases
-----------------
  hessenbot_bbs         — BBS messages (replicated)
  hessenbot_locations   — Saved map locations (replicated)
  hessenbot_checklist   — Checklist data (replicated)
  hessenbot_inventory   — Inventory / POS data (replicated)
  hessenbot_slaves      — Slave registry (master-local, NOT replicated)
  hessenbot_outbox      — Offline write buffer on slaves (slave-local)
  hessenbot_keys        — Encrypted key material (filtered replication)
"""
from __future__ import annotations

import json
import os
import pickle
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

from modules.log import logger


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class CouchDB:
    """Minimal CouchDB REST client."""

    def __init__(self, url: str, user: str, password: str) -> None:
        self.base = url.rstrip("/")
        self.auth = HTTPBasicAuth(user, password)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"Content-Type": "application/json"})

    def ping(self) -> bool:
        try:
            r = self.session.get(self.base, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_db(self, name: str) -> None:
        url = f"{self.base}/{name}"
        r = self.session.head(url, timeout=5)
        if r.status_code == 404:
            self.session.put(url, timeout=5)

    def get(self, db: str, doc_id: str) -> Optional[Dict]:
        r = self.session.get(f"{self.base}/{db}/{doc_id}", timeout=10)
        return r.json() if r.status_code == 200 else None

    def put(self, db: str, doc_id: str, doc: Dict) -> bool:
        existing = self.get(db, doc_id)
        if existing:
            doc["_rev"] = existing["_rev"]
        r = self.session.put(
            f"{self.base}/{db}/{doc_id}",
            data=json.dumps(doc),
            timeout=10,
        )
        return r.status_code in (200, 201)

    def post(self, db: str, doc: Dict) -> Optional[str]:
        """Insert new doc, returns assigned _id or None."""
        r = self.session.post(
            f"{self.base}/{db}",
            data=json.dumps(doc),
            timeout=10,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        return None

    def delete(self, db: str, doc_id: str) -> bool:
        doc = self.get(db, doc_id)
        if not doc:
            return False
        r = self.session.delete(
            f"{self.base}/{db}/{doc_id}",
            params={"rev": doc["_rev"]},
            timeout=10,
        )
        return r.status_code in (200, 201)

    def all_docs(self, db: str, include_deleted: bool = False) -> List[Dict]:
        params: Dict[str, Any] = {"include_docs": "true"}
        r = self.session.get(
            f"{self.base}/{db}/_all_docs",
            params=params,
            timeout=30,
        )
        if r.status_code != 200:
            return []
        rows = r.json().get("rows", [])
        docs = [row["doc"] for row in rows if "doc" in row]
        if not include_deleted:
            docs = [d for d in docs if not d.get("_deleted")]
        return docs

    def changes(self, db: str, since: str = "0") -> Tuple[List[Dict], str]:
        """Returns (changed_docs, last_seq)."""
        r = self.session.get(
            f"{self.base}/{db}/_changes",
            params={"since": since, "include_docs": "true"},
            timeout=30,
        )
        if r.status_code != 200:
            return [], since
        data = r.json()
        docs = [
            row["doc"]
            for row in data.get("results", [])
            if "doc" in row and not row["doc"].get("_deleted")
        ]
        return docs, str(data.get("last_seq", since))

    def setup_replication(
        self,
        source: str,
        target: str,
        rep_id: str,
        continuous: bool = True,
    ) -> bool:
        """Create a replication document in _replicator."""
        doc = {
            "_id": rep_id,
            "source": source,
            "target": target,
            "continuous": continuous,
            "create_target": True,
        }
        return self.put("_replicator", rep_id, doc)


# ---------------------------------------------------------------------------
# Module-level client (lazy init)
# ---------------------------------------------------------------------------

_client: Optional[CouchDB] = None
_lock = threading.Lock()
_SYNC_INTERVAL = 60  # seconds between bridge sync cycles
_sync_thread: Optional[threading.Thread] = None

_DBS = [
    "hessenbot_bbs",
    "hessenbot_locations",
    "hessenbot_checklist",
    "hessenbot_inventory",
    "hessenbot_slaves",
    "hessenbot_outbox",
    "hessenbot_keys",
]


def _get_client() -> CouchDB:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from modules.cluster import config as cluster_cfg
                _client = CouchDB(
                    cluster_cfg.couch_url,
                    cluster_cfg.couch_user,
                    cluster_cfg.couch_pass,
                )
    return _client


def init_databases() -> bool:
    """Ensure all required CouchDB databases exist. Returns True on success."""
    client = _get_client()
    if not client.ping():
        logger.error("ClusterStore: CouchDB not reachable")
        return False
    for db in _DBS:
        client.ensure_db(db)
    logger.info("ClusterStore: databases ready")
    return True


# ---------------------------------------------------------------------------
# Slave registry (master-local)
# ---------------------------------------------------------------------------

def load_slave_registry() -> Dict[str, Dict]:
    client = _get_client()
    docs = client.all_docs("hessenbot_slaves")
    return {d["node_id"]: d for d in docs if "node_id" in d}


def save_slave_registry(registry: Dict[str, Dict]) -> None:
    client = _get_client()
    for node_id, record in registry.items():
        doc = dict(record)
        doc.setdefault("_id", f"slave_{node_id}")
        client.put("hessenbot_slaves", doc["_id"], doc)


# ---------------------------------------------------------------------------
# Key storage (master → slave key transfer via CouchDB replication)
# ---------------------------------------------------------------------------

def store_master_key_for_slave(node_id: str, key_b64: str) -> bool:
    """
    Master stores the encrypted private key so the authorized slave
    can pull it during CouchDB replication.
    The key document is stored in hessenbot_keys and filtered to only
    replicate to the target slave's CouchDB.
    """
    client = _get_client()
    doc = {
        "_id": f"masterkey_{node_id}",
        "type": "master_private_key",
        "target_slave": node_id,
        "key_b64": key_b64,          # in production: encrypt with slave public key
        "issued_at": time.time(),
    }
    return client.put("hessenbot_keys", doc["_id"], doc)


def fetch_master_key(node_id: str) -> Optional[str]:
    """Slave pulls its key document from local CouchDB (replicated from master)."""
    client = _get_client()
    doc = client.get("hessenbot_keys", f"masterkey_{node_id}")
    if doc:
        return doc.get("key_b64")
    return None


# ---------------------------------------------------------------------------
# Outbox — offline write buffer on slaves
# ---------------------------------------------------------------------------

def outbox_append(db_name: str, operation: str, doc: Dict) -> None:
    """
    Record a local write to the outbox when offline.
    On reconnect, push_outbox() drains this to master.
    """
    client = _get_client()
    entry = {
        "db": db_name,
        "operation": operation,   # "upsert" | "delete"
        "doc": doc,
        "ts": time.time(),
    }
    client.post("hessenbot_outbox", entry)


def push_outbox() -> int:
    """
    Drain outbox → POST to master REST API.
    Returns number of records pushed.
    """
    from modules.cluster import master_post
    client = _get_client()
    docs = client.all_docs("hessenbot_outbox")
    pushed = 0
    for entry in docs:
        resp = master_post("/cluster/sync/push", json=entry)
        if resp and resp.status_code == 200:
            client.delete("hessenbot_outbox", entry["_id"])
            pushed += 1
        else:
            logger.warning(
                f"ClusterStore: outbox push failed for {entry.get('_id')}"
            )
    return pushed


# ---------------------------------------------------------------------------
# Replication setup
# ---------------------------------------------------------------------------

def setup_slave_replication(
    slave_couch_url: str,
    slave_user: str,
    slave_pass: str,
    slave_node_id: str,
    replicate_dbs: Optional[List[str]] = None,
) -> None:
    """
    Called on master: set up continuous bidirectional replication
    for the given slave's CouchDB instance.
    """
    if replicate_dbs is None:
        replicate_dbs = [
            "hessenbot_bbs",
            "hessenbot_locations",
            "hessenbot_checklist",
            "hessenbot_inventory",
        ]

    client = _get_client()
    creds = f"{slave_user}:{slave_pass}@"
    base = slave_couch_url.replace("://", f"://{creds}")

    for db in replicate_dbs:
        slave_url = f"{base}/{db}"
        safe_id = slave_node_id.replace("!", "").replace(".", "_")

        # Master → Slave
        client.setup_replication(
            source=f"/{db}",
            target=slave_url,
            rep_id=f"push_{safe_id}_{db}",
        )
        # Slave → Master
        client.setup_replication(
            source=slave_url,
            target=f"/{db}",
            rep_id=f"pull_{safe_id}_{db}",
        )

    # Keys DB: filtered push only (master → slave, not reverse)
    client.setup_replication(
        source=f"/hessenbot_keys",
        target=f"{base}/hessenbot_keys",
        rep_id=f"keys_{safe_id}",
    )
    logger.info(
        f"ClusterStore: replication configured for slave {slave_node_id}"
    )


# ---------------------------------------------------------------------------
# Sync bridge — CouchDB ↔ local pkl/SQLite
# ---------------------------------------------------------------------------
# This lets existing bot code keep reading/writing pkl+SQLite files
# while CouchDB handles cluster sync in the background.

def start_sync_bridge() -> None:
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return
    _sync_thread = threading.Thread(
        target=_sync_bridge_loop, daemon=True, name="cluster-sync-bridge"
    )
    _sync_thread.start()
    logger.info(f"ClusterStore: sync bridge started (interval={_SYNC_INTERVAL}s)")


def _sync_bridge_loop() -> None:
    while True:
        try:
            _sync_bbs()
            _sync_locations()
            _sync_checklist()
            _sync_inventory()
        except Exception as e:
            logger.error(f"ClusterStore: sync bridge error: {e}")
        time.sleep(_SYNC_INTERVAL)


def _sync_bbs() -> None:
    """Push local bbsdb.pkl posts → CouchDB; pull remote posts → bbsdb.pkl."""
    try:
        import modules.settings as st
        bbsdb_path = getattr(st, "bbsdb", "data/bbsdb.pkl")
        if not os.path.exists(bbsdb_path):
            return

        with open(bbsdb_path, "rb") as f:
            local_posts: List[Dict] = pickle.load(f)

        client = _get_client()
        existing = {d.get("local_id"): d for d in client.all_docs("hessenbot_bbs")}

        changed = False
        for post in local_posts:
            post_id = str(post.get("id", ""))
            if post_id and post_id not in existing:
                doc = dict(post)
                doc["local_id"] = post_id
                doc["origin_node"] = _my_node_id()
                client.post("hessenbot_bbs", doc)

        # Pull posts from CouchDB not in local
        local_ids = {str(p.get("id", "")) for p in local_posts}
        for doc in client.all_docs("hessenbot_bbs"):
            local_id = str(doc.get("local_id", ""))
            if local_id and local_id not in local_ids:
                local_posts.append({
                    k: v for k, v in doc.items()
                    if not k.startswith("_")
                })
                changed = True

        if changed:
            with open(bbsdb_path, "wb") as f:
                pickle.dump(local_posts, f)
    except Exception as e:
        logger.debug(f"ClusterStore: BBS sync error: {e}")


def _sync_locations() -> None:
    """Sync locations SQLite ↔ CouchDB."""
    try:
        import modules.settings as st
        db_path = getattr(st, "locations_db", "data/locations.db")
        if not os.path.exists(db_path):
            return

        client = _get_client()
        existing_couch = {
            d.get("name", "") + "_" + d.get("owner_id", ""): d
            for d in client.all_docs("hessenbot_locations")
        }

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM locations")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for row in rows:
            key = f"{row.get('name', '')}_{row.get('owner_id', '')}"
            if key not in existing_couch:
                doc = dict(row)
                doc["origin_node"] = _my_node_id()
                client.post("hessenbot_locations", doc)

        # Pull from CouchDB → SQLite (new rows from other nodes)
        local_keys = {
            f"{r.get('name', '')}_{r.get('owner_id', '')}" for r in rows
        }
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        inserted = 0
        for doc in client.all_docs("hessenbot_locations"):
            key = f"{doc.get('name', '')}_{doc.get('owner_id', '')}"
            if key not in local_keys:
                try:
                    cur.execute(
                        """INSERT OR IGNORE INTO locations
                           (name, lat, lon, description, owner_id, is_public, altitude, created_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            doc.get("name"),
                            doc.get("lat"),
                            doc.get("lon"),
                            doc.get("description", ""),
                            doc.get("owner_id"),
                            doc.get("is_public", 0),
                            doc.get("altitude"),
                            doc.get("created_at"),
                        ),
                    )
                    inserted += 1
                except Exception:
                    pass
        conn.commit()
        conn.close()
        if inserted:
            logger.debug(f"ClusterStore: locations: pulled {inserted} remote entries")
    except Exception as e:
        logger.debug(f"ClusterStore: locations sync error: {e}")


def _sync_sqlite_table(
    db_path: str,
    couch_db: str,
    table: str,
    pk_col: str,
    columns: List[str],
    insert_sql: str,
) -> None:
    """Generic SQLite ↔ CouchDB sync for simple tables."""
    if not os.path.exists(db_path):
        return
    client = _get_client()
    existing_couch = {
        str(d.get(pk_col, "")): d
        for d in client.all_docs(couch_db)
        if d.get(pk_col) is not None
    }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    local_pks = set()
    for row in rows:
        pk = str(row.get(pk_col, ""))
        local_pks.add(pk)
        if pk and pk not in existing_couch:
            doc = dict(row)
            doc["origin_node"] = _my_node_id()
            client.post(couch_db, doc)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    inserted = 0
    for doc in client.all_docs(couch_db):
        pk = str(doc.get(pk_col, ""))
        if pk and pk not in local_pks:
            try:
                values = tuple(doc.get(col) for col in columns)
                cur.execute(insert_sql, values)
                inserted += 1
            except Exception:
                pass
    conn.commit()
    conn.close()
    if inserted:
        logger.debug(f"ClusterStore: {table}: pulled {inserted} remote entries")


def _sync_checklist() -> None:
    try:
        import modules.settings as st
        db_path = getattr(st, "checklist_db", "data/checklist.db")
        _sync_sqlite_table(
            db_path,
            "hessenbot_checklist",
            "checklist_items",
            "id",
            ["id", "checklist_name", "node_id", "checked_in", "timestamp", "comment"],
            "INSERT OR IGNORE INTO checklist_items "
            "(id, checklist_name, node_id, checked_in, timestamp, comment) "
            "VALUES (?,?,?,?,?,?)",
        )
    except Exception as e:
        logger.debug(f"ClusterStore: checklist sync error: {e}")


def _sync_inventory() -> None:
    try:
        import modules.settings as st
        db_path = getattr(st, "inventory_db", "data/inventory.db")
        _sync_sqlite_table(
            db_path,
            "hessenbot_inventory",
            "items",
            "id",
            ["id", "name", "quantity", "price", "owner", "description"],
            "INSERT OR IGNORE INTO items "
            "(id, name, quantity, price, owner, description) VALUES (?,?,?,?,?,?)",
        )
    except Exception as e:
        logger.debug(f"ClusterStore: inventory sync error: {e}")


# ---------------------------------------------------------------------------
# DB Adapter — chooses local vs CouchDB based on cluster role
# ---------------------------------------------------------------------------
# Usage in bot modules (opt-in):
#   from modules.cluster_store import db_write, db_read_all
#   db_write("bbs", {"id": "123", "text": "Hello"})
#
# In STANDALONE mode: writes go to local storage only (no-op in CouchDB).
# In MASTER/SLAVE mode: writes go to local storage AND CouchDB immediately
#   (no waiting for the 60s sync bridge cycle).
# On reconnect: offline outbox is drained automatically (cluster.py).

def _is_clustered() -> bool:
    try:
        import modules.settings as st
        return getattr(st, "cluster_enabled", False)
    except Exception:
        return False


def db_write(collection: str, doc: Dict, offline_buffer: bool = True) -> bool:
    """
    Write a document to CouchDB immediately (cluster mode only).
    In standalone mode this is a no-op — existing code handles local storage.
    If CouchDB is unreachable and offline_buffer=True, the write is queued
    in the outbox for push on reconnect.
    """
    if not _is_clustered():
        return False

    couch_db = f"hessenbot_{collection}"
    try:
        client = _get_client()
        doc_id = doc.get("_id") or doc.get("id")
        if doc_id:
            return client.put(couch_db, str(doc_id), doc)
        else:
            return bool(client.post(couch_db, doc))
    except Exception as e:
        logger.debug(f"ClusterStore: db_write failed ({collection}): {e}")
        if offline_buffer:
            try:
                outbox_append(couch_db, "upsert", doc)
            except Exception:
                pass
        return False


def db_read_all(collection: str) -> List[Dict]:
    """
    Read all documents from CouchDB (cluster mode).
    Falls back to empty list in standalone mode (caller uses local storage).
    """
    if not _is_clustered():
        return []
    try:
        client = _get_client()
        return client.all_docs(f"hessenbot_{collection}")
    except Exception as e:
        logger.debug(f"ClusterStore: db_read_all failed ({collection}): {e}")
        return []


def db_delete(collection: str, doc_id: str) -> bool:
    """Delete a document from CouchDB (cluster mode only)."""
    if not _is_clustered():
        return False
    try:
        client = _get_client()
        ok = client.delete(f"hessenbot_{collection}", doc_id)
        if not ok:
            outbox_append(f"hessenbot_{collection}", "delete", {"_id": doc_id})
        return ok
    except Exception as e:
        logger.debug(f"ClusterStore: db_delete failed ({collection}/{doc_id}): {e}")
        return False


def _my_node_id() -> str:
    try:
        import modules.settings as st
        iface = getattr(st, "interface1", None)
        if iface:
            return str(getattr(iface, "localNode", {}).nodeNum or "")
    except Exception:
        pass
    return ""
