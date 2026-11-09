"""Run the ODB SHADY 6.9 web interface and authenticated API.

Required environment: SHADY_ACCESS_TOKEN (32+ characters), SHADY_API_KEY,
and SHADY_MODEL. Set secrets in the hosting platform, never in source control.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from shady.web_api import ShadyAPI


ROOT = Path(__file__).resolve().parent
WEB_ROOT = (ROOT / "web").resolve()
MAX_BODY = 16_384


def make_handler(api: ShadyAPI):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ShadyWeb/1.0"

        def _headers(self, status: int, content_type: str, *, cache: str = "no-store") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", cache)
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
            self.end_headers()

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8")
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                self._json(200, api.health())
                return
            if path == "/":
                target = WEB_ROOT / "index.html"
            elif path.startswith("/assets/"):
                target = (WEB_ROOT / unquote(path.lstrip("/"))).resolve()
                if WEB_ROOT not in target.parents:
                    self._json(404, {"error": "Not found."})
                    return
            else:
                self._json(404, {"error": "Not found."})
                return
            if not target.is_file():
                self._json(404, {"error": "Not found."})
                return
            content_type = "image/webp" if target.suffix == ".webp" else "text/html; charset=utf-8"
            self._headers(200, content_type, cache="public, max-age=300")
            self.wfile.write(target.read_bytes())

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/chat":
                self._json(404, {"error": "Not found."})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._json(415, {"error": "Use application/json."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "Invalid content length."})
                return
            if length < 1 or length > MAX_BODY:
                self._json(413, {"error": "Request body is empty or too large."})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "Request body must be valid JSON."})
                return
            authorization = self.headers.get("Authorization", "")
            supplied = authorization[7:] if authorization.startswith("Bearer ") else None
            status, response = api.chat(supplied, payload)
            self._json(status, response)

        def log_message(self, fmt: str, *args) -> None:
            # Never log request headers, chat text, or bearer credentials.
            super().log_message(fmt, *args)

    return Handler


def main() -> None:
    token = os.environ.get("SHADY_ACCESS_TOKEN", "")
    api = ShadyAPI(access_token=token)
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(api))
    print(f"ODB SHADY 6.9 listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
