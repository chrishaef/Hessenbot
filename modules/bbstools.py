# helper functions for various BBS messaging tasks
# K7MHI Kelly Keeton 2024

import pickle # pip install pickle
import secrets
import time
from datetime import datetime
from typing import Any, Optional

from modules.log import logger
from modules.settings import (
    MESSAGE_CHUNK_SIZE,
    bbs_admin_list,
    bbs_ban_list,
    bbs_link_enabled,
    bbs_link_whitelist,
    responseDelay,
)

useSynchCompression = False

if useSynchCompression:
    import zlib
    from modules.system import send_raw_bytes

trap_list_bbs = ("bbslist", "bbspost", "bbsread", "bbsdelete", "bbshelp", "bbsinfo", "bbslink", "bbsack")

# global message list, later we will use a pickle on disk
bbs_messages = []
bbs_dm = []

BBS_WEB_ADMIN_NODE_ID = 0

# BBS-DM user-ACK states (Issue #9)
DM_STATE_QUEUED = "queued"
DM_STATE_DELIVERING = "delivering"
DM_STATE_AWAITING_USER_ACK = "awaiting_user_ack"
DM_STATE_ACKED = "acked"
DM_STATE_EXPIRED = "expired"
DM_STATE_FAILED = "failed"

_PLACEHOLDER_TO = 1234567890
_PLACEHOLDER_FROM = 1234567890
_PLACEHOLDER_BODY = "Message"


def bbs_party_display_label(node_id, node_int: int = 1) -> str:
    """Anzeigename für BBS-Absender (Dashboard/Admin). Node 0 = Web-Admin."""
    try:
        nid = int(node_id)
    except (TypeError, ValueError):
        return str(node_id) if node_id not in (None, "") else "—"
    if nid == BBS_WEB_ADMIN_NODE_ID:
        from modules.locale_de import BBS_WEB_ADMIN_SENDER

        return BBS_WEB_ADMIN_SENDER

    hex_id = f"!{nid:08x}"
    short = ""
    long_name = ""
    try:
        from modules.system import get_name_from_number

        short = str(get_name_from_number(nid, "short", node_int) or "").strip()
        long_name = str(get_name_from_number(nid, "long", node_int) or "").strip()
    except Exception:
        pass

    def _skip_name(name: str) -> bool:
        if not name:
            return True
        if name in (str(nid), hex_id):
            return True
        if name.startswith("!") and name.lower() == hex_id.lower():
            return True
        return False

    parts: list[str] = []
    if not _skip_name(short):
        parts.append(short)
    if not _skip_name(long_name) and long_name not in parts:
        parts.append(long_name)
    parts.append(hex_id)
    return " · ".join(parts)


def load_bbsdb():
    global bbs_messages
    try:
        with open('data/bbsdb.pkl', 'rb') as f:
            new_bbs_messages = pickle.load(f)
            if isinstance(new_bbs_messages, list):
                for msg in new_bbs_messages:
                    msgHash = hash(tuple(msg[1:3]))
                    if all(hash(tuple(existing_msg[1:3])) != msgHash for existing_msg in bbs_messages):
                        new_id = len(bbs_messages) + 1
                        bbs_messages.append([new_id, msg[1], msg[2], msg[3]])
                return True  # Loaded successfully, regardless of whether new messages were added
            return False # File existed but did not contain a valid list of messages (possibly corrupted)
    except FileNotFoundError:
        # create a new bbsdb.pkl with a welcome message
        # template ([messageID, subject, message, fromNode, now, thread, replyto])
        bbs_messages = [[1, "Willkommen bei Meshhessen-BBS", "Hessenbot-BBS — schreib eine Nachricht mit bbspost!",0,time.strftime('%Y-%m-%d %H:%M:%S'),0,0]]
        logger.debug("System: bbsdb.pkl not found, creating new one")
        try:
            with open('data/bbsdb.pkl', 'wb') as f:
                pickle.dump(bbs_messages, f)
                return True
        except Exception as e:
            logger.error(f"System: Error creating bbsdb.pkl: {e}")
            return False
    except Exception as e:
        logger.error(f"System: Error loading bbsdb.pkl: {e}")
        return False

def save_bbsdb():
    global bbs_messages
    # save the bbs messages to the database file
    try:
        logger.debug("System: Saving data/bbsdb.pkl")
        with open('data/bbsdb.pkl', 'wb') as f:
            pickle.dump(bbs_messages, f)
    except Exception as e:
        logger.error(f"System: Error saving bbsdb: {e}")

def bbs_help():
    # help message
    return (
        "BBS-Befehle:\n"
        "bbslist — Liste\n"
        "bbspost $Betreff #Text\n"
        "bbspost @Knoten #Text (DM)\n"
        "bbspost ack @Knoten #Text (DM+Lesebestätigung)\n"
        "ack <id> — Lesebestätigung\n"
        "bbsread # — lesen\n"
        "bbsdelete # — löschen\n"
        "cmd? — Hilfe"
    )


