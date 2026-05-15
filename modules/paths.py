#!/usr/bin/env python3
"""Project-root paths (independent of process cwd / systemd WorkingDirectory)."""

import os

_REPO_ROOT: str | None = None


def repo_root() -> str:
    """Absolute path to the repository root (parent of modules/)."""
    global _REPO_ROOT
    if _REPO_ROOT is None:
        _REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return _REPO_ROOT


def path_in_repo(rel_or_abs: str) -> str:
    if not rel_or_abs:
        return repo_root()
    if os.path.isabs(rel_or_abs):
        return os.path.normpath(rel_or_abs)
    return os.path.normpath(os.path.join(repo_root(), rel_or_abs))
