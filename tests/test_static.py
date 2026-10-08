"""The web front end: served correctly, and written so a stored API key stays safe."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

import _sandbox  # noqa: F401
from support.harness import LiveServer

WEB = Path(__file__).resolve().parent.parent / "swimform" / "web"
SCRIPTS = sorted(p for p in WEB.rglob("*.js") if "viewer" not in p.relative_to(WEB).parts)

MIME = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}


class TestFrontEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LiveServer()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_every_asset_is_served_with_the_right_type(self):
        files = [p for p in WEB.rglob("*") if p.is_file() and p.suffix in MIME and p.name != "index.html"]
        self.assertTrue(files)
        for p in files:
            rel = p.relative_to(WEB).as_posix()
            status, hdrs, body = self.srv.request("GET", f"/static/{rel}")
            self.assertEqual(status, 200, rel)
            self.assertTrue(hdrs["content-type"].startswith(MIME[p.suffix]), rel)
            self.assertEqual(body, p.read_bytes(), rel)

    def test_the_page_has_no_inline_script_or_style(self):
        html = (WEB / "index.html").read_text()
        for m in re.finditer(r"<script\b([^>]*)>", html):
            self.assertIn("src=", m.group(1), "inline <script> would need 'unsafe-inline'")
        self.assertNotRegex(html, r"<style\b")
        self.assertNotRegex(html, r"\sstyle\s*=")
        self.assertNotRegex(html, r"\son[a-z]+\s*=")

    def test_scripts_never_build_html_from_strings(self):
        """The key lives in web storage, so injected markup must be impossible.
        Everything is built with createElement and textContent."""
        banned = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function|"
                            r"setAttribute\(\s*['\"]style['\"]|javascript:")
        for p in SCRIPTS:
            hit = banned.search(p.read_text())
            self.assertIsNone(hit, f"{p.relative_to(WEB)}: {hit and hit.group(0)}")

    def test_scripts_never_call_out_to_other_sites(self):
        for p in SCRIPTS:
            text = p.read_text()
            for url in re.findall(r"""fetch\(\s*['"`](https?://[^'"`]+)""", text):
                self.fail(f"{p.name} fetches {url}")
            self.assertNotRegex(text, r"XMLHttpRequest|navigator\.sendBeacon|new\s+WebSocket")

    def test_relative_imports_resolve(self):
        for p in SCRIPTS:
            for spec in re.findall(r"""(?:import|from)\s*\(?\s*['"](\.{1,2}/[^'"]+)['"]""", p.read_text()):
                self.assertTrue((p.parent / spec).resolve().is_file(), f"{p.name} imports {spec}")

    def test_the_key_is_only_ever_sent_in_the_gemini_header(self):
        api = (WEB / "js" / "api.js").read_text()
        self.assertIn('"X-Api-Key"', api)
        for p in SCRIPTS:
            if p.name in ("store.js",):
                continue
            text = p.read_text()
            self.assertNotRegex(text, r"\?key=|&key=", p.name)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_scripts_parse_as_modules(self):
        for p in SCRIPTS:
            res = subprocess.run(["node", "--check", "--input-type=module"], input=p.read_text(),
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"{p.name}: {res.stderr[:300]}")


if __name__ == "__main__":
    unittest.main()