def _bbs_ack_settings() -> tuple[bool, int, int, int, bool]:
    """Runtime ACK settings (survive settings reload)."""
    try:
        import modules.settings as st

        enabled = bool(getattr(st, "bbs_dm_user_ack_enabled", False))
        retry_s = int(getattr(st, "bbs_dm_ack_retry_seconds", 900) or 900)
        max_att = int(getattr(st, "bbs_dm_ack_max_attempts", 5) or 5)
        expire_s = int(getattr(st, "bbs_dm_ack_expire_seconds", 7200) or 7200)
        notify = bool(getattr(st, "bbs_dm_notify_sender", True))
    except Exception:
        return False, 900, 5, 7200, True
    retry_s = max(60, retry_s)
    max_att = max(1, max_att)
    expire_s = max(retry_s, expire_s)
    return enabled, retry_s, max_att, expire_s, notify


def _alloc_msg_id() -> str:
    existing = {
        str(e.get("msg_id") or "")
        for e in bbs_dm
        if isinstance(e, dict) and e.get("msg_id")
    }
    for _ in range(32):
        mid = secrets.token_hex(2)
        if mid not in existing:
            return mid
    return secrets.token_hex(3)


def _dm_now() -> float:
    return time.time()


def migrate_dm_entry(raw: Any) -> dict:
    """Normalize legacy [to, body, from] triples and partial dicts into DM records."""
    if isinstance(raw, dict):
        entry = dict(raw)
        try:
            entry["to"] = int(entry.get("to", entry.get(0, 0)) or 0)
        except (TypeError, ValueError):
            entry["to"] = 0
        entry["body"] = str(entry.get("body", entry.get("message", "")) or "")
        try:
            entry["from"] = int(entry.get("from", entry.get("fromNode", 0)) or 0)
        except (TypeError, ValueError):
            entry["from"] = 0
    elif isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            to_n = int(raw[0])
        except (TypeError, ValueError):
            to_n = 0
        try:
            from_n = int(raw[2])
        except (TypeError, ValueError):
            from_n = 0
        entry = {"to": to_n, "body": str(raw[1] or ""), "from": from_n}
    else:
        entry = {"to": 0, "body": "", "from": 0}

    entry.setdefault("require_user_ack", False)
    entry["require_user_ack"] = bool(entry.get("require_user_ack"))
    entry.setdefault("state", DM_STATE_QUEUED)
    entry.setdefault("created_at", _dm_now())
    entry.setdefault("last_attempt_at", None)
    entry.setdefault("attempt_count", 0)
    if "mesh_acked" not in entry:
        entry["mesh_acked"] = None
    entry.setdefault("user_acked", False)
    entry["user_acked"] = bool(entry.get("user_acked"))
    if not entry.get("msg_id"):
        entry["msg_id"] = _alloc_msg_id() if entry.get("require_user_ack") else ""
    entry.setdefault("notify_sender", True)
    entry.setdefault("notified_unknown_target", False)
    entry.setdefault("placeholder", False)
    return entry


def make_placeholder_dm() -> dict:
    return {
        "to": _PLACEHOLDER_TO,
        "body": _PLACEHOLDER_BODY,
        "from": _PLACEHOLDER_FROM,
        "require_user_ack": False,
        "state": DM_STATE_QUEUED,
        "created_at": 0.0,
        "last_attempt_at": None,
        "attempt_count": 0,
        "mesh_acked": None,
        "user_acked": False,
        "msg_id": "",
        "notify_sender": False,
        "notified_unknown_target": False,
        "placeholder": True,
    }


def is_placeholder_dm(entry: Any, index: int = -1) -> bool:
    if index == 0:
        return True
    if isinstance(entry, dict) and entry.get("placeholder"):
        return True
    if isinstance(entry, (list, tuple)) and len(entry) >= 3:
        try:
            return int(entry[0]) == _PLACEHOLDER_TO and str(entry[1]) == _PLACEHOLDER_BODY
        except (TypeError, ValueError):
            return False
    return False


