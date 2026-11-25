import base64
import json
from unittest.mock import MagicMock, patch

from shady.local_dream import picture


def test_local_dream_stream(monkeypatch):
    monkeypatch.setenv("LOCAL_DREAM_HOST", "100.64.0.1")
    event = {"type": "complete", "width": 1, "height": 1, "channels": 3,
             "image": base64.b64encode(b"abc").decode()}
    with patch("shady.local_dream.requests.Session") as factory:
        session = factory.return_value.__enter__.return_value
        response = session.post.return_value.__enter__.return_value
        response.iter_lines.return_value = [b"event: complete", b"data: " + json.dumps(event).encode()]
        status, result = picture({"prompt": "cat"}, edit=False)
        assert status == 200
        assert result["image"].startswith("data:image/png;base64,iVBOR")
        assert session.post.call_args.kwargs["json"]["steps"] == 20
        assert session.trust_env is False


def test_reject_public_host(monkeypatch):
    monkeypatch.setenv("LOCAL_DREAM_HOST", "8.8.8.8")
    assert picture({"prompt": "cat"}, edit=False)[0] == 503
