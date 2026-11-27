"""Exercise the same HTTP routes used by the mobile client."""
import base64
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest
import requests

from serve import make_handler
from shady.memory import MemoryStore
from shady.web_api import ShadyAPI


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADY_API_KEY", "test-chat")
    api = ShadyAPI(access_token="a"*32, collaborator_token="b"*32,
                   memory=MemoryStore(tmp_path / "test.sqlite"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("action,code", [("create", "a"), ("edit", "b")])
def test_picture_routes(service, monkeypatch, action, code):
    monkeypatch.setenv("OPENAI_API_KEY", "test-image")
    encoded = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j/MsAAAAASUVORK5CYII="
    png = base64.b64decode(encoded)

    def fake_post(url, *, headers, timeout, **options):
        assert headers["Authorization"] == "Bearer test-image"
        if action == "edit":
            assert url.endswith("/images/edits")
            assert options["files"]["image"][1] == png
        else:
            assert url.endswith("/images/generations")
        assert options.get("data", options.get("json"))["prompt"] == "sample"
        class ImageResponse:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"data": [{"b64_json": encoded}]}
        return ImageResponse()
    monkeypatch.setattr("shady.images.requests.post", fake_post)
    client = requests.Session()
    client.headers["Authorization"] = "Bearer " + code*32
    assert client.get(service + "/api/session").status_code == 200
    route = service + "/api/images/" + action
    assert requests.get(service + "/api/session").status_code == 401
    assert requests.Session().post(route, json={}).status_code == 401
    if action == "edit":
        assert client.post(route, json={"prompt": "sample"}).status_code == 400
    result = client.post(route, json={"prompt": "sample", "photo": encoded})
    assert result.status_code == 200
    assert result.json()["image"] == "data:image/png;base64," + encoded
    monkeypatch.delenv("OPENAI_API_KEY")
    assert client.post(route, json={"prompt": "sample"}).status_code == 503


def test_https_requests_receive_a_secure_host_prefixed_cookie(service):
    login = requests.post(
        service + "/api/login",
        headers={"Authorization": "Bearer " + "a"*32, "X-Forwarded-Proto": "https"},
    )
    cookie = login.headers["Set-Cookie"]
    assert cookie.startswith("__Host-shady=")
    assert "Secure" in cookie
    headers = {"Cookie": cookie.split(";")[0]}
    assert requests.get(service + "/api/session", headers=headers).ok


def test_responses_are_length_delimited(service):
    health = requests.get(service + "/api/health")
    assert health.headers["Content-Length"] == str(len(health.content))
    page = requests.get(service + "/")
    assert page.headers["Content-Length"] == str(len(page.content))
    assert requests.get(service + "/api/models").status_code == 401


def test_head_requests_are_answered_without_a_body(service):
    # Uptime monitors and link previews probe with HEAD. It shares the GET
    # routing, so the headers must match while no body is written.
    for path in ("/", "/api/health"):
        head = requests.head(service + path)
        page = requests.get(service + path)
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["Content-Length"] == page.headers["Content-Length"]
    assert requests.head(service + "/api/models").status_code == 401
    assert requests.head(service + "/nope").status_code == 404


def test_memory_routes_require_auth_and_persist(service):
    assert requests.get(service + "/api/memories").status_code == 401
    login = requests.post(service + "/api/login", headers={"Authorization": "Bearer " + "a"*32})
    headers = {"Cookie": login.headers["Set-Cookie"].split(";")[0]}
    created = requests.post(service + "/api/memories", headers=headers,
                            json={"content": "Owner likes mint"})
    assert created.status_code == 201
    listing = requests.get(service + "/api/memories", headers=headers).json()["memories"]
    assert [item["content"] for item in listing] == ["Owner likes mint"]
    removed = requests.post(service + "/api/memories/delete", headers=headers,
                            json={"id": listing[0]["id"]})
    assert removed.status_code == 200
    assert requests.get(service + "/api/memories", headers=headers).json()["memories"] == []


def test_session_survives_requests_without_resending_code(service, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for code in ("a"*32, "b"*32):
        login = requests.post(service + "/api/login", headers={"Authorization": "Bearer " + code})
        assert login.status_code == 200
        cookie = login.headers["Set-Cookie"]
        # The fixture serves plain HTTP, where browsers reject both the Secure
        # flag and the __Host- prefix, so a working local cookie looks like this.
        assert "HttpOnly" in cookie and code not in cookie
        assert "Secure" not in cookie and cookie.startswith("shady=")
        headers = {"Cookie": cookie.split(";")[0]}
        assert requests.get(service + "/api/session", headers=headers).ok
        for action in ("create", "edit"):
            assert requests.post(service + "/api/images/" + action, headers=headers, json={}).status_code == 503
        assert requests.get(service + "/api/session", headers=headers).ok
        assert requests.post(service + "/api/chat", headers=headers, json={}).status_code == 400
        assert requests.get(service + "/api/session", headers={"Cookie": headers["Cookie"] + "x"}).status_code == 401
        assert "Max-Age=0" in requests.post(service + "/api/logout", headers=headers).headers["Set-Cookie"]
    assert requests.post(service + "/api/login").status_code == 401
