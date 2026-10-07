"""Combining two camera angles into one verdict per fault."""

from __future__ import annotations

import unittest

import _sandbox  # noqa: F401
from swimform import merge, taxonomy

RUN = "run_0123456789ab"


def a(fault, dev=0.5, conf=0.8, stamps=(1.0,), evidence="seen", **extra):
    return {"faultId": fault, "deviation": dev, "confidence": conf,
            "timestamps": list(stamps), "evidence": evidence, **extra}


def clip(viewpoint, assessments=(), not_assessable=(), visible=True, start=0.0, summary="", **extra):
    return {"viewpoint": viewpoint, "swimmerVisible": visible, "assessments": list(assessments),
            "notAssessable": list(not_assessable), "window": {"startSec": start},
            "durationSec": 10.0, "summary": summary, "reportThreshold": 0.2, **extra}


def slot(name, result):
    return {"slot": name, "result": result}


def by_fault(combined):
    return {x["faultId"]: x for x in combined["assessments"]}


class TestPlanePreference(unittest.TestCase):
    def test_a_front_fault_is_judged_from_the_front_clip_even_when_side_is_surer(self):
        out = merge.combine([
            slot("side", clip("side", [a("crossover_entry", 0.2, 0.95)])),
            slot("front", clip("front", [a("crossover_entry", 0.7, 0.55)])),
        ])
        got = by_fault(out)["crossover_entry"]
        self.assertEqual(got["fromClip"], "front")
        self.assertEqual(got["deviation"], 0.7)

    def test_a_side_fault_is_judged_from_the_side_clip(self):
        out = merge.combine([
            slot("side", clip("side", [a("low_body_position", 0.7, 0.6)])),
            slot("front", clip("front", [a("low_body_position", 0.3, 0.99)])),
        ])
        self.assertEqual(by_fault(out)["low_body_position"]["fromClip"], "side")

    def test_without_a_plane_match_the_more_confident_clip_wins(self):
        out = merge.combine([
            slot("side", clip("unclear", [a("low_body_position", 0.5, 0.4)])),
            slot("front", clip("unclear", [a("low_body_position", 0.6, 0.9)])),
        ])
        self.assertEqual(by_fault(out)["low_body_position"]["fromClip"], "front")

    def test_a_fault_seen_by_only_one_clip_is_kept(self):
        out = merge.combine([slot("side", clip("side", [a("breathing_head_lift", 0.5)])),
                             slot("front", clip("front", []))])
        self.assertIn("breathing_head_lift", by_fault(out))


class TestUnassessed(unittest.TestCase):
    def test_rescued_by_the_other_angle(self):
        out = merge.combine([
            slot("side", clip("side", [], [{"faultId": "scissor_kick", "reason": "legs overlap"}])),
            slot("front", clip("front", [a("scissor_kick", 0.4)])),
        ])
        self.assertEqual(out["notAssessable"], [])

    def test_stays_unassessed_when_no_angle_could_judge_it(self):
        out = merge.combine([
            slot("side", clip("side", [], [{"faultId": "scissor_kick", "reason": "legs overlap"}])),
            slot("front", clip("front", [], [{"faultId": "scissor_kick", "reason": "legs hidden"}])),
        ])
        self.assertEqual(len(out["notAssessable"]), 1)
        self.assertEqual(out["notAssessable"][0]["reason"], "legs hidden")  # the right camera's reason
        self.assertEqual(out["notAssessable"][0]["faultName"], "Scissor kick")


class TestViewpoints(unittest.TestCase):
    def test_a_clip_filed_in_the_wrong_slot_is_flagged(self):
        out = merge.combine([slot("side", clip("front", [a("crossover_entry")])),
                             slot("front", clip("front", [a("scissor_kick")]))])
        kinds = {(w["slot"], w["kind"]) for w in out["warnings"]}
        self.assertIn(("side", "viewpoint_mismatch"), kinds)
        self.assertTrue(next(v for v in out["viewpoints"] if v["slot"] == "side")["mismatch"])

    def test_a_correctly_filed_pair_has_no_warnings(self):
        out = merge.combine([slot("side", clip("side")), slot("front", clip("front"))])
        self.assertEqual(out["warnings"], [])

    def test_an_unclear_angle_is_noted_not_called_a_mismatch(self):
        out = merge.combine([slot("side", clip("unclear", [a("low_body_position")]))])
        self.assertEqual([w["kind"] for w in out["warnings"]], ["viewpoint_unclear"])

    def test_no_swimmer_in_either_clip(self):
        out = merge.combine([slot("side", clip("unclear", visible=False))])
        self.assertFalse(out["swimmerVisible"])
        self.assertEqual(out["warnings"][0]["kind"], "no_swimmer")

    def test_one_clip_still_works(self):
        out = merge.combine([slot("front", clip("front", [a("crossover_entry", 0.6)]))])
        self.assertEqual(out["viewpoint"], "front")
        self.assertTrue(out["drills"])


