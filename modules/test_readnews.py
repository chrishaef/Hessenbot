#!/usr/bin/env python3
# Regression: !readnews must not treat leftover "!" as a news source (HB-16).
# Run: python -m pytest modules/test_readnews.py -q

from __future__ import annotations

import unittest

from modules.filemon import parse_readnews_source


class ParseReadnewsSourceTests(unittest.TestCase):
    def test_bang_readnews_default(self):
        self.assertIsNone(parse_readnews_source("!readnews"))

    def test_bare_readnews_default(self):
        self.assertIsNone(parse_readnews_source("readnews"))

    def test_bang_with_source(self):
        self.assertEqual(parse_readnews_source("!readnews mesh"), "mesh")

    def test_bare_with_source(self):
        self.assertEqual(parse_readnews_source("readnews mesh"), "mesh")

    def test_help_marker(self):
        self.assertEqual(parse_readnews_source("!readnews?"), "?")
        self.assertEqual(parse_readnews_source("readnews?"), "?")

    def test_case_and_space(self):
        self.assertIsNone(parse_readnews_source("  !ReadNews  "))
        self.assertEqual(parse_readnews_source("!READNEWS Mesh"), "mesh")


if __name__ == "__main__":
    unittest.main()
