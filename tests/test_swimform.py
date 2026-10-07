"""Tests for the parts that must not silently drift.

Nothing here touches the network. The model is the one component we cannot
test, so everything around it — the taxonomy join, the ranking rules, the
geometry, the report — is tested instead.

    python3 -m pytest tests/          (or: python3 tests/test_swimform.py)
"""

from __future__ import annotations

import unittest

import _sandbox  # noqa: F401  (must come before any swimform import)
from swimform import analyze, coach, measure, recommend, report, taxonomy


def assessed(fault_id: str, deviation: float, confidence: float = 1.0) -> dict:
    return {"faultId": fault_id, "deviation": deviation, "confidence": confidence}


class TestTaxonomy(unittest.TestCase):
    def test_every_fault_has_drills(self):
        """A fault with no drills can be detected but not acted on."""
        for fid in taxonomy.fault_ids():
            self.assertTrue(taxonomy.drills_for_fault(fid),
                            f"{fid} has no drills — detecting it would be useless")

    def test_faults_carry_an_elite_reference(self):
        """The elite anchor is what the model scores against; without it the
        prompt silently degrades to the model's own baseline."""
        for f in taxonomy.faults():
            for key in ("id", "name", "short", "plane", "why", "elite"):
                self.assertTrue(f.get(key), f"{f.get('id')} missing {key}")

    def test_validation_rejects_a_typo_in_a_fault_id(self):
        bad = [{"id": "x", "corrects_faults": [{"faultId": "nope", "strength": "primary"}],
                "contraindicated_for": []}]
        with self.assertRaises(taxonomy.TaxonomyError):
            taxonomy.validate(bad)


class TestRecommend(unittest.TestCase):
    def test_returns_drills_for_a_detected_fault(self):
        out = recommend.recommend([assessed("low_body_position", 0.6)])
        self.assertTrue(out)
        for s in out:
            self.assertTrue(s.addresses)

    def test_ignores_faults_below_threshold(self):
        self.assertEqual(recommend.recommend([assessed("low_body_position", 0.1)]), [])

    def test_contraindicated_drills_are_withheld(self):
        """A drill that trains the opposite pattern must never be suggested —
        prescribing it makes the swimmer worse, not merely no better."""
        blocked = [d for d in taxonomy.drills() if d["contraindicated_for"]]
        self.assertTrue(blocked, "no contraindications in the data — test is vacuous")
        fault = blocked[0]["contraindicated_for"][0]
        ids = {s.drill["id"] for s in
               recommend.recommend([assessed(fault, 0.9)], limit=50)}
        for d in blocked:
            if fault in d["contraindicated_for"]:
                self.assertNotIn(d["id"], ids, f"{d['id']} contraindicated for {fault}")

    def test_confidence_weights_the_score(self):
        sure = recommend.recommend([assessed("low_body_position", 0.6, 1.0)])
        unsure = recommend.recommend([assessed("low_body_position", 0.6, 0.3)])
        self.assertGreater(sure[0].score, unsure[0].score)

    def test_no_drill_is_listed_twice(self):
        out = recommend.recommend(
            [assessed(f, 0.7) for f in taxonomy.fault_ids()], limit=20)
        ids = [s.drill["id"] for s in out]
        self.assertEqual(len(ids), len(set(ids)))

    def test_spreads_across_faults(self):
        out = recommend.recommend(
            [assessed("low_body_position", 0.8), assessed("short_stroke_finish", 0.8)],
            limit=6)
        leads = {s.addresses[0] for s in out}
        self.assertGreater(len(leads), 1, "all drills targeted one fault")

    def test_no_assessments_means_no_drills(self):
        self.assertEqual(recommend.recommend([]), [])

    def test_serialised_drill_is_complete(self):
        s = recommend.recommend([assessed("low_body_position", 0.6)])[0].as_dict()
        for key in ("id", "title", "summary", "addresses", "addressesNames", "reason"):
            self.assertIn(key, s)
        self.assertEqual(len(s["addresses"]), len(s["addressesNames"]))


