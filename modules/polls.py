# Einfache Mesh-Umfragen für Hessenbot
# Daten: data/polls.pkl

from __future__ import annotations

import pickle
import time
from datetime import datetime
from typing import Any

from modules.log import logger
from modules.paths import ensure_parent_dir, path_in_repo

trap_list_polls = ("poll",)

POLL_DB_PATH = path_in_repo("data/polls.pkl")
MAX_OPTIONS_DEFAULT = 8

_poll_store: dict[str, Any] = {
    "next_id": 1,
    "polls": {},
}


def _default_store() -> dict[str, Any]:
    return {"next_id": 1, "polls": {}}


def load_polls() -> bool:
    global _poll_store
    try:
        with open(POLL_DB_PATH, "rb") as f:
            data = pickle.load(f)
        if isinstance(data, dict) and isinstance(data.get("polls"), dict):
            _poll_store = data
            if "next_id" not in _poll_store:
                _poll_store["next_id"] = max(
                    (int(k) for k in _poll_store["polls"].keys() if str(k).isdigit()),
                    default=0,
                ) + 1
            return True
    except FileNotFoundError:
        _poll_store = _default_store()
        save_polls()
        return True
    except Exception as e:
        logger.error(f"Polls: load failed: {e}")
        _poll_store = _default_store()
        return False


def save_polls() -> bool:
    try:
        ensure_parent_dir(POLL_DB_PATH)
        with open(POLL_DB_PATH, "wb") as f:
            pickle.dump(_poll_store, f)
        return True
    except Exception as e:
        logger.error(f"Polls: save failed: {e}")
        return False


def list_polls(*, active_only: bool = False) -> list[dict[str, Any]]:
    out = []
    for key, poll in _poll_store.get("polls", {}).items():
        if not isinstance(poll, dict):
            continue
        if active_only and not poll.get("active", True):
            continue
        out.append(poll)
    out.sort(key=lambda p: int(p.get("id", 0)), reverse=True)
    return out


def get_poll(poll_id: int) -> dict[str, Any] | None:
    return _poll_store.get("polls", {}).get(str(int(poll_id)))


def _vote_totals(poll: dict[str, Any]) -> list[int]:
    options = poll.get("options") or []
    votes: dict[str, list] = poll.get("votes") or {}
    return [len(votes.get(str(i), [])) for i in range(len(options))]


def _total_votes(poll: dict[str, Any]) -> int:
    return sum(_vote_totals(poll))


def create_poll(
    title: str,
    question: str,
    options: list[str],
    *,
    active: bool = True,
) -> tuple[bool, str, int | None]:
    import modules.settings as st

    title = (title or "").strip()
    question = (question or "").strip()
    opts = [o.strip() for o in options if o and str(o).strip()]
    max_opt = int(getattr(st, "polls_max_options", MAX_OPTIONS_DEFAULT))

    if not question:
        return False, "Frage darf nicht leer sein.", None
    if len(opts) < 2:
        return False, "Mindestens zwei Antwortoptionen nötig.", None
    if len(opts) > max_opt:
        return False, f"Maximal {max_opt} Optionen erlaubt.", None

    pid = int(_poll_store.get("next_id", 1))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    poll = {
        "id": pid,
        "title": title or question[:60],
        "question": question,
        "options": opts,
        "active": bool(active),
        "created": now,
        "votes": {str(i): [] for i in range(len(opts))},
        "node_choice": {},
    }
    _poll_store["polls"][str(pid)] = poll
    _poll_store["next_id"] = pid + 1
    save_polls()
    logger.info(f"Polls: created #{pid} ({len(opts)} options)")
    return True, f"Umfrage #{pid} angelegt.", pid


def set_poll_active(poll_id: int, active: bool) -> tuple[bool, str]:
    poll = get_poll(poll_id)
    if not poll:
        return False, "Umfrage nicht gefunden."
    poll["active"] = bool(active)
    save_polls()
    state = "aktiviert" if active else "deaktiviert"
    return True, f"Umfrage #{poll_id} {state}."


def reset_poll_votes(poll_id: int) -> tuple[bool, str]:
    poll = get_poll(poll_id)
    if not poll:
        return False, "Umfrage nicht gefunden."
    opts = poll.get("options") or []
    poll["votes"] = {str(i): [] for i in range(len(opts))}
    poll["node_choice"] = {}
    save_polls()
    return True, f"Stimmen für Umfrage #{poll_id} zurückgesetzt."


def delete_poll(poll_id: int) -> tuple[bool, str]:
    key = str(int(poll_id))
    if key not in _poll_store.get("polls", {}):
        return False, "Umfrage nicht gefunden."
    del _poll_store["polls"][key]
    save_polls()
    return True, f"Umfrage #{poll_id} gelöscht."


