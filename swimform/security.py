"""Guards for a server that runs on your own machine.

A local server is still reachable from every web page you visit: a page on
another site can ask your browser to POST to http://127.0.0.1:8787, and a
hostile DNS name can point at 127.0.0.1 too. These checks close both doors —
the Host header must be one of ours (rebinding), the Origin must be ours
(cross-site requests), and every POST must carry a custom header, which a
cross-site page cannot send without a CORS preflight this server never grants.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# A key only has to be safe to put in a header: printable ASCII, no spaces, no line breaks.
# Providers' key formats change (some now contain dots and other symbols), so anything
# stricter than that turns a valid, freshly generated key away.
KEY_RE = re.compile(r"^[\x21-\x7e]{8,600}$")
RUN_RE = re.compile(r"^run_[0-9a-f]{12}$")
FILE_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}\.(?:png|jpg)$")

CSRF_HEADER = "X-Swimform"


def allowed_hosts(port: int, extra: tuple[str, ...] = ()) -> set[str]:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    hosts.update(h.lower() for h in extra)
    return hosts


def valid_key_shape(key: str) -> bool:
    return bool(KEY_RE.match(key or ""))


def key_problem(key: str) -> str | None:
    """Why a pasted key was refused, in words — never the key itself."""
    key = key or ""
    if re.search(r"\s", key):
        return "contains a space or line break (paste just the key, once)"
    if len(key) < 8:
        return "is too short"
    if len(key) > 600:
        return "is too long (did it get pasted twice?)"
    if re.search(r"[^\x21-\x7e]", key):
        return "contains a character that is not plain ASCII (an accented letter or curly quote?)"
    return None


def check_request(method: str, headers, hosts: set[str]) -> str | None:
    """Return a reason to refuse the request, or None to allow it.

    Every request must name one of our hosts (that is what stops DNS rebinding).
    Reads stop there: another site cannot read a response from us anyway, and a
    sandboxed frame legitimately loads our scripts from an opaque origin. Writes
    go further, because a cross-site page *can* make the browser send them.
    """
    host = (headers.get("Host") or "").lower()
    if host not in hosts:
        return "Unrecognised Host header."
    if method != "POST":
        return None

    origin = headers.get("Origin")
    if origin:
        parts = urlsplit(origin)
        if parts.scheme != "http" or (parts.netloc or "").lower() not in hosts:
            return "Cross-site requests are not allowed."

    if headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
        return "Cross-site requests are not allowed."

    if headers.get(CSRF_HEADER) != "1":
        return "Missing request header."
    return None
