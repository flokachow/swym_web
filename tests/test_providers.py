"""Every AI provider, against a local fake: key handling, fallback, structured output, frames.

One contract, run three times. What differs between the providers (where the key
goes, how a schema is requested, whether video is accepted) is checked per
provider; what must not differ (the fallback rules, the key staying out of errors)
is checked identically.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _sandbox  # noqa: F401
from support.fake_providers import ANTHROPIC_KEY, GOOD_KEY, KEYS, OPENAI_KEY, FakeProviders
from swimform import config, providers
from swimform.providers import base

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))
SCHEMA = {"type": "object", "properties": {"assessments": {"type": "array", "items": {
    "type": "object", "properties": {"faultId": {"type": "string"}, "deviation": {"type": "number"}}}}}}


class Contract:
    provider = ""
    wrong_key = "wrong-key-0123456789abcdefghij"
    models = ["model-a", "model-b", "model-c"]

    @property
    def key(self):
        return KEYS[self.provider]

    @property
    def setting(self):
        return providers.get(self.provider).models_setting

    def setUp(self):
        self.fake = FakeProviders()
        self.fake.start()
        self._sleep = base._sleep
        base._sleep = lambda s: None  # do not wait out real backoff
        config.save({self.setting: self.models})
        providers.get(self.provider).no_temperature.clear()

    def tearDown(self):
        base._sleep = self._sleep
        self.fake.stop()
        config.CONFIG_PATH.unlink(missing_ok=True)

    def gen(self, parts=None, schema=None, key=None, **kw):
        return providers.generate(self.provider, parts or [{"text": "hi"}], schema,
                                  key or self.key, **kw)

    def posts(self):
        return [c for c in self.fake.calls if c["method"] == "POST"]

    def models_called(self):
        return [c["model"] for c in self.posts()]

    # -- the key ----------------------------------------------------------

    def test_key_travels_in_a_header_never_the_url(self):
        self.gen()
        call = self.fake.calls[-1]
        self.assertNotIn("key=", call["path"])
        self.assert_key_header(call)

    def test_the_key_never_appears_in_an_error(self):
        self.fake.behaviours = {m: ["echo503"] * 3 for m in self.models}
        with self.assertRaises(providers.ProviderError) as ctx:
            self.gen()
        self.assertNotIn(self.key, str(ctx.exception))

    def test_a_rejected_key_stops_at_once(self):
        with self.assertRaises(providers.KeyRejected):
            self.gen(key=self.wrong_key)
        self.assertEqual(len(self.posts()), 1)

    def test_a_scripted_401_is_a_key_error_too(self):
        self.fake.behaviours = {"model-a": ["401"]}
        with self.assertRaises(providers.KeyRejected):
            self.gen()
        self.assertEqual(len(self.posts()), 1)

    # -- fallback ---------------------------------------------------------

    def test_a_missing_model_falls_through_to_the_next(self):
        self.fake.behaviours = {"model-a": ["404"]}
        self.assertIn("Kick sets", self.gen())
        self.assertEqual(self.models_called(), ["model-a", "model-b"])

    def test_a_timeout_moves_straight_to_the_next_model(self):
        self.fake.behaviours = {"model-a": ["timeout"]}
        self.gen(timeout=1)
        self.assertEqual(self.models_called(), ["model-a", "model-b"])  # one try, not three

    def test_repeated_network_failure_still_reaches_the_next_model(self):
        self.fake.behaviours = {"model-a": ["drop", "drop", "drop"]}
        self.gen()
        self.assertEqual(self.models_called(), ["model-a"] * 3 + ["model-b"])

    def test_a_busy_model_is_retried_before_falling_back(self):
        self.fake.behaviours = {"model-a": ["429", "503"]}
        self.gen()
        self.assertEqual(self.models_called(), ["model-a"] * 3)

    def test_overloaded_529_is_treated_as_busy(self):
        self.fake.behaviours = {"model-a": ["529"]}
        self.gen()
        self.assertEqual(self.models_called(), ["model-a"] * 2)

    def test_a_bad_request_on_one_model_tries_the_next(self):
        self.fake.behaviours = {"model-a": ["400"]}
        self.gen()
        self.assertEqual(self.models_called(), ["model-a", "model-b"])

    def test_a_model_name_cannot_smuggle_a_path(self):
        for bad in ("../x", "a/b", "a b", "x" * 80, "a?b=c"):
            with self.assertRaises(providers.ProviderError):
                self.gen(model=bad)
        self.assertEqual(self.posts(), [])

    def test_unreachable_service_fails_with_a_readable_error(self):
        self.fake.kill()
        with self.assertRaises(providers.ProviderError) as ctx:
            self.gen(timeout=2)
        self.assertIn("No model", str(ctx.exception))

    def test_a_model_that_refuses_temperature_is_retried_without_it_and_remembered(self):
        self.fake.behaviours = {"model-a": ["reject_temp"]}
        self.gen()
        self.gen()
        first, second, third = self.posts()[:3]
        has = lambda c: self.fake.has_temperature(self.provider, c["body"])  # noqa: E731
        self.assertTrue(has(first))
        self.assertFalse(has(second))                 # the retry
        self.assertFalse(has(third))                  # the next call did not try again
        self.assertEqual(self.models_called(), ["model-a"] * 3)

    # -- models -----------------------------------------------------------

    def test_listing_models_needs_no_generation(self):
        names = providers.list_models(self.provider, self.key)
        self.assertTrue(names)
        self.assertTrue(all(c["method"] == "GET" for c in self.fake.calls))

    def test_listing_models_rejects_a_bad_key(self):
        with self.assertRaises(providers.KeyRejected):
            providers.list_models(self.provider, self.wrong_key)


class TestGemini(Contract, unittest.TestCase):
    provider = "gemini"

    def assert_key_header(self, call):
        lowered = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(lowered["x-goog-api-key"], GOOD_KEY)
        self.assertNotIn("authorization", lowered)

    def test_structured_output_uses_a_response_schema(self):
        out = self.gen([{"text": "runs from 0.0 to 6.0 seconds"}], SCHEMA)
        self.assertIn("assessments", out)
        cfgd = self.posts()[-1]["body"]["generationConfig"]
        self.assertEqual(cfgd["response_mime_type"], "application/json")

    def test_lists_only_models_that_can_generate(self):
        self.assertEqual(providers.list_models("gemini", self.key), ["gemini-3.8-flash", "gemini-3.7-flash"])

    def test_follows_a_second_page(self):
        self.fake.pages = 2
        self.assertIn("gemini-3.8-flash", providers.list_models("gemini", self.key))


class TestOpenAI(Contract, unittest.TestCase):
    provider = "openai"
    wrong_key = "sk-wrong-0123456789abcdefghijkl"

    def assert_key_header(self, call):
        lowered = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(lowered["authorization"], f"Bearer {OPENAI_KEY}")

    def test_structured_output_is_a_strict_json_schema(self):
        out = self.gen([{"text": "runs from 0.0 to 6.0 seconds"}], SCHEMA)
        self.assertIn("assessments", out)
        fmt = self.posts()[-1]["body"]["response_format"]["json_schema"]
        self.assertTrue(fmt["strict"])

        def closed(node):
            if isinstance(node, dict):
                if node.get("type") == "object" and "properties" in node:
                    self.assertIs(node["additionalProperties"], False)
                    self.assertEqual(node["required"], list(node["properties"]))
                for v in node.values():
                    closed(v)
            elif isinstance(node, list):
                for v in node:
                    closed(v)
        closed(fmt["schema"])

    def test_lists_only_chat_models(self):
        self.assertEqual(providers.list_models("openai", self.key), ["gpt-4.1", "gpt-5"])


class TestAnthropic(Contract, unittest.TestCase):
    provider = "anthropic"
    wrong_key = "sk-ant-wrong-0123456789abcdefghij"

    def assert_key_header(self, call):
        lowered = {k.lower(): v for k, v in call["headers"].items()}
        self.assertEqual(lowered["x-api-key"], ANTHROPIC_KEY)
        self.assertEqual(lowered["anthropic-version"], "2023-06-01")

    def test_structured_output_is_a_forced_tool_call(self):
        out = self.gen([{"text": "runs from 0.0 to 6.0 seconds"}], SCHEMA)
        self.assertIn("assessments", out)
        body = self.posts()[-1]["body"]
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": "report"})
        self.assertEqual(body["tools"][0]["input_schema"], SCHEMA)
        self.assertIn("max_tokens", body)

    def test_lists_models(self):
        self.assertEqual(providers.list_models("anthropic", self.key),
                         ["claude-sonnet-5-5", "claude-haiku-4-5-20251001"])


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class TestVideoVersusFrames(unittest.TestCase):
    """Gemini watches the video; the others are sent still frames with their times."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="swimform-prov-"))
        clip = cls.tmp / "c.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=duration=6:size=320x240:rate=15", "-pix_fmt", "yuv420p", str(clip)], check=True)
        cls.video = clip.read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.fake = FakeProviders()
        self.fake.start()
        config.save({"models": ["model-a"], "modelsOpenai": ["model-a"], "modelsAnthropic": ["model-a"]})

    def tearDown(self):
        self.fake.stop()
        config.CONFIG_PATH.unlink(missing_ok=True)

    def run_clip(self, provider, fps=2.0, duration=6.0):
        parts = [{"text": f"clip runs from 0.0 to {duration} seconds"},
                 {"video": self.video, "fps": fps, "duration": duration}]
        providers.generate(provider, parts, None, KEYS[provider])
        return self.fake.calls[-1]["body"]

    def test_gemini_gets_the_video_itself(self):
        parts = self.run_clip("gemini")["contents"][0]["parts"]
        videos = [p for p in parts if "inline_data" in p]
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["inline_data"]["mime_type"], "video/mp4")
        self.assertEqual(videos[0]["video_metadata"], {"fps": 2.0})

    def test_openai_gets_labelled_frames(self):
        content = self.run_clip("openai")["messages"][0]["content"]
        images = [p for p in content if p["type"] == "image_url"]
        labels = [p["text"] for p in content if p["type"] == "text" and p["text"].startswith("Frame at")]
        self.assertTrue(5 <= len(images) <= base.MAX_FRAMES, len(images))
        self.assertEqual(len(images), len(labels))
        self.assertEqual(labels[0], "Frame at t = 0.0 s:")
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(any(p["type"] == "video" for p in content))

    def test_anthropic_gets_labelled_frames(self):
        content = self.run_clip("anthropic")["messages"][0]["content"]
        images = [p for p in content if p["type"] == "image"]
        self.assertTrue(5 <= len(images) <= base.MAX_FRAMES, len(images))
        self.assertEqual(images[0]["source"]["media_type"], "image/jpeg")

    def test_a_long_clip_is_capped_not_flooded(self):
        content = self.run_clip("openai", fps=2.0, duration=600.0)["messages"][0]["content"]
        self.assertLessEqual(len([p for p in content if p["type"] == "image_url"]), base.MAX_FRAMES)

    def test_frames_are_evenly_timed(self):
        frames, rate = base.sample_frames(self.video, 2.0, 6.0)
        self.assertAlmostEqual(rate, 2.0)
        self.assertEqual([t for t, _ in frames][:3], [0.0, 0.5, 1.0])
        self.assertGreater(len(frames[0][1]), 500)

    def test_a_non_video_is_a_clear_error(self):
        with self.assertRaises(providers.ProviderError):
            base.sample_frames(b"not a video", 2.0, 6.0)


class TestRegistry(unittest.TestCase):
    def test_gemini_is_the_recommended_native_video_provider(self):
        info = {p["id"]: p for p in providers.info()}
        self.assertTrue(info["gemini"]["recommended"] and info["gemini"]["nativeVideo"])
        self.assertFalse(info["openai"]["nativeVideo"] or info["anthropic"]["nativeVideo"])
        for p in info.values():
            self.assertTrue(p["keyUrl"].startswith("https://"))
            self.assertTrue(p["models"])

    def test_unknown_provider(self):
        with self.assertRaises(providers.ProviderError):
            providers.get("nope")

    def test_every_provider_has_an_env_key_and_a_models_setting(self):
        for pid in config.PROVIDER_IDS:
            self.assertIn(pid, config.ENV_KEYS)
            self.assertIn(providers.get(pid).models_setting, config.DEFAULTS)


if __name__ == "__main__":
    unittest.main()
