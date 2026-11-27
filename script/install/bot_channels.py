#!/usr/bin/env python3
"""Map the wizard's "bot processes these channels" answer onto the existing config keys.

No new config key is introduced; only these existing [general] keys are used:
  ignoreChannels, ignoreDefaultChannel, messagesChannel (defaultChannel is read, never written).

Usage:
    bot_channels.py CONFIG_INI --selected 1[,0,2] --existing 0,1[,2] [--apply] [--dry-run]

Without --apply the resulting `section.key=value` assignments are printed (only keys that differ
from the current file). With --apply they are written through ini_set (comment-preserving).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ini_set  # noqa: E402

DEFAULT_IGNORE = "2,3,4"
DEFAULT_MESSAGES = 1


def parse_indices(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.lstrip("-").isdigit():
            raise ValueError(f"not a channel index: {part!r}")
        out.append(int(part))
    return out


def format_indices(values: Iterable[int]) -> str:
    return ",".join(str(v) for v in sorted(set(values)))


def compute(
    selected: Iterable[int],
    existing: Iterable[int],
    default_channel: int,
    current_ignore: Iterable[int],
    current_messages: int,
    current_ignore_default: bool,
) -> dict[str, str]:
    """Return desired [general] values (always complete); caller diffs against the file."""
    sel = set(selected)
    exist = set(existing)
    ignore = (set(current_ignore) | (exist - sel - {default_channel})) - sel
    ignore.discard(default_channel)

    ignore_default = default_channel not in sel
    non_default = sorted(i for i in sel if i != default_channel)
    messages = non_default[0] if non_default else current_messages
    if current_messages in sel and current_messages != default_channel:
        messages = current_messages

    return {
        "ignoreChannels": format_indices(ignore),
        "ignoreDefaultChannel": "True" if ignore_default else "False",
        "messagesChannel": str(messages),
    }


def _int_or(value: Optional[str], fallback: int) -> int:
    try:
        return int((value or "").strip())
    except ValueError:
        return fallback


def plan_changes(ini_text: str, selected: list[int], existing: list[int]) -> list[tuple[str, str]]:
    g = lambda k: ini_set.get_value(ini_text, "general", k)  # noqa: E731
    default_channel = _int_or(g("defaultChannel"), 0)
    cur_ignore_raw = g("ignoreChannels")
    cur_ignore = parse_indices(cur_ignore_raw if cur_ignore_raw is not None else DEFAULT_IGNORE)
    cur_messages = _int_or(g("messagesChannel"), DEFAULT_MESSAGES)
    cur_ignore_default = (g("ignoreDefaultChannel") or "True").strip().lower() in ("1", "true", "yes", "on")

    desired = compute(selected, existing, default_channel, cur_ignore, cur_messages, cur_ignore_default)

    changes: list[tuple[str, str]] = []
    if set(parse_indices(desired["ignoreChannels"])) != set(cur_ignore):
        changes.append(("ignoreChannels", desired["ignoreChannels"]))
    if (desired["ignoreDefaultChannel"] == "True") != cur_ignore_default:
        changes.append(("ignoreDefaultChannel", desired["ignoreDefaultChannel"]))
    if int(desired["messagesChannel"]) != cur_messages:
        changes.append(("messagesChannel", desired["messagesChannel"]))
    return changes


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--selected", required=True, help="channel indices the bot processes")
    ap.add_argument("--existing", required=True, help="channel indices that exist on the node")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        selected = parse_indices(args.selected)
        existing = parse_indices(args.existing)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not selected:
        print("error: at least one channel must be selected", file=sys.stderr)
        return 2

    with open(args.config, encoding="utf-8", newline="") as fh:
        text = fh.read()
    changes = plan_changes(text, selected, existing)

    if not args.apply or args.dry_run:
        for key, value in changes:
            print(f"general.{key}={value}")
        return 0

    if not changes:
        print("no changes needed")
        return 0
    return ini_set.main([args.config] + [a for k, v in changes for a in ("--set", f"general.{k}={v}")])


if __name__ == "__main__":
    sys.exit(main())
