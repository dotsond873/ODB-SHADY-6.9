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


def test_mask_preserves_original_pixels(monkeypatch):
    import io
    from PIL import Image
    monkeypatch.setenv("LOCAL_DREAM_HOST", "100.64.0.1")
    def encode(image):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
    original = Image.new("RGB", (2, 1), (255, 0, 0))
    mask = Image.new("L", (2, 1), 0)
    mask.putpixel((1, 0), 255)
    event = {"type": "complete", "width": 2, "height": 1, "channels": 3,
             "image": base64.b64encode(bytes([0, 0, 255] * 2)).decode()}
    with patch("shady.local_dream.requests.Session") as factory:
        response = factory.return_value.__enter__.return_value.post.return_value.__enter__.return_value
        response.iter_lines.return_value = [b"data: " + json.dumps(event).encode()]
        status, result = picture({"prompt": "beach", "photo": encode(original), "mask": encode(mask)}, edit=True)
        assert status == 200, result
        fields = factory.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        sent_mask = Image.open(io.BytesIO(base64.b64decode(fields["mask"])))
        assert list(sent_mask.getdata()) == [0, 255]
        output = Image.open(io.BytesIO(base64.b64decode(result["image"].split(",")[1])))
        assert output.getpixel((0, 0)) == (255, 0, 0)
        assert output.getpixel((1, 0)) == (0, 0, 255)
