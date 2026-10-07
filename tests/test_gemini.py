"""The Gemini client, against a local fake: key handling and the fallback chain."""

from __future__ import annotations

import os
import unittest

import _sandbox  # noqa: F401
from support.fake_gemini_server import GOOD_KEY, FakeGemini
from swimform import config, gemini


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGemini()
        os.environ["SWIMFORM_GEMINI_BASE"] = self.fake.start()
        self._sleep = gemini._sleep
        gemini._sleep = lambda s: None  # do not wait out real backoff
        config.save({"models": ["model-a", "model-b", "model-c"]})

    def tearDown(self):
        gemini._sleep = self._sleep
        os.environ.pop("SWIMFORM_GEMINI_BASE", None)
        self.fake.stop()
        config.CONFIG_PATH.unlink(missing_ok=True)

    def models_called(self):
        return [c["model"] for c in self.fake.calls if c["method"] == "POST"]

    def test_key_travels_in_the_header_never_the_url(self):
        gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        call = self.fake.calls[-1]
        lowered = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(lowered["x-goog-api-key"], GOOD_KEY)
        self.assertNotIn("key=", call["path"])

    def test_a_missing_model_falls_through_to_the_next(self):
        self.fake.behaviours = {"model-a": ["404"]}
        out = gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        self.assertIn("Kick sets", out)
        self.assertEqual(self.models_called(), ["model-a", "model-b"])

    def test_a_timeout_moves_straight_to_the_next_model(self):
        self.fake.behaviours = {"model-a": ["timeout"]}
        gemini.generate([{"text": "hi"}], None, GOOD_KEY, timeout=1)
        self.assertEqual(self.models_called(), ["model-a", "model-b"])  # one try, not three

    def test_repeated_network_failure_still_reaches_the_next_model(self):
        """The old client gave up the whole run after three failures on model 1."""
        self.fake.behaviours = {"model-a": ["drop", "drop", "drop"]}
        gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        self.assertEqual(self.models_called(), ["model-a"] * 3 + ["model-b"])

    def test_a_busy_model_is_retried_before_falling_back(self):
        self.fake.behaviours = {"model-a": ["429", "503"]}
        gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        self.assertEqual(self.models_called(), ["model-a"] * 3)

    def test_a_bad_request_on_one_model_tries_the_next(self):
        self.fake.behaviours = {"model-a": ["400"]}
        gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        self.assertEqual(self.models_called(), ["model-a", "model-b"])

    def test_a_rejected_key_stops_at_once(self):
        with self.assertRaises(gemini.GeminiKeyError):
            gemini.generate([{"text": "hi"}], None, "wrong-key-0123456789abcdefghij")
        self.assertEqual(len(self.models_called()), 1)

    def test_a_scripted_401_is_a_key_error_too(self):
        self.fake.behaviours = {"model-a": ["401"]}
        with self.assertRaises(gemini.GeminiKeyError):
            gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        self.assertEqual(len(self.models_called()), 1)

    def test_a_model_name_cannot_smuggle_a_path(self):
        for bad in ("../x", "a/b", "a b", "x" * 80, "a?b=c"):
            with self.assertRaises(gemini.GeminiError):
                gemini.generate([{"text": "hi"}], None, GOOD_KEY, model=bad)
        self.assertEqual(self.models_called(), [])

    def test_the_key_never_appears_in_an_error(self):
        self.fake.behaviours = {m: ["echo503"] * 3 for m in ("model-a", "model-b", "model-c")}
        with self.assertRaises(gemini.GeminiError) as ctx:
            gemini.generate([{"text": "hi"}], None, GOOD_KEY)
        self.assertNotIn(GOOD_KEY, str(ctx.exception))

    def test_scrub(self):
        self.assertEqual(gemini.scrub("a SECRET b", "SECRET"), "a [key] b")
        self.assertEqual(gemini.scrub("a b", None), "a b")

    def test_unreachable_api_fails_with_a_readable_error(self):
        self.fake.stop()
        with self.assertRaises(gemini.GeminiError) as ctx:
            gemini.generate([{"text": "hi"}], None, GOOD_KEY, timeout=2)
        self.assertIn("No model", str(ctx.exception))

    def test_schema_requests_return_parsed_json(self):
        out = gemini.generate(
            [{"text": "runs from 0.0 to 6.0 seconds"}],
            {"type": "object", "properties": {"assessments": {}}}, GOOD_KEY)
        self.assertIn("assessments", out)


class ListModelsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGemini()
        os.environ["SWIMFORM_GEMINI_BASE"] = self.fake.start()

    def tearDown(self):
        os.environ.pop("SWIMFORM_GEMINI_BASE", None)
        self.fake.stop()

    def test_lists_only_models_that_can_generate(self):
        self.assertEqual(gemini.list_models(GOOD_KEY), ["gemini-3.8-flash", "gemini-3.7-flash"])

    def test_follows_a_second_page(self):
        self.fake.pages = 2
        names = gemini.list_models(GOOD_KEY)
        self.assertIn("gemini-3.8-flash", names)

    def test_rejects_a_bad_key(self):
        with self.assertRaises(gemini.GeminiKeyError):
            gemini.list_models("wrong-key-0123456789abcdefghij")

    def test_costs_no_generation(self):
        gemini.list_models(GOOD_KEY)
        self.assertTrue(all(c["method"] == "GET" for c in self.fake.calls))


if __name__ == "__main__":
    unittest.main()
