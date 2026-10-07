"""Release tripwire: nothing third-party, personal or secret may creep back in.

The words are assembled from pieces so this file does not trip itself.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

import _sandbox  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN = {
    "drill publisher": re.compile(r"swimmers" + r"best|\bone[ -]?swim\b", re.I),
    "drill catalogue name": re.compile(r"compen" + r"dium", re.I),
    "scraped-source fields": re.compile(r"source_" + r"urls|drill_" + r"prose|fetch_" + r"drills", re.I),
    "publisher drill codes": re.compile(r"\bFR(?:A|BO|K|PR|S)\d{2}"),
    "stock footage / third-party video": re.compile(
        r"pex" + r"els|myswim" + r"pro|you" + r"tube|you" + r"tu\.be", re.I),
    "local absolute path": re.compile(r"/Us" + r"ers/"),
    "placeholder": re.compile(r"YOUR" + r"NAME"),
    "google api key": re.compile(r"AI" + r"za[0-9A-Za-z_-]{20,}"),
}

MEDIA = (".mp4", ".mov", ".m4v", ".avi", ".mkv")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def candidate_files() -> list[Path]:
    """Tracked files plus untracked-but-not-ignored ones, i.e. what a commit would ship."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        return [ROOT / p for p in out if (ROOT / p).is_file()]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*")
                if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)]


class TestTripwire(unittest.TestCase):
    def test_no_forbidden_strings_in_shipped_files(self):
        hits = []
        for path in candidate_files():
            if path.suffix.lower() in MEDIA or path.suffix in (".png", ".jpg", ".ico", ".jar"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for label, rx in FORBIDDEN.items():
                m = rx.search(text)
                if m:
                    hits.append(f"{path.relative_to(ROOT)}: {label} ({m.group(0)!r})")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_media_files_shipped(self):
        media = [str(p.relative_to(ROOT)) for p in candidate_files()
                 if p.suffix.lower() in MEDIA]
        self.assertEqual(media, [], "footage must never be committed")

    def test_scraped_leftovers_are_gone(self):
        self.assertFalse((ROOT / "data" / "cache").exists())
        prose = "drill_" + "prose.json"
        self.assertFalse((ROOT / "data" / prose).exists())
        self.assertFalse((ROOT / "swimform" / "data" / prose).exists())
        self.assertFalse((ROOT / "scripts" / ("fetch_" + "drills.py")).exists())


if __name__ == "__main__":
    unittest.main()