class TestShape(unittest.TestCase):
    def test_sorted_by_deviation_times_confidence(self):
        out = merge.combine([slot("side", clip("side", [
            a("low_body_position", 0.3, 0.9), a("breathing_head_lift", 0.9, 0.9),
            a("short_stroke_finish", 0.6, 0.2)]))])
        scores = [x["deviation"] * x["confidence"] for x in out["assessments"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_moments_carry_source_file_time_and_stills(self):
        res = clip("side", [a("low_body_position", 0.7, 0.9, stamps=(1.0, 3.0),
                              evidenceFrames=[{"t": 1.0, "at": 11.0, "image": f"/overlay/{RUN}/ev_a_0.jpg"}])],
                   start=10.0)
        got = by_fault(merge.combine([slot("side", res)]))["low_body_position"]
        self.assertEqual([m["at"] for m in got["moments"]], [11.0, 13.0])
        self.assertEqual(got["moments"][0]["image"], f"/overlay/{RUN}/ev_a_0.jpg")
        self.assertIsNone(got["moments"][1]["image"])

    def test_wording_is_attached(self):
        got = by_fault(merge.combine([slot("side", clip("side", [a("low_body_position", 0.8, 0.9)]))]))
        self.assertEqual(got["low_body_position"]["severity"]["label"], "Costing you time")
        self.assertEqual(got["low_body_position"]["clarity"], "Clear in the video")

    def test_headline_names_the_biggest_fault(self):
        out = merge.combine([slot("side", clip("side", [a("low_body_position", 0.8, 0.9)]))])
        self.assertIn("Low body position", out["headline"])

    def test_nothing_above_threshold(self):
        out = merge.combine([slot("side", clip("side", [a("low_body_position", 0.05, 0.9)]))])
        self.assertIn("Nothing stands out", out["headline"])
        self.assertEqual(out["drills"], [])

    def test_drills_follow_the_merged_verdict(self):
        out = merge.combine([slot("side", clip("side", [a("low_body_position", 0.8, 0.9)]))])
        valid = {d["id"] for d in taxonomy.drills()}
        self.assertTrue(out["drills"])
        for d in out["drills"]:
            self.assertIn(d["id"], valid)


class TestUntrustedInput(unittest.TestCase):
    def test_garbage_assessments_are_dropped_not_trusted(self):
        res = clip("side", [a("nonsense_fault"), a("low_body_position", "high", 0.5),
                            a("low_body_position", float("nan"), 0.5),
                            a("breathing_head_lift", 5, -3, stamps=(-4, 1e9, "x", 2.0, 2.2)),
                            "string", None])
        out = merge.combine([slot("side", res)])
        self.assertEqual([x["faultId"] for x in out["assessments"]], ["breathing_head_lift"])
        got = out["assessments"][0]
        self.assertEqual((got["deviation"], got["confidence"]), (1.0, 0.0))  # clamped
        self.assertEqual(got["timestamps"], [2.0])  # bad values gone, 2.2 within 0.5s of 2.0

    def test_only_our_own_image_urls_survive(self):
        res = clip("side", [a("low_body_position", 0.7, 0.9, stamps=(1.0,),
                              frame={"t": 1.0, "image": "http://evil.example/x.png"},
                              evidenceFrames=[{"t": 1.0, "at": 1.0, "image": "/overlay/../../etc/passwd"}])])
        got = by_fault(merge.combine([slot("side", res)]))["low_body_position"]
        self.assertIsNone(got["frame"])
        self.assertIsNone(got["moments"][0]["image"])

    def test_bad_requests(self):
        for bad in (None, [], [slot("side", clip("side"))] * 2, [slot("above", {})],
                    [{"slot": "side", "result": "text"}], "x"):
            with self.assertRaises(merge.CombineError):
                merge.combine(bad)

    def test_text_is_length_limited(self):
        res = clip("side", [a("low_body_position", 0.7, 0.9, evidence="x" * 50000)], summary="y" * 50000)
        out = merge.combine([slot("side", res)])
        self.assertLessEqual(len(out["assessments"][0]["evidence"]), 1200)
        self.assertLessEqual(len(out["summary"]), 1200)


if __name__ == "__main__":
    unittest.main()
