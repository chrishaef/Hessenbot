#!/usr/bin/env python3
"""Comment-preserving INI editor for config.ini (replaces sed on literal strings).

Usage:
    ini_set.py FILE --set section.key=value [--set ...] [--get section.key] [--dry-run]

Rules:
  * section and key names match case-insensitively; the file's own spelling is kept.
  * an active `key = ...` line is rewritten in place (only if the value actually changes).
  * otherwise a commented example (`# key = ...`) is followed by the new active line.
  * otherwise the key is appended to the end of its section; missing sections are appended.
Exit codes: 0 ok, 2 usage error, 3 --get on a missing key.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from typing import Optional

SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[^\s#;=\[][^=]*?)(?P<sep>\s*[=:]\s*)(?P<value>.*?)(?P<nl>\r?\n?)$")
COMMENTED_KEY_RE = re.compile(r"^\s*[#;]\s*(?P<key>[A-Za-z0-9_.\-]+)\s*[=:]")


def _split_lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _newline_style(lines: list[str]) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"


def get_value(text: str, section: str, key: str) -> Optional[str]:
    current = None
    for line in _split_lines(text):
        m = SECTION_RE.match(line)
        if m:
            current = m.group("name").strip().lower()
            continue
        if current != section.lower():
            continue
        km = KEY_RE.match(line)
        if km and km.group("key").strip().lower() == key.lower():
            return km.group("value").strip()
    return None


def set_value(text: str, section: str, key: str, value: str) -> tuple[str, bool]:
    """Return (new_text, changed)."""
    lines = _split_lines(text)
    nl = _newline_style(lines)
    sec_l = section.lower()
    key_l = key.lower()

    current = None
    sec_start = None
    sec_end = None
    key_idx = None
    comment_idx = None
    last_content_idx = None

    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if m:
            name = m.group("name").strip().lower()
            if current == sec_l and sec_end is None:
                sec_end = i
            current = name
            if name == sec_l and sec_start is None:
                sec_start = i
                last_content_idx = i
            continue
        if current != sec_l:
            continue
        if line.strip():
            last_content_idx = i
        km = KEY_RE.match(line)
        if km and km.group("key").strip().lower() == key_l and key_idx is None:
            key_idx = i
            continue
        cm = COMMENTED_KEY_RE.match(line)
        if cm and cm.group("key").lower() == key_l:
            comment_idx = i

    if sec_start is not None and sec_end is None:
        sec_end = len(lines)

    if key_idx is not None:
        km = KEY_RE.match(lines[key_idx])
        assert km is not None
        if km.group("value").strip() == value:
            return text, False
        lines[key_idx] = f"{km.group('indent')}{km.group('key')}{km.group('sep')}{value}{km.group('nl') or nl}"
        return "".join(lines), True

    new_line = f"{key} = {value}{nl}"
    if sec_start is None:
        if lines and not lines[-1].endswith(("\n", "\r\n")):
            lines[-1] += nl
        if lines and lines[-1].strip():
            lines.append(nl)
        lines.append(f"[{section}]{nl}")
        lines.append(new_line)
        return "".join(lines), True

    if comment_idx is not None:
        insert_at = comment_idx + 1
    else:
        insert_at = (last_content_idx if last_content_idx is not None else sec_start) + 1
    if insert_at > 0 and not lines[insert_at - 1].endswith(("\n", "\r\n")):
        lines[insert_at - 1] += nl
    lines.insert(insert_at, new_line)
    return "".join(lines), True


def _write_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    st = os.stat(path) if os.path.exists(path) else None
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ini_set_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if st is not None:
            os.chmod(tmp, st.st_mode & 0o7777)
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except PermissionError:
                pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _parse_assignment(arg: str) -> tuple[str, str, str]:
    left, sep, value = arg.partition("=")
    if not sep or "." not in left:
        raise argparse.ArgumentTypeError(f"expected section.key=value, got: {arg!r}")
    section, _, key = left.partition(".")
    if not section.strip() or not key.strip():
        raise argparse.ArgumentTypeError(f"expected section.key=value, got: {arg!r}")
    return section.strip(), key.strip(), value


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--set", dest="sets", action="append", default=[], type=_parse_assignment, metavar="SECTION.KEY=VALUE")
    ap.add_argument("--get", dest="get", metavar="SECTION.KEY")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    with open(args.file, encoding="utf-8", newline="") as fh:
        text = fh.read()

    if args.get:
        section, _, key = args.get.partition(".")
        val = get_value(text, section, key)
        if val is None:
            return 3
        print(val)
        return 0

    if not args.sets:
        ap.error("nothing to do: use --set or --get")

    changed_any = False
    for section, key, value in args.sets:
        text, changed = set_value(text, section, key, value)
        changed_any = changed_any or changed
        print(f"{'set' if changed else 'unchanged'}: [{section}] {key} = {value}")

    if changed_any and not args.dry_run:
        _write_atomic(args.file, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