class TestMeasure(unittest.TestCase):
    @staticmethod
    def pt(name, x, y, visible=True):
        return {"name": name, "x": x, "y": y, "visible": visible}

    def test_right_angle_at_the_elbow(self):
        pts = [self.pt("shoulder_near", 100, 100),
               self.pt("elbow_near", 200, 100),
               self.pt("wrist_near", 200, 200)]
        elbow = next(m for m in measure.compute(pts, None) if m.id == "elbow_angle")
        self.assertAlmostEqual(elbow.value, 90.0, places=3)

    def test_flat_body_line_is_good(self):
        pts = [self.pt("shoulder_near", 100, 500), self.pt("hip_top", 400, 500)]
        line = next(m for m in measure.compute(pts, None) if m.id == "body_line_angle")
        self.assertAlmostEqual(line.value, 0.0, places=3)
        self.assertEqual(line.verdict, "good")

    def test_dropped_hips_are_flagged(self):
        pts = [self.pt("shoulder_near", 100, 400), self.pt("hip_top", 400, 600)]
        line = next(m for m in measure.compute(pts, None) if m.id == "body_line_angle")
        self.assertEqual(line.verdict, "pronounced")

    def test_obscured_landmarks_lower_confidence_not_output(self):
        """The visibility flag runs conservative and has called a usable hip
        invisible, so it must not suppress the measurement."""
        pts = [self.pt("shoulder_near", 100, 500),
               self.pt("hip_top", 400, 500, visible=False)]
        line = next(m for m in measure.compute(pts, None) if m.id == "body_line_angle")
        self.assertFalse(line.confident)
        self.assertIsNotNone(line.value)

    def test_impossible_head_height_is_unknown_not_good(self):
        """A failed waterline used to produce -2.1 torso lengths and score it
        'good' because the arithmetic came out negative."""
        pts = [self.pt("head_top", 300, 500),
               self.pt("shoulder_near", 400, 520),
               self.pt("hip_top", 600, 560)]
        head = next(m for m in measure.compute(pts, 100) if m.id == "head_height")
        self.assertEqual(head.verdict, "unknown")
        self.assertFalse(head.confident)

    def test_plausible_head_height_is_scored(self):
        pts = [self.pt("head_top", 300, 500),
               self.pt("shoulder_near", 400, 520),
               self.pt("hip_top", 600, 560)]
        head = next(m for m in measure.compute(pts, 495) if m.id == "head_height")
        self.assertEqual(head.verdict, "good")
        self.assertTrue(head.confident)

    def test_missing_points_produce_no_measurement(self):
        self.assertEqual(measure.compute([self.pt("ear", 10, 10)], None), [])


class TestSchemas(unittest.TestCase):
    def test_model_cannot_return_an_unmapped_fault(self):
        """Fault ids are an enum in the response schema. That is the only thing
        stopping the model inventing a problem we have no drills for."""
        schema = analyze.assessment_schema()
        enum = schema["properties"]["assessments"]["items"]["properties"]["faultId"]["enum"]
        self.assertEqual(set(enum), set(taxonomy.fault_ids()))
        triage = coach.triage_schema()
        self.assertEqual(
            set(triage["properties"]["faults"]["items"]["properties"]["faultId"]["enum"]),
            set(taxonomy.fault_ids()))

    def test_prompt_states_the_elite_reference_for_every_fault(self):
        prompt = analyze.assessment_prompt()
        for f in taxonomy.faults():
            self.assertIn(f["id"], prompt)
            self.assertIn(f["elite"][:40], prompt)

    def test_prompt_pushes_against_soft_calibration(self):
        """The model's default baseline is a club swimmer, not an elite one.
        Losing this paragraph makes everything score near zero."""
        self.assertIn("NOT a competent club swimmer", analyze.assessment_prompt())


class TestReport(unittest.TestCase):
    result = {
        "swimmerVisible": True, "viewpoint": "side", "durationSec": 12.0,
        "strokeCount": 8, "summary": "Hips are riding low.", "reportThreshold": 0.2,
        "assessments": [
            {"faultId": "low_body_position", "faultName": "Low body position",
             "deviation": 0.75, "confidence": 0.9, "timestamps": [1.5],
             "evidence": "Hips deep.", "measurements": [
                 {"id": "body_line_angle", "label": "Body line", "value": 11.0,
                  "unit": "deg", "reference": "elite 0-5", "from": [],
                  "confident": True, "verdict": "pronounced"}]},
            {"faultId": "over_rotation", "faultName": "Over-rotation",
             "deviation": 0.05, "confidence": 0.8, "timestamps": [],
             "evidence": "Fine.", "measurements": []},
        ],
        "notAssessable": [{"faultId": "scissor_kick", "faultName": "Scissor kick",
                           "reason": "Legs obscured."}],
        "drills": [{"id": "kick_sets", "title": "Kick sets", "equipment": [],
                    "summary": "Structured kicking.", "caution": "",
                    "addressesNames": ["Low body position"], "reason": "Trains hips.",
                    "addresses": ["low_body_position"]}],
    }

    def test_text_separates_reported_from_clean(self):
        out = report.text(self.result)
        self.assertIn("WHAT TO WORK ON", out)
        self.assertIn("Low body position", out)
        self.assertIn("CHECKED AND CLEAN", out)
        self.assertIn("Over-rotation", out)

    def test_text_surfaces_unassessable_and_drills(self):
        out = report.text(self.result)
        self.assertIn("Legs obscured.", out)
        self.assertIn("Kick sets", out)

    def test_markdown_lists_the_drill(self):
        self.assertIn("**Kick sets**", report.markdown(self.result))

    def test_no_swimmer_says_so_in_both_formats(self):
        empty = {"swimmerVisible": False}
        self.assertIn("No swimmer", report.text(empty))
        self.assertIn("No swimmer", report.markdown(empty))


if __name__ == "__main__":
    unittest.main(verbosity=2)