def cast_vote(poll_id: int, option_1based: int, node_id: int) -> str:
    import modules.settings as st

    poll = get_poll(poll_id)
    if not poll:
        return f"Umfrage #{poll_id} nicht gefunden."
    if not poll.get("active", True):
        return f"Umfrage #{poll_id} ist geschlossen."

    options = poll.get("options") or []
    idx = int(option_1based) - 1
    if idx < 0 or idx >= len(options):
        return f"Option 1–{len(options)} wählen. Beispiel: poll {poll_id} 1"

    nid = str(int(node_id))
    votes: dict[str, list] = poll.setdefault("votes", {})
    node_choice: dict[str, int] = poll.setdefault("node_choice", {})

    prev = node_choice.get(nid)
    if prev is not None and str(prev) in votes:
        old_list = votes[str(prev)]
        if nid in old_list:
            old_list.remove(nid)

    if not getattr(st, "polls_allow_revote", True) and prev is not None:
        return "Du hast bereits abgestimmt. Ändern ist deaktiviert."

    votes.setdefault(str(idx), [])
    if nid not in votes[str(idx)]:
        votes[str(idx)].append(nid)
    node_choice[nid] = idx
    save_polls()

    label = options[idx]
    totals = _vote_totals(poll)
    return (
        f"✅ Stimme für #{poll_id}: {option_1based}) {label}\n"
        f"Stand: {_format_totals_line(totals)}"
    )


def _format_totals_line(totals: list[int]) -> str:
    return " · ".join(str(t) for t in totals) + f" (Σ{sum(totals)})"


def format_poll_detail(poll_id: int, *, node_id: int | None = None) -> str:
    poll = get_poll(poll_id)
    if not poll:
        return f"Umfrage #{poll_id} nicht gefunden."

    options = poll.get("options") or []
    totals = _vote_totals(poll)
    total = sum(totals)
    state = "aktiv" if poll.get("active", True) else "geschlossen"
    lines = [
        f"📊 #{poll['id']} {poll.get('title', '')} ({state})",
        str(poll.get("question", "")),
    ]
    node_choice = poll.get("node_choice") or {}
    my_vote = None
    if node_id is not None:
        my_vote = node_choice.get(str(int(node_id)))

    for i, opt in enumerate(options):
        count = totals[i]
        pct = f" {round(100 * count / total)}%" if total else ""
        mark = " ←du" if my_vote == i else ""
        lines.append(f"{i + 1}) {opt} ({count}{pct}){mark}")

    lines.append(f"Abstimmen: poll {poll_id} <1-{len(options)}>")
    return "\n".join(lines)


def format_poll_list(*, active_only: bool = False) -> str:
    polls = list_polls(active_only=active_only)
    if not polls:
        return "Keine Umfragen." if not active_only else "Keine aktiven Umfragen."

    lines = ["📊 Umfragen:"]
    for p in polls[:15]:
        state = "✓" if p.get("active", True) else "✗"
        total = _total_votes(p)
        q = str(p.get("question", ""))[:50]
        if len(str(p.get("question", ""))) > 50:
            q += "…"
        lines.append(f"#{p['id']} [{state}] {q} ({total} Stimmen)")
    lines.append("Details: poll <Nr>")
    return "\n".join(lines)


def polls_help_text() -> str:
    return (
        "📊 Poll-Hilfe:\n"
        "poll — aktive Umfragen\n"
        "poll liste — alle Umfragen\n"
        "poll <Nr> — Frage & Ergebnis\n"
        "poll <Nr> <Option> — abstimmen (1, 2, …)"
    )


def _poll_message_args(message: str) -> list[str]:
    """Nach dem Befehl poll (ohne !) — z. B. !poll 1 2 → ['1', '2']."""
    parts = (message or "").strip().split()
    if not parts:
        return []
    first = parts[0].lower().lstrip("!")
    if first == "poll":
        return parts[1:]
    if first.startswith("poll") and len(first) > len("poll"):
        return [first[len("poll") :]] + parts[1:]
    return parts


def _parse_poll_number(parts: list[str], index: int = 0) -> tuple[int | None, int]:
    """Parse poll/option number; accepts ``Nr 1`` / ``Nr.1`` help-style input."""
    from modules.system import parse_user_number

    if index >= len(parts):
        return None, index
    combined = parse_user_number(parts[index])
    if combined is not None:
        return combined, index + 1
    if parts[index].lower().startswith("nr") and index + 1 < len(parts):
        combined = parse_user_number(" ".join(parts[index : index + 2]))
        if combined is not None:
            return combined, index + 2
    return None, index


def handle_poll_command(message: str, node_id: int, is_dm: bool = False) -> str:
    if not message:
        return polls_help_text()

    raw = message.strip()
    lower = raw.lower()
    if "?" in raw and (is_dm or lower.rstrip("!").endswith("?")):
        return polls_help_text()

    parts = _poll_message_args(raw)
    if not parts:
        return format_poll_list(active_only=True)

    sub = parts[0].lower()
    if sub in ("liste", "list", "all"):
        return format_poll_list(active_only=False)

    poll_id, next_i = _parse_poll_number(parts, 0)
    if poll_id is None:
        return polls_help_text()

    if next_i >= len(parts):
        return format_poll_detail(poll_id, node_id=node_id)

    option, _ = _parse_poll_number(parts, next_i)
    if option is None:
        return f"Option als Zahl 1–N. Beispiel: poll {poll_id} 1"

    return cast_vote(poll_id, option, node_id)


load_polls()
