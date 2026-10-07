"""The local HTTP server: who may talk to it, what it refuses, what it never leaks."""

from __future__ import annotations

import unittest

import _sandbox  # noqa: F401
from support.fake_gemini_server import GOOD_KEY
from support.harness import LiveServer
from swimform import config


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LiveServer()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def tearDown(self):
        config.CONFIG_PATH.unlink(missing_ok=True)

    # -- who may talk to it ----------------------------------------------

    def test_a_foreign_host_header_is_refused(self):
        """DNS rebinding: a hostile name that resolves to 127.0.0.1."""
        status, _, _ = self.srv.request("GET", "/health", host="evil.example:80")
        self.assertEqual(status, 403)

    def test_a_cross_site_origin_is_refused_on_post(self):
        status, _, _ = self.srv.request("POST", "/config", b"{}",
                                        headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_a_same_origin_post_is_allowed(self):
        status, _, _ = self.srv.request(
            "POST", "/config", b"{}", headers={"Origin": f"http://127.0.0.1:{self.srv.port}"})
        self.assertEqual(status, 200)

    def test_a_post_without_the_custom_header_is_refused(self):
        """A cross-site form or simple fetch cannot add a custom header."""
        status, _, _ = self.srv.request("POST", "/config", b"{}", csrf=False)
        self.assertEqual(status, 403)

    def test_a_cross_site_fetch_metadata_is_refused(self):
        status, _, _ = self.srv.request("POST", "/config", b"{}",
                                        headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    # -- pages and static files ------------------------------------------

    def test_the_page_is_served_with_a_strict_csp(self):
        status, hdrs, body = self.srv.request("GET", "/")
        self.assertEqual(status, 200)
        csp = hdrs["content-security-policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(hdrs["x-content-type-options"], "nosniff")

    def test_static_rejects_traversal_and_unknown_types(self):
        for path in ("/static/../server.py", "/static/..%2fserver.py",
                     "/static/%2e%2e/config.py", "/static/../../README.md", "/static/nope.js"):
            status, _, _ = self.srv.request("GET", path)
            self.assertEqual(status, 404, path)

    def test_favicon_is_quiet(self):
        status, _, _ = self.srv.request("GET", "/favicon.ico")
        self.assertEqual(status, 204)

    # -- health and settings ---------------------------------------------

    def test_health_never_reports_a_key(self):
        status, body = self.srv.json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIs(body["serverKey"], False)
        self.assertNotIn(GOOD_KEY, str(body))

    def test_config_update_merges_instead_of_resetting(self):
        self.srv.json("POST", "/config", {"fps": 3})
        status, body = self.srv.json("POST", "/config", {"overlays": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["fps"], 3)
        self.assertEqual(body["overlays"], 1)

    def test_config_rejects_unknown_or_bad_values(self):
        for bad in ({"apiKey": "x"}, {"base": "http://evil"}, {"fps": "fast"}, {"fps": 999},
                    {"models": ["../x"]}, {"models": []}, {"overlays": True}, {"reportThreshold": 2}):
            status, _ = self.srv.json("POST", "/config", bad)
            self.assertEqual(status, 400, bad)

    def test_config_never_holds_the_key(self):
        self.srv.json("POST", "/config", {"fps": 2})
        self.assertNotIn(GOOD_KEY, config.CONFIG_PATH.read_text())

    def test_oversize_json_is_refused_before_it_is_read(self):
        status, _, _ = self.srv.request("POST", "/ask", b"{}",
                                        headers={"Content-Length": str(50 * 1024 * 1024)})
        self.assertEqual(status, 413)

    def test_bad_content_length_is_a_400_not_a_crash(self):
        status, _, _ = self.srv.request("POST", "/ask", b"{}", headers={"Content-Length": "abc"})
        self.assertEqual(status, 400)

    def test_analyze_without_content_length_is_411(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port)
        conn.putrequest("POST", "/analyze", skip_host=True)
        conn.putheader("Host", f"127.0.0.1:{self.srv.port}")
        conn.putheader("X-Swimform", "1")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 411)

    def test_invalid_json_is_a_400(self):
        status, _, _ = self.srv.request("POST", "/combine", b"{not json")
        self.assertEqual(status, 400)

    # -- overlays ---------------------------------------------------------

    def test_overlay_serves_only_well_formed_names(self):
        run = config.OVERLAY_ROOT / "run_0123456789ab"
        run.mkdir(parents=True, exist_ok=True)
        (run / "overlay_1.0.png").write_bytes(b"\x89PNG fake")
        (run / "ev_x_0.jpg").write_bytes(b"jpeg fake")
        s1, h1, _ = self.srv.request("GET", "/overlay/run_0123456789ab/overlay_1.0.png")
        s2, h2, _ = self.srv.request("GET", "/overlay/run_0123456789ab/ev_x_0.jpg")
        self.assertEqual((s1, h1["content-type"]), (200, "image/png"))
        self.assertEqual((s2, h2["content-type"]), (200, "image/jpeg"))
        for bad in ("/overlay/../../etc/passwd", "/overlay/run_0123456789ab/../x.png",
                    "/overlay/run_0123456789ab/overlay_1.0.txt", "/overlay/overlays_evil/a.png",
                    "/overlay/run_0123456789abc/a.png", "/overlay/run_0123456789ab"):
            status, _, _ = self.srv.request("GET", bad)
            self.assertEqual(status, 404, bad)

    def test_purge_removes_stored_images(self):
        run = config.OVERLAY_ROOT / "run_aaaaaaaaaaaa"
        run.mkdir(parents=True, exist_ok=True)
        (run / "a.png").write_bytes(b"x")
        status, body = self.srv.json("POST", "/purge", {})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["removed"], 1)
        self.assertFalse(run.exists())

    # -- the key ----------------------------------------------------------

    def test_key_check_accepts_a_good_key_and_lists_models(self):
        status, body = self.srv.json("POST", "/key/check", {})
        self.assertEqual(status, 200)
        self.assertIs(body["valid"], True)
        self.assertIn("gemini-3.8-flash", body["models"])
        self.assertNotIn(GOOD_KEY, str(body))

    def test_key_check_rejects_a_wrong_key(self):
        status, body = self.srv.json("POST", "/key/check", {}, key="wrong-key-0123456789abcdefghij")
        self.assertEqual(status, 200)
        self.assertIs(body["valid"], False)

    def test_key_check_without_a_key(self):
        status, body = self.srv.json("POST", "/key/check", {}, key=None)
        self.assertIs(body["valid"], False)

    def test_a_malformed_key_is_a_400(self):
        status, _ = self.srv.json("POST", "/key/check", {}, key="short")
        self.assertEqual(status, 400)
        status, _ = self.srv.json("POST", "/key/check", {}, key="has spaces in it 0123456789")
        self.assertEqual(status, 400)

    def test_ask_uses_the_callers_key_and_never_echoes_it(self):
        status, body = self.srv.json("POST", "/ask", {"question": "why do my legs sink?"})
        self.assertEqual(status, 200)
        self.assertIn("Kick sets", body["answer"])
        self.assertTrue(body["drills"])
        self.assertNotIn(GOOD_KEY, str(body))
        seen = [c for c in self.srv.fake.calls if c["method"] == "POST"][-1]
        self.assertEqual({k.lower(): v for k, v in seen["headers"].items()}["x-goog-api-key"], GOOD_KEY)

    def test_the_key_is_never_logged(self):
        self.srv.json("POST", "/key/check", {})
        self.assertTrue(self.srv.log)
        self.assertNotIn(GOOD_KEY, "\n".join(self.srv.log))

    def test_a_missing_key_is_reported_as_needs_key(self):
        status, body = self.srv.json("POST", "/ask", {"question": "hello"}, key=None)
        self.assertEqual(status, 503)
        self.assertTrue(body["needsKey"])

    def test_a_wrong_key_on_a_real_call_is_reported_as_needs_key(self):
        status, body = self.srv.json("POST", "/ask", {"question": "hello"},
                                     key="wrong-key-0123456789abcdefghij")
        self.assertEqual(status, 401)
        self.assertTrue(body["needsKey"])

    def test_combine_rejects_nonsense(self):
        for bad in ({}, {"angles": []}, {"angles": [{"slot": "up", "result": {}}]},
                    {"angles": [{"slot": "side", "result": {}}, {"slot": "side", "result": {}}]},
                    {"angles": [{"slot": "side"}]}):
            status, _ = self.srv.json("POST", "/combine", bad)
            self.assertEqual(status, 400, bad)


if __name__ == "__main__":
    unittest.main()
