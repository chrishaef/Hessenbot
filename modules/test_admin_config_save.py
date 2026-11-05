#!/usr/bin/env python3
# Regression: ACP Einstellungen-Speichern darf fremde Keys nicht droppen/zerlegen.
# Run: python -m pytest modules/test_admin_config_save.py -q

from __future__ import annotations

import os
import tempfile
import unittest
from configparser import ConfigParser
from pathlib import Path

from modules.admin_config import (
    apply_form_to_config,
    build_settings_form_html,
    parse_field_name,
    write_config_file,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "config.template"


class AdminConfigSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.config_path = self.root / "config.ini"
        # write_config_file looks for config.template beside the ini
        (self.root / "config.template").write_text(
            TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write_ini(self, text: str) -> None:
        self.config_path.write_text(text, encoding="utf-8")

    def _read(self, *, preserve_case: bool = True) -> ConfigParser:
        cfg = ConfigParser()
        if preserve_case:
            cfg.optionxform = str  # type: ignore[method-assign]
        cfg.read(self.config_path, encoding="utf-8")
        return cfg

    def test_partial_form_preserves_non_submitted_keys(self) -> None:
        self._write_ini(
            "[bbs]\n"
            "bbsDmUserAckEnabled = False\n"
            "bbsDmAckRetrySeconds = 900\n"
            "\n"
            "[location]\n"
            "blitzWatchEnabled = True\n"
            "blitzWatchDefaultRadiusKm = 8\n"
            "customExtraKey = keep-me\n"
        )
        cfg = ConfigParser()
        cfg.read(self.config_path, encoding="utf-8")

        # Only ACK toggle submitted — mimics truncated/partial POST.
        form = {"cfg__bbs__bbsdmuserackenabled": "True"}
        apply_form_to_config(cfg, form, config_file=str(self.config_path))

        out = self._read()
        self.assertEqual(out["bbs"]["bbsDmUserAckEnabled"], "True")
        self.assertEqual(out["bbs"]["bbsDmAckRetrySeconds"], "900")
        self.assertEqual(out["location"]["blitzWatchEnabled"], "True")
        self.assertEqual(out["location"]["blitzWatchDefaultRadiusKm"], "8")
        self.assertEqual(out["location"]["customExtraKey"], "keep-me")

    def test_full_form_save_restores_camel_case_and_keeps_blitzwatch(self) -> None:
        self._write_ini(
            "[bbs]\n"
            "bbsDmUserAckEnabled = False\n"
            "bbsDmNotifySender = True\n"
            "\n"
            "[location]\n"
            "blitzWatchEnabled = True\n"
            "blitzWatchDefaultRadiusKm = 5\n"
        )
        cfg = ConfigParser()
        cfg.read(self.config_path, encoding="utf-8")
        # Keys are lowercased in-memory (default optionxform).
        self.assertIn("blitzwatchenabled", list(cfg["location"]))

        form = {}
        for section in cfg.sections():
            for key in cfg[section]:
                form[f"cfg__{section}__{key}"] = cfg[section][key]
        form["cfg__bbs__bbsdmuserackenabled"] = "True"

        apply_form_to_config(cfg, form, config_file=str(self.config_path))

        raw = self.config_path.read_text(encoding="utf-8")
        self.assertIn("bbsDmUserAckEnabled = True", raw)
        self.assertIn("blitzWatchEnabled = True", raw)
        self.assertNotRegex(raw, r"(?m)^blitzwatchenabled\s*=")
        self.assertNotRegex(raw, r"(?m)^bbsdmuserackenabled\s*=")

        out = self._read()
        self.assertEqual(out["location"]["blitzWatchEnabled"], "True")
        self.assertEqual(out["bbs"]["bbsDmUserAckEnabled"], "True")

    def test_write_config_file_does_not_drop_unknown_keys(self) -> None:
        self._write_ini(
            "[location]\n"
            "blitzWatchEnabled = False\n"
            "myLocalOnlyFlag = yes\n"
        )
        cfg = ConfigParser()
        cfg.read(self.config_path, encoding="utf-8")
        write_config_file(cfg, str(self.config_path))
        out = self._read()
        self.assertEqual(out["location"]["blitzWatchEnabled"], "False")
        self.assertEqual(out["location"]["myLocalOnlyFlag"], "yes")

    def test_build_settings_form_includes_existing_keys(self) -> None:
        self._write_ini(
            "[bbs]\n"
            "bbsDmUserAckEnabled = True\n"
            "\n"
            "[location]\n"
            "blitzWatchEnabled = False\n"
        )
        cfg = ConfigParser()
        cfg.read(self.config_path, encoding="utf-8")
        html = build_settings_form_html(cfg)
        self.assertIn('name="cfg__bbs__bbsdmuserackenabled"', html)
        self.assertIn('name="cfg__location__blitzwatchenabled"', html)
        # Labels stay human-readable even when keys were lowercased in memory.
        self.assertIn("Blitzwatch Auto-Warnung", html)

    def test_parse_field_name(self) -> None:
        self.assertEqual(
            parse_field_name("cfg__location__blitzWatchEnabled"),
            ("location", "blitzWatchEnabled"),
        )
        self.assertIsNone(parse_field_name("other"))


if __name__ == "__main__":
    unittest.main()
