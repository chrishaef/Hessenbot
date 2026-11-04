# Command rate limiting / expensive-command cooldowns (mesh airtime protection).
# Kept free of radio/meshtastic imports so unit tests stay lightweight.

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_cmd_rate_tracker: dict = {}
_cmd_rate_notified: dict = {}
_cmd_expensive_last: dict = {}
_cmd_expensive_notified: dict = {}
_unknown_dm_hint_last: dict = {}

_DEFAULT_EXPENSIVE_COMMANDS = (
    "wx,wxc,warning,dealert,blitz,uv,regen,trace,whereami,rlist,satpass,tide,river,earthquake"
)

# Cooldown between "unknown command" DM hints per node (seconds)
UNKNOWN_DM_HINT_COOLDOWN_SEC = 300


def extract_command_token(message: str) -> str:
    """First command word without leading ! or trailing ?."""
    parts = (message or "").strip().lstrip("!").split()
    if not parts:
        return ""
    return parts[0].lower().rstrip("?").strip()


def _settings():
    import modules.settings as st

    return st


def _expensive_command_set() -> set:
    st = _settings()
    raw = getattr(st, "cmdExpensiveCommands", _DEFAULT_EXPENSIVE_COMMANDS)
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = str(raw or _DEFAULT_EXPENSIVE_COMMANDS).split(",")
    return {str(x).strip().lower().rstrip("?") for x in items if str(x).strip()}


def check_command_throttle(
    node_id,
    command_token: Optional[str] = None,
    *,
    is_admin: Optional[Callable[[str], bool]] = None,
):
    """Airtime throttle for mesh commands.

    Returns:
      None  — allowed
      ""    — over limit, stay silent (no mesh reply)
      str   — send this short message once, then skip auto-response
    """
    st = _settings()
    node_key = str(node_id)
    if is_admin is not None:
        if is_admin(node_key):
            return None
    else:
        try:
            from modules.system import isNodeAdmin

            if isNodeAdmin(node_key):
                return None
        except Exception:
            pass

    now = time.time()
    cmd = (command_token or "").strip().lower().rstrip("?")

    if getattr(st, "cmdRateLimitEnabled", True):
        window = max(1, int(getattr(st, "cmdRateLimitWindow", 60) or 60))
        max_cmds = max(1, int(getattr(st, "cmdRateLimitMax", 3) or 3))
        cutoff = now - window
        timestamps = [t for t in _cmd_rate_tracker.get(node_key, []) if t > cutoff]
        timestamps.append(now)
        _cmd_rate_tracker[node_key] = timestamps
        if len(timestamps) > max_cmds:
            logger.warning(
                f"System: Rate limit hit for node {node_key} "
                f"({len(timestamps)} cmds in {window}s)"
            )
            if getattr(st, "cmdRateLimitNotifyOnce", True):
                last_notify = float(_cmd_rate_notified.get(node_key, 0) or 0)
                if last_notify > cutoff:
                    return ""
                _cmd_rate_notified[node_key] = now
            return "⏱️ Bitte etwas langsamer."

    cooldown = int(getattr(st, "cmdExpensiveCooldownSec", 45) or 0)
    if cooldown > 0 and cmd and cmd in _expensive_command_set():
        key = (node_key, cmd)
        last = float(_cmd_expensive_last.get(key, 0) or 0)
        if last and (now - last) < cooldown:
            remaining = max(1, int(cooldown - (now - last) + 0.999))
            last_n = float(_cmd_expensive_notified.get(key, 0) or 0)
            if last_n >= last:
                logger.debug(
                    f"System: Expensive cooldown silent node={node_key} cmd={cmd} "
                    f"remaining={remaining}s"
                )
                return ""
            _cmd_expensive_notified[key] = now
            logger.warning(
                f"System: Expensive cooldown node={node_key} cmd={cmd} "
                f"remaining={remaining}s"
            )
            return f"⏱️ !{cmd} erst in {remaining}s wieder."
        _cmd_expensive_last[key] = now

    return None


def take_unknown_dm_hint(node_id, cooldown_sec: Optional[int] = None) -> Optional[str]:
    """Return unknown-command hint text if cooldown elapsed; else None (stay silent)."""
    from modules.locale_de import unknown_dm_command_hint

    node_key = str(node_id)
    now = time.time()
    cd = UNKNOWN_DM_HINT_COOLDOWN_SEC if cooldown_sec is None else max(0, int(cooldown_sec))
    last = float(_unknown_dm_hint_last.get(node_key, 0) or 0)
    if last and (now - last) < cd:
        return None
    _unknown_dm_hint_last[node_key] = now
    return unknown_dm_command_hint()


def is_cmd_rate_limited(node_id, *, is_admin: Optional[Callable[[str], bool]] = None) -> bool:
    return check_command_throttle(node_id, is_admin=is_admin) is not None


