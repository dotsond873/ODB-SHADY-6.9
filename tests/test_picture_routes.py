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
