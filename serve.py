"""Run the ODB SHADY 6.9 web interface and authenticated API.

Required environment: SHADY_ACCESS_TOKEN (32+ characters), SHADY_API_KEY,
and SHADY_MODEL. Set secrets in the hosting platform, never in source control.
"""
from __future__ import annotations

import json
import logging
import os
import ssl
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from shady.images import EDIT_BODY_LIMIT, make_picture
from shady.web_api import ShadyAPI


ROOT = Path(__file__).resolve().parent
WEB_ROOT = (ROOT / "web").resolve()
# A maximum-length message is ~24 KB of raw UTF-8, and ~36 KB when a client
# escapes every non-ASCII character as \uXXXX. The cap must sit above the
# 6000-character rule rather than rejecting valid non-English text with a
# misleading "body too large" error.
MAX_BODY = 65_536
PICTURE_BODY_LIMIT = 65_536
MEMORY_BODY_LIMIT = 8_192

POST_BODY_LIMITS = {
    "/api/chat": MAX_BODY,
    "/api/images/create": PICTURE_BODY_LIMIT,
    "/api/images/edit": EDIT_BODY_LIMIT,
    "/api/memories": MEMORY_BODY_LIMIT,
    "/api/memories/delete": MEMORY_BODY_LIMIT,
    "/api/tasks": MAX_BODY,
    "/api/tasks/step": MEMORY_BODY_LIMIT,
    "/api/tasks/approve": MEMORY_BODY_LIMIT,
    "/api/tasks/deny": MEMORY_BODY_LIMIT,
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".webp": "image/webp",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _configure_logging() -> None:
    """Record failures to a local rotating file without echoing user text."""
    handler: logging.Handler
    try:
        path = Path(os.getenv("SHADY_LOG_PATH", "data/shady.log"))
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)


def make_handler(api: ShadyAPI):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ShadyWeb/1.0"
        protocol_version = "HTTP/1.1"
        # A stalled client cannot hold a thread forever.
        timeout = 30

        def _headers(
            self,
            status: int,
            content_type: str,
            *,
            length: int = 0,
            cache: str = "no-store",
            cookies=None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", cache)
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
            if self.close_connection:
                self.send_header("Connection", "close")
            if cookies is not None:
                for item in [cookies] if isinstance(cookies, str) else cookies:
                    self.send_header("Set-Cookie", item)
            self.end_headers()

        def _json(self, status: int, payload: dict, *, cookies=None) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._headers(
                status,
                "application/json; charset=utf-8",
                length=len(body),
                cookies=cookies,
            )
            self.wfile.write(body)

        def _bearer(self):
            authorization = self.headers.get("Authorization", "")
            return authorization[7:] if authorization.startswith("Bearer ") else None

        def _token(self):
            bearer = self._bearer()
            if bearer is not None:
                return bearer
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except CookieError:
                return None
            session = cookies.get("__Host-shady") or cookies.get("shady")
            return session.value if session else None

        def _request_is_https(self) -> bool:
            # Render terminates TLS and forwards the original scheme.
            forwarded = self.headers.get("X-Forwarded-Proto", "")
            if forwarded.split(",")[0].strip().lower() == "https":
                return True
            return isinstance(self.connection, ssl.SSLSocket)

        @staticmethod
        def _cookie(name: str, value: str, *, max_age: int, secure: bool) -> str:
            flags = "Secure; " if secure else ""
            return (
                f"{name}={value}; {flags}HttpOnly; SameSite=Strict; Path=/; "
                f"Max-Age={max_age}"
            )

        def _session_cookie(self, value: str, *, max_age: int) -> str:
            # Browsers refuse both a Secure cookie and the __Host- prefix over
            # plain HTTP, so local development gets an ordinary session cookie.
            secure = self._request_is_https()
            return self._cookie(
                "__Host-shady" if secure else "shady",
                value,
                max_age=max_age,
                secure=secure,
            )

        def _logout_cookies(self) -> list[str]:
            return [
                self._cookie("__Host-shady", "", max_age=0, secure=True),
                self._cookie("shady", "", max_age=0, secure=False),
            ]

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/session":
                if api.authorized(self._token()):
                    self._json(200, {"authenticated": True})
                else:
                    self._json(401, {"error": "Check your private access code."})
                return
            if path == "/api/health":
                self._json(200, api.health())
                return
            if path == "/api/memories":
                status, payload = api.list_memories(self._token())
                self._json(status, payload)
                return
            if path == "/api/models":
                status, payload = api.models(self._token())
                self._json(status, payload)
                return
            if path == "/api/tasks":
                status, payload = api.list_tasks(self._token())
                self._json(status, payload)
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
            body = target.read_bytes()
            content_type = CONTENT_TYPES.get(
                target.suffix.lower(), "application/octet-stream"
            )
            self._headers(
                200, content_type, length=len(body), cache="public, max-age=300"
            )
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/login":
                session = api.start_session(self._bearer())
                if session is None:
                    self._json(401, {"error": "Check your private access code."})
                else:
                    cookie = self._session_cookie(
                        session, max_age=api.SESSION_SECONDS
                    )
                    self._json(200, {"authenticated": True}, cookies=cookie)
                return
            if path == "/api/logout":
                self._json(200, {}, cookies=self._logout_cookies())
                return
            if path not in POST_BODY_LIMITS:
                # Nothing reads this body, so the connection cannot be reused.
                self.close_connection = True
                self._json(404, {"error": "Not found."})
                return
            supplied = self._token()
            if not api.authorized(supplied):
                self.close_connection = True
                self._json(401, {"error": "Check your private access code."})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                # The unread body would corrupt a reused connection.
                self.close_connection = True
                self._json(415, {"error": "Use application/json."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.close_connection = True
                self._json(400, {"error": "Invalid content length."})
                return
            if length < 1 or length > POST_BODY_LIMITS[path]:
                self.close_connection = True
                self._json(413, {"error": "Request body is empty or too large."})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "Request body must be valid JSON."})
                return
            routes = {
                "/api/chat": api.chat,
                "/api/memories": api.add_memory,
                "/api/memories/delete": api.delete_memory,
                "/api/tasks": api.create_task,
                "/api/tasks/step": api.run_task_step,
                "/api/tasks/approve": api.approve_task,
                "/api/tasks/deny": api.deny_task,
            }
            handler = routes.get(path)
            if handler is not None:
                status, response = handler(supplied, payload)
            else:
                status, response = make_picture(
                    payload, edit=path == "/api/images/edit"
                )
            self._json(status, response)

        def log_message(self, fmt: str, *args) -> None:
            # Never log request headers, chat text, or bearer credentials.
            super().log_message(fmt, *args)

    return Handler


class ShadyHTTPServer(ThreadingHTTPServer):
    """Threaded server that never lets a slow client outlive shutdown."""

    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    _configure_logging()
    token = os.environ.get("SHADY_ACCESS_TOKEN", "")
    api = ShadyAPI(access_token=token, collaborator_token=os.getenv("SHADY_BETH_ACCESS_TOKEN", ""))
    port = int(os.environ.get("PORT", "8000"))
    server = ShadyHTTPServer(("0.0.0.0", port), make_handler(api))
    print(f"ODB SHADY 6.9 listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
