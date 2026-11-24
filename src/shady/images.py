"""Owner-only picture creation and editing through the OpenAI Images API."""
import base64
import binascii
import os

import requests

PHOTO_LIMIT = 10 * 1024 * 1024
EDIT_BODY_LIMIT = 4 * ((PHOTO_LIMIT + 2) // 3) + 65536


def photo_file(encoded):
    if not isinstance(encoded, str):
        raise ValueError("Choose a photo to edit.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("The uploaded photo could not be read.") from None
    if len(raw) > PHOTO_LIMIT:
        raise ValueError("Choose a photo under 10 MB.")
    if raw.startswith(b"\xff\xd8\xff"):
        return ("photo.jpg", raw, "image/jpeg")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("photo.png", raw, "image/png")
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return ("photo.webp", raw, "image/webp")
    raise ValueError("Choose a JPEG, PNG, or WebP photo.")


def gemini_picture(payload, *, edit, key):
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 6000:
        return 400, {"error": "Enter picture instructions of up to 6000 characters."}
    parts = [{"text": prompt.strip()}]
    if edit:
        try:
            _, raw, mime = photo_file(payload.get("photo"))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode("ascii")}})
    model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
    if not model or not all(c.isalnum() or c in "-_." for c in model):
        return 503, {"error": "Check GEMINI_IMAGE_MODEL in Render."}
    try:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent",
            headers={"x-goog-api-key": key},
            json={"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}},
            timeout=(10, 240))
        if response.status_code in (401, 403, 404):
            return 502, {"error": "Check Gemini API key and image model access in Render."}
        if response.status_code == 429:
            return 429, {"error": "Gemini reached a quota or billing limit."}
        if response.status_code == 400:
            return 400, {"error": "Gemini declined the picture request."}
        response.raise_for_status()
        for candidate in response.json().get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                data = part.get("inlineData") or part.get("inline_data") or {}
                mime = data.get("mimeType") or data.get("mime_type")
                encoded = data.get("data")
                if mime in ("image/png", "image/jpeg", "image/webp") and isinstance(encoded, str):
                    _, _, actual = photo_file(encoded)
                    if actual == mime:
                        return 200, {"image": "data:" + mime + ";base64," + encoded}
    except requests.Timeout:
        return 504, {"error": "Gemini took too long to return the picture."}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        pass
    return 502, {"error": "Gemini could not deliver a picture. Try again shortly."}


def make_picture(payload, *, edit):
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        return gemini_picture(payload, edit=edit, key=gemini_key)

    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return 503, {"error": "Picture setup requires OPENAI_API_KEY in Render."}
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 6000:
        return 400, {"error": "Enter picture instructions of up to 6000 characters."}
    fields = {"model": "gpt-image-2", "prompt": prompt.strip(), "quality": "medium",
              "output_format": "png"}
    if edit:
        try:
            photo = photo_file(payload.get("photo"))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        url = "https://api.openai.com/v1/images/edits"
        options = {"data": fields, "files": {"image": photo}}
    else:
        url = "https://api.openai.com/v1/images/generations"
        options = {"json": fields}
    try:
        response = requests.post(url, headers={"Authorization": "Bearer " + key},
                                 timeout=(10, 240), **options)
        if response.status_code in (401, 403):
            return 502, {"error": "Check the OpenAI image key and model access in Render."}
        if response.status_code == 429:
            return 429, {"error": "OpenAI reached a rate or billing limit. Check your API account."}
        if response.status_code == 400:
            return 400, {"error": "OpenAI declined this picture request. Try different instructions or a different photo."}
        response.raise_for_status()
        encoded = response.json()["data"][0]["b64_json"]
        if not isinstance(encoded, str) or not encoded.startswith("iVBORw0KGgo"):
            raise ValueError("Invalid PNG")
    except requests.Timeout:
        return 504, {"error": "OpenAI took too long to return the picture."}
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError):
        return 502, {"error": "OpenAI could not deliver the picture. Try again shortly."}
    return 200, {"image": "data:image/png;base64," + encoded}
