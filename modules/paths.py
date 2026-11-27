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


def ensure_parent_dir(file_path: str) -> None:
    """Create parent directory for a file path (e.g. before open(..., 'w'))."""
    d = os.path.dirname(file_path)
    if d:
        os.makedirs(d, exist_ok=True)


def runtime_writable_paths_from_config(config_ini: str | None = None) -> list[str]:
    """Paths the bot / web admin may write (DM alert, news, ban list, …)."""
    import configparser

    root = repo_root()
    cfg_path = config_ini or os.path.join(root, "config.ini")
    paths: set[str] = set()
    for rel in (
        "data/bbs_ban_list.txt",
        "data/leaderboard.pkl",
        "data/alert.txt",
        "data/news.txt",
        "alert.txt",
    ):
        paths.add(path_in_repo(rel))
    if os.path.isfile(cfg_path):
        parser = configparser.ConfigParser()
        parser.read(cfg_path, encoding="utf-8")
        for section, key in (
            ("fileMon", "file_path"),
            ("webAdmin", "alert_file"),
            ("fileMon", "news_file_path"),
            ("webAdmin", "news_file"),
        ):
            if parser.has_option(section, key):
                value = parser.get(section, key).strip()
                if value:
                    paths.add(path_in_repo(value))
    return sorted(paths)