def get_rate_limit_snapshot(
    *,
    resolve_names: Optional[Callable[[str], tuple]] = None,
) -> list:
    """Live usage rows for Admin → Limits."""
    st = _settings()
    now = time.time()
    window = max(1, int(getattr(st, "cmdRateLimitWindow", 60) or 60))
    max_cmds = max(1, int(getattr(st, "cmdRateLimitMax", 3) or 3))
    cooldown = int(getattr(st, "cmdExpensiveCooldownSec", 45) or 0)
    cutoff = now - window
    enabled = bool(getattr(st, "cmdRateLimitEnabled", True))

    node_keys = set(_cmd_rate_tracker.keys()) | {k[0] for k in _cmd_expensive_last.keys()}
    rows = []
    for node_key in node_keys:
        timestamps = [t for t in _cmd_rate_tracker.get(node_key, []) if t > cutoff]
        _cmd_rate_tracker[node_key] = timestamps
        count = len(timestamps)
        notified = float(_cmd_rate_notified.get(node_key, 0) or 0) > cutoff
        if enabled and count > max_cmds:
            status = "limitiert"
        elif notified:
            status = "Hinweis gesendet"
        else:
            status = "OK"

        expensive = []
        for (n, cmd), last in list(_cmd_expensive_last.items()):
            if n != node_key:
                continue
            remaining = max(0, int(cooldown - (now - last) + 0.999)) if cooldown else 0
            if remaining > 0:
                expensive.append({"cmd": cmd, "remaining_sec": remaining})

        short = long_n = ""
        try:
            hex_id = f"!{int(node_key):08x}"
        except (TypeError, ValueError):
            hex_id = node_key
        if resolve_names:
            try:
                short, long_n, hex_id = resolve_names(node_key)
            except Exception:
                pass

        rows.append(
            {
                "node_id": node_key,
                "hex": hex_id,
                "short": short or "",
                "long": long_n or "",
                "cmds_in_window": count,
                "limit_max": max_cmds,
                "window_sec": window,
                "status": status,
                "notified": notified,
                "expensive": expensive,
            }
        )

    rows.sort(key=lambda r: (-r["cmds_in_window"], r["node_id"]))
    return rows


def reset_rate_limit(node_id=None) -> int:
    """Clear throttle state for one node or all. Returns number of nodes cleared."""
    global _cmd_rate_tracker, _cmd_rate_notified, _cmd_expensive_last, _cmd_expensive_notified
    global _unknown_dm_hint_last
    if node_id is None or str(node_id).strip() in ("", "*"):
        n = len(
            set(_cmd_rate_tracker)
            | {k[0] for k in _cmd_expensive_last}
            | set(_unknown_dm_hint_last)
        )
        _cmd_rate_tracker.clear()
        _cmd_rate_notified.clear()
        _cmd_expensive_last.clear()
        _cmd_expensive_notified.clear()
        _unknown_dm_hint_last.clear()
        return n
    node_key = str(node_id).strip()
    had = (
        node_key in _cmd_rate_tracker
        or any(k[0] == node_key for k in _cmd_expensive_last)
        or node_key in _unknown_dm_hint_last
    )
    _cmd_rate_tracker.pop(node_key, None)
    _cmd_rate_notified.pop(node_key, None)
    _unknown_dm_hint_last.pop(node_key, None)
    for key in [k for k in list(_cmd_expensive_last) if k[0] == node_key]:
        del _cmd_expensive_last[key]
    for key in [k for k in list(_cmd_expensive_notified) if k[0] == node_key]:
        del _cmd_expensive_notified[key]
    return 1 if had else 0


def cleanup_throttle_state(current_time: Optional[float] = None) -> None:
    """Drop stale tracker entries (called from system memory cleanup)."""
    st = _settings()
    now = current_time if current_time is not None else time.time()
    window = max(1, int(getattr(st, "cmdRateLimitWindow", 60) or 60))
    cutoff = now - window
    if _cmd_rate_tracker:
        stale = [
            k
            for k, ts_list in _cmd_rate_tracker.items()
            if not any(t > cutoff for t in ts_list)
        ]
        for k in stale:
            del _cmd_rate_tracker[k]
        for k in [k for k, t in list(_cmd_rate_notified.items()) if t <= cutoff]:
            del _cmd_rate_notified[k]
    cooldown = int(getattr(st, "cmdExpensiveCooldownSec", 45) or 0)
    if _cmd_expensive_last and cooldown > 0:
        exp_cut = now - max(cooldown * 2, 300)
        for key in [k for k, t in list(_cmd_expensive_last.items()) if t < exp_cut]:
            del _cmd_expensive_last[key]
            _cmd_expensive_notified.pop(key, None)
    hint_cut = now - (UNKNOWN_DM_HINT_COOLDOWN_SEC * 2)
    for k in [k for k, t in list(_unknown_dm_hint_last.items()) if t < hint_cut]:
        del _unknown_dm_hint_last[k]
