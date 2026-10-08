"""The documents and the app must say the same thing, and the README must not lie."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import _sandbox  # noqa: F401
from swimform import config, taxonomy

ROOT = Path(__file__).resolve().parent.parent


class TestDocs(unittest.TestCase):
    def test_consent_version_matches_the_document(self):
        js = (ROOT / "swimform" / "web" / "js" / "store.js").read_text()
        version = re.search(r'CONSENT_VERSION\s*=\s*"([^"]+)"', js).group(1)
        doc = (ROOT / "docs" / "RESPONSIBLE_USE.md").read_text()
        self.assertIn(f"Consent notice version: {version}", doc)
        consent_js = (ROOT / "swimform" / "web" / "js" / "consent.js").read_text()
        self.assertIn("CONSENT_VERSION", consent_js)

    def test_the_notice_covers_the_essentials(self):
        text = (ROOT / "swimform" / "web" / "js" / "consent.js").read_text().lower()
        for needle in ("google", "free", "personal information", "children", "not coaching",
                       "key", "no warranty", "endorsed"):
            self.assertIn(needle, text)

    def test_the_responsible_use_doc_links_googles_terms(self):
        doc = (ROOT / "docs" / "RESPONSIBLE_USE.md").read_text()
        self.assertIn("https://ai.google.dev/gemini-api/terms", doc)
        self.assertIn("not legal advice", doc.lower())

    def test_readme_describes_the_real_drill_count_and_defaults(self):
        words = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split()
        readme = (ROOT / "README.md").read_text()
        self.assertIn(f"{words[len(taxonomy.drills())]} drills", readme.lower())
        for key, value in config.DEFAULTS.items():
            if isinstance(value, list):
                self.assertIn(f"`{key}`", readme, key)
            else:
                self.assertRegex(readme, rf"`{key}`.*`{re.escape(str(value))}`", key)

    def test_readme_commands_exist(self):
        from swimform import cli
        parser = cli.build_parser()
        names = set(parser._subparsers._group_actions[0].choices)
        readme = (ROOT / "README.md").read_text()
        for cmd in re.findall(r"python3 -m swimform ([a-z]+)", readme):
            self.assertIn(cmd, names, cmd)

    def test_ci_runs_the_suite(self):
        path = ROOT / ".github" / "workflows" / "ci.yml"
        if not path.exists():
            self.skipTest("no CI workflow in this checkout")
        ci = path.read_text()
        self.assertIn("unittest discover", ci)
        self.assertIn("ffmpeg", ci)

    def test_the_licence_is_plain_mit(self):
        lic = (ROOT / "LICENSE").read_text()
        self.assertIn("MIT License", lic)
        self.assertNotIn("NOTE ON DATA", lic)

    def test_packaging_includes_the_data_and_web_files(self):
        toml = (ROOT / "pyproject.toml").read_text()
        for needle in ("data/*.json", "web/*.html", "web/js/*.js", "web/viewer/*"):
            self.assertIn(needle, toml)


if __name__ == "__main__":
    unittest.main()