def dm_to(entry: Any) -> int:
    if isinstance(entry, dict):
        try:
            return int(entry.get("to") or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(entry, (list, tuple)) and len(entry) >= 1:
        try:
            return int(entry[0])
        except (TypeError, ValueError):
            return 0
    return 0


def dm_body(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("body") or "")
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return str(entry[1] or "")
    return ""


def dm_from(entry: Any) -> int:
    if isinstance(entry, dict):
        try:
            return int(entry.get("from") or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(entry, (list, tuple)) and len(entry) >= 3:
        try:
            return int(entry[2])
        except (TypeError, ValueError):
            return 0
    return 0


def dm_require_user_ack(entry: Any) -> bool:
    if isinstance(entry, dict):
        return bool(entry.get("require_user_ack"))
    return False


def dm_state(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("state") or DM_STATE_QUEUED)
    return DM_STATE_QUEUED


def dm_msg_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("msg_id") or "")
    return ""


def node_known_in_nodedb(node_id: int) -> bool:
    """True when target appears in persistent NodeDB or a live interface NodeDB."""
    try:
        nid = int(node_id)
    except (TypeError, ValueError):
        return False
    if nid <= 0:
        return False
    try:
        import modules.nodedb as ndb

        if ndb.get_node(nid):
            return True
    except Exception:
        pass
    try:
        from modules.system import _interface_node

        for iface in range(1, 10):
            if _interface_node(nid, iface) is not None:
                return True
    except Exception:
        pass
    return False


def _notify_sender(entry: dict, text: str, device_id: int = 1) -> None:
    _, _, _, _, notify_default = _bbs_ack_settings()
    if "notify_sender" in entry:
        if not entry.get("notify_sender"):
            return
    elif not notify_default:
        return
    from_n = dm_from(entry)
    if from_n <= 0:
        logger.info(f"System: BBS DM status (web/no-mesh sender): {text}")
        return
    try:
        from modules.system import send_message

        send_message(text, 0, from_n, device_id)
    except Exception as e:
        logger.debug(f"System: BBS DM sender notify failed: {e}")


def _ensure_dm_list_normalized() -> None:
    global bbs_dm
    if not bbs_dm:
        bbs_dm = [make_placeholder_dm()]
        return
    for idx, raw in enumerate(bbs_dm):
        # Keep existing normalized dicts in place (preserve object identity for hooks)
        if (
            isinstance(raw, dict)
            and "to" in raw
            and "body" in raw
            and "from" in raw
            and "state" in raw
        ):
            if idx == 0:
                raw["placeholder"] = True
            raw.setdefault("require_user_ack", False)
            raw.setdefault("msg_id", "")
            raw.setdefault("attempt_count", 0)
            raw.setdefault("mesh_acked", None)
            raw.setdefault("user_acked", False)
            continue
        if is_placeholder_dm(raw, idx) and idx == 0:
            bbs_dm[idx] = make_placeholder_dm()
        else:
            entry = migrate_dm_entry(raw)
            if idx == 0:
                entry["placeholder"] = True
            bbs_dm[idx] = entry
    if not is_placeholder_dm(bbs_dm[0], 0):
        bbs_dm.insert(0, make_placeholder_dm())

def bbs_list_messages():
    #print (f"System: raw bbs_messages: {bbs_messages}")
    # return a string with new line for each message subject in the list bbs_messages
    message_list = ""
    for message in bbs_messages:
        # message[0] is the messageID, message[1] is the subject
        message_list += "[#" + str(message[0]) + "] " + message[1] + "\n"

    # last newline removed
    message_list = message_list[:-1]
    return message_list

def bbs_delete_message(messageID = 0, fromNode = 0):
    #if messageID out of range ignore
    if (messageID - 1) >= len(bbs_messages):
        return "Nachricht nicht gefunden."
    
    # delete a message from the bbsdb
    if messageID > 0:
        # if same user wrote message they can delete it
        if fromNode == bbs_messages[messageID - 1][3] or str(fromNode) in bbs_admin_list:
            bbs_messages.pop(messageID - 1)
            # reset the messageID
            for i in range(len(bbs_messages)):
                bbs_messages[i][0] = i + 1

            # save the bbsdb
            save_bbsdb()
            
            return "Nachricht #" + str(messageID) + " gelöscht."
        else:
            logger.warning(f"System: node {fromNode}, tried to delete a message: {bbs_messages[messageID - 1]} and was dropped.")
            return "Du darfst diese Nachricht nicht löschen."
    else:
        return "Bitte Nachrichtennummer angeben (bbsdelete #)."


def bbs_delete_message_system(message_id: int):
    """
    Remove a public BBS message by 1-based ID without author check (trusted: web admin).
    Renumbers message IDs and saves data/bbsdb.pkl.
    """
    global bbs_messages
    if message_id < 1 or message_id > len(bbs_messages):
        return False, "Nachricht nicht gefunden."
    bbs_messages.pop(message_id - 1)
    for i in range(len(bbs_messages)):
        bbs_messages[i][0] = i + 1
    save_bbsdb()
    logger.info(f"System: BBS message #{message_id} removed via web admin")
    return True, f"Nachricht #{message_id} gelöscht."


def bbs_post_message(subject, message, fromNode, threadID=0, replytoID=0):
    # post a message to the bbsdb
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    thread = threadID
    replyto = replytoID
    # post a message to the bbsdb and assign a messageID
    messageID = len(bbs_messages) + 1

    # Check the BAN list for naughty nodes and silently drop the message
    if str(fromNode) in bbs_ban_list:
        logger.warning(f"System: Naughty node {fromNode}, tried to post a message: {subject}, {message} and was dropped.")
        return "Nachricht gespeichert. ID: " + str(messageID)
    # validate message length isnt three times the MESSAGE_CHUNK_SIZE
    if len(message) > (3 * MESSAGE_CHUNK_SIZE):
        return "Nachricht zu lang, max. " + str(3 * MESSAGE_CHUNK_SIZE) + " Zeichen."
    # validate not a duplicate message
    for msg in bbs_messages:
        if msg[1].strip().lower() == subject.strip().lower() and msg[2].strip().lower() == message.strip().lower():
            messageID = msg[0]
            return "Nachricht gespeichert. ID: " + str(messageID)
    # validate its not overlength by keeping in chunker limit
    # append the message to the list
    bbs_messages.append([messageID, subject, message, fromNode, now, thread, replyto])
    logger.info(f"System: NEW Message Posted, subject: {subject}, message: {message} from {fromNode}")

    # save the bbsdb
    save_bbsdb()

    return "Nachricht gespeichert. ID: " + str(messageID)

def bbs_read_message(messageID = 0):
    #if messageID out of range ignore
    if (messageID - 1) >= len(bbs_messages):
        return "Nachricht nicht gefunden."
    if messageID > 0:
        fromNode = bbs_messages[messageID - 1][3]
        fromNodeHex = hex(fromNode)[-4:]
        message = bbs_messages[messageID - 1]
        return f"#{message[0]}\nVon:{fromNodeHex}\n{message[2]}"
    else:
        return "Bitte Nachrichtennummer angeben (bbsread #)."
   
def save_bbsdm():
    global bbs_dm
    _ensure_dm_list_normalized()
    logger.debug("System: Saving Updated BBS Direct Messages data/bbsdm.pkl")
    with open('data/bbsdm.pkl', 'wb') as f:
        pickle.dump(bbs_dm, f)

def load_bbsdm():
    """Load/migrate bbsdm.pkl. Empty memory → full load; else merge new rows (bbsAPI)."""
    global bbs_dm
    try:
        with open('data/bbsdm.pkl', 'rb') as f:
            new_bbs_dm = pickle.load(f)
        if not isinstance(new_bbs_dm, list):
            return
        migrated = [migrate_dm_entry(m) for m in new_bbs_dm]
        if not bbs_dm:
            bbs_dm = migrated
            _ensure_dm_list_normalized()
            return
        existing_ids = {dm_msg_id(m) for m in bbs_dm if dm_msg_id(m)}
        existing_tb = {
            (dm_to(m), dm_body(m).strip().lower(), dm_from(m))
            for m in bbs_dm
        }
        changed = False
        for idx, entry in enumerate(migrated):
            if is_placeholder_dm(entry, idx):
                continue
            mid = dm_msg_id(entry)
            if mid and mid in existing_ids:
                continue
            key = (dm_to(entry), dm_body(entry).strip().lower(), dm_from(entry))
            if key in existing_tb:
                continue
            bbs_dm.append(entry)
            if mid:
                existing_ids.add(mid)
            existing_tb.add(key)
            changed = True
        _ensure_dm_list_normalized()
        if changed:
            logger.debug("System: bbsdm.pkl merge added new DM row(s)")
        return
    except Exception as e:
        logger.debug(f"System: Creating new data/bbsdm.pkl ({e})")
    if not bbs_dm:
        bbs_dm = [make_placeholder_dm()]
        try:
            with open('data/bbsdm.pkl', 'wb') as f:
                pickle.dump(bbs_dm, f)
        except Exception as err:
            logger.error(f"System: Error creating bbsdm.pkl: {err}")


def bbs_post_dm(toNode, message, fromNode, require_user_ack: bool = False):
    """Queue a BBS DM. require_user_ack enables Lesebestätigung (Issue #9)."""
    global bbs_dm
    _ensure_dm_list_normalized()
    ack_enabled, _, _, _, notify_default = _bbs_ack_settings()

    if str(fromNode) in bbs_ban_list:
        logger.warning(f"System: Naughty node {fromNode}, tried to post a message: {message} and was dropped.")
        return "DM für Knoten " + str(toNode) + " gespeichert."

    if len(message) > (3 * MESSAGE_CHUNK_SIZE):
        return "Nachricht zu lang, max. " + str(3 * MESSAGE_CHUNK_SIZE) + " Zeichen."

    want_ack = bool(require_user_ack)
    if want_ack and not ack_enabled:
        return (
            "Lesebestätigung ist deaktiviert (bbsDmUserAckEnabled=False). "
            "Nutze bbspost @Knoten #Text ohne ack."
        )

    to_i = int(toNode)
    from_i = int(fromNode)
    body = str(message)

    for msg in bbs_dm[1:]:
        if dm_to(msg) == to_i and dm_body(msg).strip().lower() == body.strip().lower():
            if want_ack and not dm_require_user_ack(msg):
                continue
            if not want_ack and dm_require_user_ack(msg):
                continue
            mid = dm_msg_id(msg)
            if want_ack and mid:
                return f"BBS-DM (ACK) für Knoten {to_i} bereits gespeichert. ID {mid}"
            return "DM für Knoten " + str(to_i) + " gespeichert."

    entry = migrate_dm_entry({
        "to": to_i,
        "body": body,
        "from": from_i,
        "require_user_ack": want_ack,
        "state": DM_STATE_QUEUED,
        "created_at": _dm_now(),
        "last_attempt_at": None,
        "attempt_count": 0,
        "mesh_acked": None,
        "user_acked": False,
        "msg_id": _alloc_msg_id() if want_ack else "",
        "notify_sender": notify_default,
        "notified_unknown_target": False,
        "placeholder": False,
    })
    bbs_dm.append(entry)
    save_bbsdm()

    mid = entry.get("msg_id") or ""
    logger.info(
        f"System: BBS DM Queued: from={from_i} to={to_i} "
        f"ack={want_ack} msg_id={mid or '-'}"
    )

    if want_ack:
        reply = f"BBS-DM (ACK) für Knoten {to_i} gespeichert. ID {mid}"
        _notify_sender(
            entry,
            f"BBS-DM eingereiht an {to_i}, Lesebestätigung ja, ID {mid}",
        )
    else:
        reply = "BBS-DM für Knoten " + str(to_i) + " gespeichert."
        _notify_sender(entry, f"BBS-DM eingereiht an {to_i}, Lesebestätigung nein")

    if not node_known_in_nodedb(to_i):
        entry["notified_unknown_target"] = True
        save_bbsdm()
        _notify_sender(entry, f"Ziel {to_i} noch nicht in NodeDB — warte.")

    return reply


def get_bbs_stats():
    global bbs_messages, bbs_dm
    _ensure_dm_list_normalized()
    pending = max(0, len(bbs_dm) - 1)
    return f"📡 BBS: {len(bbs_messages)} Nachrichten.\n✉️ Wartende DMs: {pending}"


def bbs_check_dm(toNode):
    """Return the next deliverable DM record for toNode, or False.

    Legacy callers may index the result like a triple; dicts also support
    that via helpers. Prefer dm_to/dm_body/dm_from.
    """
    global bbs_dm
    _ensure_dm_list_normalized()
    try:
        target = int(toNode)
    except (TypeError, ValueError):
        return False
    for idx, msg in enumerate(bbs_dm):
        if is_placeholder_dm(msg, idx):
            continue
        if dm_to(msg) != target:
            continue
        state = dm_state(msg)
        if state == DM_STATE_QUEUED:
            return msg
        if state == DM_STATE_AWAITING_USER_ACK and dm_require_user_ack(msg):
            # Packet sighting can complement retries; only when due
            if _retry_due(msg):
                return msg
    return False


def bbs_delete_dm(toNode, message):
    global bbs_dm
    _ensure_dm_list_normalized()
    try:
        target = int(toNode)
    except (TypeError, ValueError):
        return "System: No DM found for node " + str(toNode)
    for idx, msg in enumerate(list(bbs_dm)):
        if is_placeholder_dm(msg, idx):
            continue
        if dm_to(msg) == target and dm_body(msg) == message:
            bbs_dm.remove(msg)
            save_bbsdm()
            return "System: cleared mail for" + str(toNode)
    return "System: No DM found for node " + str(toNode)


def bbs_delete_dm_at_index(index: int):
    """
    Remove one row from bbs_dm by list index (trusted: web admin).
    Index 0 is reserved (placeholder / stats convention); cannot be removed.
    """
    global bbs_dm
    _ensure_dm_list_normalized()
    if index < 0 or index >= len(bbs_dm):
        return False, "Eintrag nicht gefunden."
    if index == 0 or is_placeholder_dm(bbs_dm[index], index):
        return False, "Der erste Eintrag ist reserviert (interner Platzhalter) und kann nicht gelöscht werden."
    bbs_dm.pop(index)
    if len(bbs_dm) == 0:
        bbs_dm.append(make_placeholder_dm())
        logger.debug("System: bbs_dm was empty after delete; restored placeholder row")
    _ensure_dm_list_normalized()
    save_bbsdm()
    logger.info(f"System: BBS DM row {index} removed via web admin")
    return True, "DM-Eintrag gelöscht."


def _retry_due(entry: dict, now: Optional[float] = None) -> bool:
    _, retry_s, _, _, _ = _bbs_ack_settings()
    now = _dm_now() if now is None else now
    last = entry.get("last_attempt_at")
    if last is None:
        return True
    try:
        return (now - float(last)) >= retry_s
    except (TypeError, ValueError):
        return True


def _is_expired(entry: dict, now: Optional[float] = None) -> bool:
    _, _, max_att, expire_s, _ = _bbs_ack_settings()
    now = _dm_now() if now is None else now
    try:
        created = float(entry.get("created_at") or now)
    except (TypeError, ValueError):
        created = now
    attempts = int(entry.get("attempt_count") or 0)
    if attempts >= max_att:
        return True
    if (now - created) >= expire_s:
        return True
    return False


def _format_mail_body(entry: dict, device_id: int = 1) -> str:
    from_n = dm_from(entry)
    try:
        from modules.system import get_name_from_number

        from_name = get_name_from_number(from_n, "long", device_id)
    except Exception:
        from_name = str(from_n)
    text = f"Mail: {dm_body(entry)}  From: {from_name}"
    if dm_require_user_ack(entry):
        mid = dm_msg_id(entry) or "?"
        text += f"\nBitte bestätigen: ack {mid}"
    return text


def _send_dm_to_recipient(entry: dict, device_id: int, channel: int = 0) -> bool:
    try:
        from modules.system import send_message

        return bool(send_message(_format_mail_body(entry, device_id), channel, dm_to(entry), device_id))
    except Exception as e:
        logger.error(f"System: BBS DM send failed: {e}")
        return False


def bbs_deliver_entry(entry: dict, device_id: int = 1, channel: int = 0, *, force: bool = False) -> str:
    """Deliver one DM entry. ACK-mails stay queued; normal mails are removed after send."""
    global bbs_dm
    if entry not in bbs_dm:
        return "not_found"
    if is_placeholder_dm(entry, bbs_dm.index(entry) if entry in bbs_dm else -1):
        return "placeholder"

    now = _dm_now()
    to_n = dm_to(entry)
    want_ack = dm_require_user_ack(entry)

    if want_ack and _is_expired(entry, now):
        mid = dm_msg_id(entry) or "?"
        entry["state"] = DM_STATE_EXPIRED
        _notify_sender(entry, f"BBS-DM abgelaufen: ID {mid} an {to_n}", device_id)
        try:
            bbs_dm.remove(entry)
        except ValueError:
            pass
        save_bbsdm()
        return "expired"

    if want_ack and not force and dm_state(entry) == DM_STATE_AWAITING_USER_ACK and not _retry_due(entry, now):
        return "wait_retry"

    if not node_known_in_nodedb(to_n) and not force:
        if want_ack and not entry.get("notified_unknown_target"):
            entry["notified_unknown_target"] = True
            save_bbsdm()
            _notify_sender(entry, f"Ziel {to_n} noch nicht in NodeDB — warte.", device_id)
        return "unknown_target"

    entry["state"] = DM_STATE_DELIVERING
    entry["attempt_count"] = int(entry.get("attempt_count") or 0) + 1
    entry["last_attempt_at"] = now
    attempt = entry["attempt_count"]
    _, _, max_att, _, _ = _bbs_ack_settings()
    mid = dm_msg_id(entry) or "-"
    save_bbsdm()

    if want_ack:
        _notify_sender(
            entry,
            f"Zustellversuch #{attempt}/{max_att} (ID {mid}) an {to_n}",
            device_id,
        )
        if attempt > 1:
            _notify_sender(entry, f"Retry {attempt}/{max_att} für ID {mid}", device_id)

    ok = _send_dm_to_recipient(entry, device_id, channel)
    if not want_ack:
        # Legacy behaviour: remove after send attempt
        try:
            bbs_dm.remove(entry)
        except ValueError:
            pass
        save_bbsdm()
        if ok:
            _notify_sender(entry, f"BBS-DM zugestellt an {to_n}", device_id)
        return "delivered" if ok else "send_failed"

    entry["state"] = DM_STATE_AWAITING_USER_ACK
    # mesh_acked stays None until mesh callback; unknown is fine
    save_bbsdm()
    logger.info(
        f"System: BBS DM Delivery (ACK pending): from={dm_from(entry)} to={to_n} "
        f"msg_id={mid} attempt={attempt}"
    )
    return "awaiting_user_ack" if ok else "send_failed"


def bbs_try_deliver_for_node(to_node: int, device_id: int = 1, channel: int = 0) -> Optional[str]:
    """Packet/NodeDB trigger: deliver next eligible DM for this node."""
    _ensure_dm_list_normalized()
    try:
        target = int(to_node)
    except (TypeError, ValueError):
        return None
    for idx, msg in enumerate(bbs_dm):
        if is_placeholder_dm(msg, idx):
            continue
        if dm_to(msg) != target:
            continue
        state = dm_state(msg)
        if state == DM_STATE_QUEUED:
            return bbs_deliver_entry(msg, device_id, channel)
        if state == DM_STATE_AWAITING_USER_ACK and dm_require_user_ack(msg) and _retry_due(msg):
            return bbs_deliver_entry(msg, device_id, channel)
    return None


def bbs_ack_maintenance_tick(device_id: int = 1) -> None:
    """Periodic: expire ACK-mails, first delivery / retry when target in NodeDB."""
    if not bbs_dm:
        return
    ack_enabled, _, _, _, _ = _bbs_ack_settings()
    _ensure_dm_list_normalized()
    now = _dm_now()
    # Snapshot to allow mutation while iterating
    for idx, msg in list(enumerate(bbs_dm)):
        if is_placeholder_dm(msg, idx):
            continue
        if not isinstance(msg, dict):
            continue
        if not dm_require_user_ack(msg):
            # Normal queued DMs: deliver once target is known
            if dm_state(msg) == DM_STATE_QUEUED and node_known_in_nodedb(dm_to(msg)):
                bbs_deliver_entry(msg, device_id, 0)
            continue
        if not ack_enabled:
            continue
        if _is_expired(msg, now):
            mid = dm_msg_id(msg) or "?"
            to_n = dm_to(msg)
            msg["state"] = DM_STATE_EXPIRED
            _notify_sender(msg, f"BBS-DM abgelaufen: ID {mid} an {to_n}", device_id)
            try:
                bbs_dm.remove(msg)
            except ValueError:
                pass
            save_bbsdm()
            continue
        state = dm_state(msg)
        if state == DM_STATE_QUEUED and node_known_in_nodedb(dm_to(msg)):
            bbs_deliver_entry(msg, device_id, 0)
        elif state == DM_STATE_AWAITING_USER_ACK and _retry_due(msg, now) and node_known_in_nodedb(dm_to(msg)):
            bbs_deliver_entry(msg, device_id, 0)


def bbs_pending_user_acks_for(node_id: int) -> list[dict]:
    """ACK-pflichtige Mails, die der Empfänger bestätigen darf (nur nach Zustellung)."""
    _ensure_dm_list_normalized()
    try:
        target = int(node_id)
    except (TypeError, ValueError):
        return []
    out: list[dict] = []
    for idx, msg in enumerate(bbs_dm):
        if is_placeholder_dm(msg, idx):
            continue
        if not dm_require_user_ack(msg):
            continue
        if dm_to(msg) != target:
            continue
        # Flow: ack <id> erst im State awaiting_user_ack (nicht queued/delivering)
        if dm_state(msg) == DM_STATE_AWAITING_USER_ACK:
            out.append(msg)
    return out


def bbs_handle_user_ack(from_node: int, msg_id: Optional[str] = None, device_id: int = 1) -> Optional[str]:
    """Process recipient `ack` / `ack <id>`. Returns DE reply or None if not a BBS ACK."""
    ack_enabled, _, _, _, _ = _bbs_ack_settings()
    if not ack_enabled:
        return None
    pending = bbs_pending_user_acks_for(from_node)
    if not pending:
        return None

    mid = (msg_id or "").strip().lower()
    target: Optional[dict] = None
    if mid:
        for msg in pending:
            if dm_msg_id(msg).lower() == mid:
                target = msg
                break
        if target is None:
            # Explicit id that doesn't match — still a BBS ack attempt
            return f"Keine wartende Lesebestätigung mit ID {mid}."
    else:
        if len(pending) != 1:
            ids = ", ".join(dm_msg_id(m) or "?" for m in pending)
            return f"Mehrere wartende Mails — bitte ack <id> angeben ({ids})."
        target = pending[0]

    target["user_acked"] = True
    target["state"] = DM_STATE_ACKED
    mid_ok = dm_msg_id(target) or "?"
    to_n = dm_to(target)
    _notify_sender(
        target,
        f"Nutzer bestätigt: ID {mid_ok} von Empfänger {from_node}",
        device_id,
    )
    try:
        bbs_dm.remove(target)
    except ValueError:
        pass
    save_bbsdm()
    logger.info(f"System: BBS DM user-ACK from={from_node} msg_id={mid_ok}")
    return f"Danke — Lesebestätigung für ID {mid_ok} gespeichert."


def parse_ack_command(message: str) -> tuple[bool, Optional[str]]:
    """Return (is_ack_command, msg_id_or_None). Bare ack → (True, None)."""
    words = (message or "").strip().split()
    if not words:
        return False, None
    first = words[0].lstrip("!").lower()
    if first.endswith("?"):
        first = first[:-1]
    if first != "ack":
        return False, None
    if len(words) == 1:
        return True, None
    # ping-style "ack @node" is not user-ACK
    if words[1].startswith("@") or words[1].startswith("#"):
        return False, None
    return True, words[1].strip()


def bbs_on_mesh_delivery_result(dest_node: int, success: bool, device_id: int = 1) -> None:
    """Mesh/wantAck callback: Node-Empfang bestätigt vs. fehlgeschlagen (ACK-mails only)."""
    _ensure_dm_list_normalized()
    try:
        target = int(dest_node)
    except (TypeError, ValueError):
        return
    for idx, msg in enumerate(bbs_dm):
        if is_placeholder_dm(msg, idx):
            continue
        if not dm_require_user_ack(msg):
            continue
        if dm_to(msg) != target:
            continue
        if dm_state(msg) not in (DM_STATE_AWAITING_USER_ACK, DM_STATE_DELIVERING):
            continue
        # Only update once from None, or on change
        prev = msg.get("mesh_acked")
        msg["mesh_acked"] = bool(success)
        save_bbsdm()
        mid = dm_msg_id(msg) or "?"
        if success and prev is not True:
            _notify_sender(msg, f"Node-Empfang bestätigt (ID {mid})", device_id)
        elif not success and prev is not False:
            _notify_sender(msg, f"Node-Empfang fehlgeschlagen/offen (ID {mid})", device_id)
        break


def bbs_admin_redeliver(index: int, device_id: int = 1) -> tuple[bool, str]:
    _ensure_dm_list_normalized()
    if index <= 0 or index >= len(bbs_dm):
        return False, "Eintrag nicht gefunden."
    entry = bbs_dm[index]
    entry["last_attempt_at"] = None
    if dm_state(entry) in (DM_STATE_EXPIRED, DM_STATE_ACKED, DM_STATE_FAILED):
        entry["state"] = DM_STATE_QUEUED
    result = bbs_deliver_entry(entry, device_id, 0, force=True)
    return True, f"Erneute Zustellung: {result}"


def bbs_admin_mark_done(index: int, device_id: int = 1) -> tuple[bool, str]:
    _ensure_dm_list_normalized()
    if index <= 0 or index >= len(bbs_dm):
        return False, "Eintrag nicht gefunden."
    entry = bbs_dm[index]
    mid = dm_msg_id(entry) or "?"
    entry["state"] = DM_STATE_ACKED
    entry["user_acked"] = True
    _notify_sender(entry, f"BBS-DM manuell erledigt: ID {mid}", device_id)
    bbs_dm.pop(index)
    if len(bbs_dm) == 0:
        bbs_dm.append(make_placeholder_dm())
    save_bbsdm()
    return True, f"DM ID {mid} als erledigt markiert."


def bbs_dm_status_label(entry: Any) -> str:
    if not isinstance(entry, dict):
        return "queued"
    st = dm_state(entry)
    labels = {
        DM_STATE_QUEUED: "wartend",
        DM_STATE_DELIVERING: "zustellung",
        DM_STATE_AWAITING_USER_ACK: "warte auf Nutzer-ACK",
        DM_STATE_ACKED: "bestätigt",
        DM_STATE_EXPIRED: "abgelaufen",
        DM_STATE_FAILED: "fehlgeschlagen",
    }
    return labels.get(st, st)


def compress_data(data_to_compress):
    # Prepare message as bytes
    compressed = zlib.compress(data_to_compress.encode('utf-8'))
    return compressed

def decompress_data(data_bytes):
    try:
        decompressed = zlib.decompress(data_bytes)
        msg = decompressed.decode('utf-8')
        return msg
    except Exception as e:
        logger.warning(f"Error decompressing data: {e}")
        return False

def bbs_receive_compressed(data_bytes, fromNode, RxNode):
    try:
        decompressed = zlib.decompress(data_bytes)
        msg = decompressed.decode('utf-8')
        
        bbs_sync_posts(msg, fromNode, RxNode)

        return msg
    except Exception as e:
        logger.error(f"Error decompressing BBS message: {e}")
        return None

def bbs_sync_posts(input, peerNode, RxNode):
    messageID =  0

    # check if the bbs link is enabled
    if bbs_link_whitelist != ['']:
        if str(peerNode) not in bbs_link_whitelist:
            logger.warning(f"System: BBS Link is disabled for node {peerNode}.")
            return "System: BBS Link is disabled for your node."
    if bbs_link_enabled == False:
        return "System: BBS Link is disabled."
    
    # respond when another bot asks for the bbs posts to sync
    if "bbslink" in input.lower():
        if "$" in input and "#" in input:
            #store the message
            subject = input.split("$")[1].split("#")[0]
            body = input.split("#")[1]
            fromNodeHex = body.split("@")[1]
            #validate the fromNodeHex is a valid hex number
            try:
                int(fromNodeHex, 16)
            except ValueError:
                logger.error(f"System: Invalid fromNodeHex in bbslink from node {peerNode}: {input}")
                fromNodeHex = hex(peerNode)
            #validate the subject and body are not empty
            if subject.strip() == "" or body.strip() == "":
                logger.error(f"System: Empty subject or body in bbslink from node {peerNode}: {input}")
                return "System: Invalid bbslink format."
            
            #store the message in the bbsdb
            try:
                bbs_post_message(subject, body, int(fromNodeHex, 16))
            except Exception as e:
                logger.error(f"System: Error parsing bbslink from node {peerNode}: {input} ({e})")
                fromNodeHex = hex(peerNode)
            messageID = input.split(" ")[1]
            return f"bbsack {messageID}"
    elif "bbsack" in input.lower():
        # increment the messageID
        if len(input.split(" ")) > 1:
            try:
                messageID = int(input.split(" ")[1]) + 1
            except Exception as e:
                logger.error(f"System: Error parsing bbsack from node {peerNode}: {input} ({e})")
                return "link error"
        else:
            return "link error"

    # send message with delay to keep chutil happy
    if messageID < len(bbs_messages):
        logger.debug(f"System: wait to bbslink with peer " + str(peerNode))
        fromNodeHex = hex(bbs_messages[messageID][3])
        time.sleep(5 + responseDelay)
        # every 5 messages add extra delay
        if messageID % 5 == 0:
            time.sleep(10 + responseDelay)
        logger.debug(f"System: Sending bbslink message {messageID} of {len(bbs_messages)} to peer " + str(peerNode))
        msg = f"bbslink {messageID} ${bbs_messages[messageID][1]} #{bbs_messages[messageID][2]} @{fromNodeHex}"
        if useSynchCompression:
            compressed = compress_data(msg)
            send_raw_bytes(peerNode, compressed)
            logger.debug("System: Sent compressed bbslink message to peer " + str(peerNode))
        else:
            return msg
    else:
        logger.debug("System: bbslink sync complete with peer " + str(peerNode))


#initialize the bbsdb's
load_bbsdb()
load_bbsdm()
