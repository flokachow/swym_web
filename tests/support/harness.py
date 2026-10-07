"""Shared plumbing for tests that talk to a real swimform server on a free port."""

from __future__ import annotations

import http.client
import json
import os
import threading

from swimform import server

from .fake_gemini_server import GOOD_KEY, FakeGemini


class LiveServer:
    def __init__(self):
        # Capture the server's log instead of spraying it over the test output;
        # tests can then assert that the key never reaches it.
        self.log: list[str] = []
        self._orig_log = server.Handler.log_message
        server.Handler.log_message = lambda h, fmt, *a: self.log.append(fmt % a)
        self.fake = FakeGemini()
        os.environ["SWIMFORM_GEMINI_BASE"] = self.fake.start()
        self.httpd = server.create_server("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        server.Handler.log_message = self._orig_log
        self.httpd.shutdown()
        self.httpd.server_close()
        self.fake.stop()
        os.environ.pop("SWIMFORM_GEMINI_BASE", None)

    def request(self, method, path, body=None, headers=None, host=None, key=GOOD_KEY,
                csrf=True, timeout=120):
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if method == "POST" and csrf:
            h["X-Swimform"] = "1"
        if key:
            h["X-Gemini-Key"] = key
        h.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            data = r.read()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, data
        finally:
            conn.close()

    def json(self, method, path, obj=None, **kw):
        body = json.dumps(obj).encode() if obj is not None else None
        headers = {"Content-Type": "application/json", **kw.pop("headers", {})}
        status, hdrs, data = self.request(method, path, body, headers, **kw)
        try:
            return status, json.loads(data or b"{}")
        except json.JSONDecodeError:
            return status, {"_raw": data}
