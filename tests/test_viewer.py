"""The 3D viewer bundle: built from our source, carries three.js's licence, no native bridge."""

from __future__ import annotations

import unittest
from pathlib import Path

import _sandbox  # noqa: F401
from swimform import taxonomy

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "swimform" / "web" / "viewer"


class TestViewerBundle(unittest.TestCase):
    def test_files_exist(self):
        for name in ("viewer.html", "viewer.js", "viewer.css"):
            self.assertTrue((VIEWER / name).is_file(), name)

    def test_page_loads_only_its_own_files(self):
        html = (VIEWER / "viewer.html").read_text()
        self.assertIn('src="viewer.js"', html)
        self.assertNotIn("<style", html)
        self.assertNotIn("http", html)

    def test_bundle_has_the_demo_clips_and_the_three_licence(self):
        js = (VIEWER / "viewer.js").read_text()
        for demo in ("catch_up", "single_arm"):
            self.assertIn(demo, js)
        self.assertIn("SPDX-License-Identifier: MIT", js)
        self.assertNotIn("ReactNativeWebView", js)

    def test_third_party_notice_names_three(self):
        notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
        self.assertIn("three.js", notice)
        self.assertIn("Permission is hereby granted", notice)

    def test_every_drill_demo_is_in_the_bundle(self):
        js = (VIEWER / "viewer.js").read_text()
        for d in taxonomy.drills():
            if d.get("demo"):
                self.assertIn(d["demo"], js, d["id"])


if __name__ == "__main__":
    unittest.main()
