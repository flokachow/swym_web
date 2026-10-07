"""The drill library is hand-authored data; these tests keep it honest."""

from __future__ import annotations

import re
import unittest

import _sandbox  # noqa: F401
from swimform import taxonomy

EQUIPMENT = {"fins", "snorkel", "pull buoy", "kickboard", "hand paddles", "ankle band"}
REQUIRED = ("id", "title", "summary", "how_to", "why", "easier", "harder", "sets",
            "equipment", "caution", "corrects_faults", "contraindicated_for",
            "triathlon_relevance", "status")


class TestDrillLibrary(unittest.TestCase):
    def test_schema(self):
        for d in taxonomy.drills():
            for key in REQUIRED:
                self.assertIn(key, d, f"{d.get('id')} missing {key}")
            self.assertRegex(d["id"], r"^[a-z][a-z0-9_]*$")
            self.assertTrue(3 <= len(d["how_to"]) <= 6, f"{d['id']}: 3-6 steps")
            self.assertTrue(set(d["equipment"]) <= EQUIPMENT, f"{d['id']}: equipment vocabulary")
            self.assertIn(d["triathlon_relevance"], ("high", "medium", "low"))
            self.assertEqual(d["status"], "draft")
            self.assertTrue(d["corrects_faults"], f"{d['id']} corrects nothing")

    def test_every_fault_is_covered(self):
        for fid in taxonomy.fault_ids():
            self.assertTrue(taxonomy.drills_for_fault(fid), fid)

    def test_no_drill_both_corrects_and_is_contraindicated(self):
        for d in taxonomy.drills():
            fixed = {l["faultId"] for l in d["corrects_faults"]}
            self.assertFalse(fixed & set(d["contraindicated_for"]), d["id"])

    def test_contraindications_exist(self):
        """The recommender test that relies on them would pass vacuously otherwise."""
        self.assertTrue(any(d["contraindicated_for"] for d in taxonomy.drills()))

    def test_risky_drills_carry_a_caution(self):
        by_id = taxonomy.drill_by_id()
        for did in ("head_up_swimming", "fist_swimming", "sculling"):
            self.assertTrue(by_id[did]["caution"], did)

    def test_demo_ids_are_known(self):
        known = {"catch_up", "single_arm"}
        for d in taxonomy.drills():
            if d.get("demo"):
                self.assertIn(d["demo"], known, d["id"])

    def test_public_shape(self):
        d = taxonomy.drill_public(taxonomy.drills()[0])
        for key in ("id", "title", "howTo", "corrects", "contraindicatedFor", "demo"):
            self.assertIn(key, d)

    def test_ids_are_unique_slugs_not_codes(self):
        ids = [d["id"] for d in taxonomy.drills()]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertFalse(re.match(r"^fr[a-z]*\d", i), i)


if __name__ == "__main__":
    unittest.main()
