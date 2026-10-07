"""Small pure pieces: settings validation, wording, the measurement gate, the key check."""

from __future__ import annotations

import unittest

import _sandbox  # noqa: F401
from swimform import config, measure, security, wording


class TestConfig(unittest.TestCase):
    def tearDown(self):
        config.CONFIG_PATH.unlink(missing_ok=True)

    def test_unknown_keys_are_rejected(self):
        with self.assertRaises(config.ConfigError):
            config.save({"geminiKey": "x"})

    def test_values_are_type_checked(self):
        for bad in ({"fps": "2"}, {"fps": 0}, {"overlays": 1.5}, {"overlays": -1},
                    {"models": "gemini"}, {"models": ["a b"]}, {"retentionHours": 0}):
            with self.assertRaises(config.ConfigError, msg=str(bad)):
                config.save(bad)

    def test_partial_updates_merge(self):
        config.save({"fps": 3})
        config.save({"overlays": 2})
        cfg = config.load()
        self.assertEqual((cfg["fps"], cfg["overlays"]), (3, 2))

    def test_a_corrupt_stored_value_falls_back_to_the_default(self):
        config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.CONFIG_PATH.write_text('{"fps": "banana", "overlays": 1}')
        cfg = config.load()
        self.assertEqual(cfg["fps"], config.DEFAULTS["fps"])
        self.assertEqual(cfg["overlays"], 1)

    def test_models_are_deduplicated(self):
        self.assertEqual(config.save({"models": ["a", "a", "b"]})["models"], ["a", "b"])


class TestWording(unittest.TestCase):
    def test_severity_thresholds(self):
        self.assertEqual(wording.severity(0.66)["label"], "Costing you time")
        self.assertEqual(wording.severity(0.65)["label"], "Worth fixing")
        self.assertEqual(wording.severity(0.4)["label"], "Worth fixing")
        self.assertEqual(wording.severity(0.39)["label"], "Minor")

    def test_clarity_suggests_the_other_camera(self):
        self.assertEqual(wording.clarity(0.9), "Clear in the video")
        self.assertEqual(wording.clarity(0.7), "Fairly clear")
        self.assertIn("front", wording.clarity(0.2, "side"))
        self.assertIn("side", wording.clarity(0.2, "front"))


class TestMeasureGate(unittest.TestCase):
    class M:
        def __init__(self, id):
            self.id = id

    def test_measurements_attach_only_to_the_faults_they_bear_on(self):
        ms = [self.M("elbow_angle"), self.M("body_line_angle"), self.M("head_height")]
        ids = lambda fault, view: [m.id for m in measure.relevant(fault, view, ms)]  # noqa: E731
        self.assertEqual(ids("low_body_position", "side"), ["body_line_angle"])
        self.assertEqual(ids("head_position_high", "side"), ["head_height"])
        self.assertEqual(ids("dropped_elbow_catch", "side"), ["elbow_angle"])
        self.assertEqual(ids("crossover_entry", "front"), [])
        self.assertEqual(ids("low_body_position", "front"), [])  # body line needs the side camera

    def test_a_flat_body_swimming_right_to_left_is_still_flat(self):
        pt = lambda n, x, y: {"name": n, "x": x, "y": y, "visible": True}  # noqa: E731
        pts = [pt("shoulder_near", 800, 500), pt("hip_top", 500, 503)]
        line = next(m for m in measure.compute(pts, None) if m.id == "body_line_angle")
        self.assertLess(line.value, 2)
        self.assertEqual(line.verdict, "good")


class TestSecurityHelpers(unittest.TestCase):
    def test_key_shape(self):
        self.assertTrue(security.valid_key_shape("a" * 20))
        self.assertTrue(security.valid_key_shape("test-key-0123456789abcdefghij"))
        for bad in ("", "short", "has space 0123456789012345", "x" * 201, "ünicode" + "a" * 20, None):
            self.assertFalse(security.valid_key_shape(bad), bad)

    def test_hosts(self):
        hosts = security.allowed_hosts(8787)
        self.assertIn("127.0.0.1:8787", hosts)
        self.assertIn("localhost:8787", hosts)
        self.assertNotIn("evil.example", hosts)


if __name__ == "__main__":
    unittest.main()
