"""The whole dual-angle flow over HTTP, against the fake Gemini.

Real ffmpeg, real Pillow, real merge — only the model is faked. The clips are
test patterns generated on the spot; nothing swim-related is committed. Skipped
when ffmpeg is not installed.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import _sandbox  # noqa: F401
from support.fake_providers import GOOD_KEY, KEYS
from support.harness import LiveServer
from swimform import config

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_clip(path: Path, seconds: int) -> bytes:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc=duration={seconds}:size=320x240:rate=15", "-pix_fmt", "yuv420p", str(path)],
        check=True)
    return path.read_bytes()


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class DualAngleFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="swimform-clips-"))
        cls.short = make_clip(cls.tmp / "short.mp4", 6)    # the fake reads this as a side view
        cls.long = make_clip(cls.tmp / "long.mp4", 9)      # ...and this as a front view
        cls.srv = LiveServer()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def analyse(self, video: bytes, viewpoint: str, start=None, end=None, key=GOOD_KEY, provider=None):
        headers = {"X-Viewpoint": viewpoint}
        if start is not None:
            headers["X-Start-Sec"] = str(start)
        if end is not None:
            headers["X-End-Sec"] = str(end)
        status, _, data = self.srv.request("POST", "/analyze", video, headers, key=key, provider=provider)
        return status, json.loads(data)

    def test_two_angles_become_one_verdict(self):
        s1, side = self.analyse(self.short, "side")
        s2, front = self.analyse(self.long, "front")
        self.assertEqual((s1, s2), (200, 200), (side, front))

        # Privacy and hygiene of the per-clip result.
        for res in (side, front):
            self.assertNotIn("video", res)
            self.assertNotIn("overlayDir", res)
            self.assertNotIn("/tmp", json.dumps(res))
            self.assertTrue(res["runId"].startswith("run_"))
        self.assertNotEqual(side["runId"], front["runId"])

        status, combined = self.srv.json("POST", "/combine", {"angles": [
            {"slot": "side", "result": side}, {"slot": "front", "result": front}]})
        self.assertEqual(status, 200, combined)
        got = {a["faultId"]: a for a in combined["assessments"]}

        self.assertEqual(got["low_body_position"]["fromClip"], "side")
        self.assertEqual(got["crossover_entry"]["fromClip"], "front")
        self.assertEqual(got["scissor_kick"]["fromClip"], "front")
        self.assertEqual(combined["notAssessable"], [])   # the front clip rescued the rest
        self.assertEqual(combined["warnings"], [])
        self.assertTrue(combined["drills"])
        self.assertIn("markdown", combined)

        # Evidence stills and an annotated frame exist and are servable.
        moment_images = [m["image"] for a in combined["assessments"] for m in a["moments"] if m["image"]]
        self.assertTrue(moment_images, "expected evidence stills")
        for url in moment_images[:3]:
            status, hdrs, body = self.srv.request("GET", url)
            self.assertEqual((status, hdrs["content-type"]), (200, "image/jpeg"))
            self.assertGreater(len(body), 500)
        framed = [a for a in combined["assessments"] if a.get("frame")]
        self.assertTrue(framed, "expected at least one annotated frame")
        status, hdrs, _ = self.srv.request("GET", framed[0]["frame"]["image"])
        self.assertEqual((status, hdrs["content-type"]), (200, "image/png"))

    def test_the_other_providers_run_the_same_flow_from_frames(self):
        for provider in ("openai", "anthropic"):
            key = KEYS[provider]
            s1, side = self.analyse(self.short, "side", key=key, provider=provider)
            s2, front = self.analyse(self.long, "front", key=key, provider=provider)
            self.assertEqual((s1, s2), (200, 200), (side, front))
            for res in (side, front):
                self.assertEqual((res["provider"], res["mode"]), (provider, "frames"))
            status, combined = self.srv.json("POST", "/combine", {"angles": [
                {"slot": "side", "result": side}, {"slot": "front", "result": front}]})
            self.assertEqual(status, 200, combined)
            self.assertEqual((combined["provider"], combined["mode"]), (provider, "frames"))
            got = {a["faultId"]: a for a in combined["assessments"]}
            self.assertEqual(got["low_body_position"]["fromClip"], "side")
            self.assertEqual(got["crossover_entry"]["fromClip"], "front")
            self.assertEqual(combined["notAssessable"], [])
            calls = [c for c in self.srv.fake.calls if c["method"] == "POST" and c["provider"] == provider]
            self.assertTrue(calls)
            self.assertNotIn(key, json.dumps(side) + json.dumps(combined) + "\n".join(self.srv.log))

    def test_gemini_results_say_they_were_watched_as_video(self):
        status, res = self.analyse(self.short, "side")
        self.assertEqual((res["provider"], res["mode"]), ("gemini", "video"))

    def test_nothing_is_left_behind_but_the_stills(self):
        self.analyse(self.short, "side")
        self.assertEqual(list(config.UPLOAD_DIR.glob("*")), [], "uploaded video must be deleted")
        for run in config.OVERLAY_ROOT.iterdir():
            raw = [f.name for f in run.glob("frame_*.jpg")]
            self.assertEqual(raw, [], "raw frames are not kept")

    def test_swapped_slots_are_flagged(self):
        _, a = self.analyse(self.long, "side")    # a front-looking clip filed as side
        _, b = self.analyse(self.short, "front")  # a side-looking clip filed as front
        _, combined = self.srv.json("POST", "/combine", {"angles": [
            {"slot": "side", "result": a}, {"slot": "front", "result": b}]})
        kinds = sorted(w["kind"] for w in combined["warnings"])
        self.assertEqual(kinds, ["viewpoint_mismatch", "viewpoint_mismatch"])

    def test_a_trim_window_shifts_seek_times_to_the_source_file(self):
        status, res = self.analyse(self.long, "front", start=2, end=8)   # a 6s window -> reads as side
        self.assertEqual(status, 200, res)
        self.assertEqual(res["window"]["startSec"], 2.0)
        self.assertAlmostEqual(res["durationSec"], 6.0, places=1)
        _, combined = self.srv.json("POST", "/combine", {"angles": [{"slot": "front", "result": res}]})
        for a in combined["assessments"]:
            for m in a["moments"]:
                self.assertAlmostEqual(m["at"], round(2 + m["t"], 1), places=1)
                self.assertLessEqual(m["t"], 6.0)

    def test_bad_windows_are_refused_politely(self):
        status, res = self.analyse(self.short, "side", start=5, end=3)
        self.assertEqual(status, 400)
        self.assertIn("after the start", res["error"])
        status, res = self.analyse(self.short, "side", start=500)
        self.assertEqual(status, 400)

    def test_the_server_stays_responsive_during_an_analysis(self):
        self.srv.fake.delay = 1.0
        try:
            out = {}
            t = threading.Thread(target=lambda: out.update(r=self.analyse(self.short, "side")))
            t.start()
            time.sleep(0.4)
            began = time.time()
            status, _ = self.srv.json("GET", "/health")
            self.assertEqual(status, 200)
            self.assertLess(time.time() - began, 0.6, "health blocked behind an analysis")
            t.join()
            self.assertEqual(out["r"][0], 200)
        finally:
            self.srv.fake.delay = 0.0

    def test_a_third_simultaneous_analysis_is_refused(self):
        self.srv.fake.delay = 1.5
        results = []
        try:
            threads = [threading.Thread(target=lambda: results.append(self.analyse(self.short, "side")[0]))
                       for _ in range(3)]
            for t in threads:
                t.start()
                time.sleep(0.15)
            for t in threads:
                t.join()
        finally:
            self.srv.fake.delay = 0.0
        self.assertEqual(sorted(results), [200, 200, 429])

    def test_the_key_never_reaches_the_log_or_a_response(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, res = self.analyse(self.short, "side")
        self.assertEqual(status, 200)
        self.assertNotIn(GOOD_KEY, json.dumps(res))
        self.assertNotIn(GOOD_KEY, buf.getvalue())
        self.assertNotIn(GOOD_KEY, "\n".join(self.srv.log))

    def test_a_wrong_key_is_reported_before_any_work_is_wasted(self):
        status, res = self.analyse(self.short, "side", key="wrong-key-0123456789abcdefghij")
        self.assertEqual(status, 401)
        self.assertTrue(res["needsKey"])

    def test_a_non_video_upload_is_a_400(self):
        status, _, data = self.srv.request("POST", "/analyze", b"this is not a video",
                                           {"X-Viewpoint": "side"})
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(data))

    def test_an_unknown_viewpoint_is_a_400(self):
        status, _, _ = self.srv.request("POST", "/analyze", self.short, {"X-Viewpoint": "up"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
