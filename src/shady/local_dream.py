"""Private Local Dream image generation via userspace Tailscale."""
import base64
import io
import ipaddress
import json
import os
import threading

import requests
from PIL import Image

_lock = threading.Lock()


def picture(payload, *, edit):
    from .images import photo_file
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 6000:
        return 400, {"error": "Enter picture instructions."}
    try:
        host = ipaddress.IPv4Address(os.environ["LOCAL_DREAM_HOST"])
        if host not in ipaddress.IPv4Network("100.64.0.0/10"):
            raise ValueError()
    except (KeyError, ValueError):
        return 503, {"error": "Configure the private Local Dream host."}
    fields = {"prompt": prompt.strip(), "steps": 20, "cfg": 7, "size": 512, "scheduler": "dpm"}
    if edit:
        try:
            _, raw, mime = photo_file(payload.get("photo"))
            if mime == "image/webp":
                return 400, {"error": "Use PNG or JPEG for local editing."}
            fields.update(image=base64.b64encode(raw).decode("ascii"), denoise_strength=0.6)
        except ValueError as exc:
            return 400, {"error": str(exc)}
    if not _lock.acquire(blocking=False):
        return 503, {"error": "Local Dream is busy. Try again shortly."}
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.post(f"http://{host}:8081/generate", json=fields,
                              proxies={"http": "http://127.0.0.1:1055"},
                              stream=True, allow_redirects=False, timeout=(10, 180)) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith(b"data:"):
                        continue
                    event = json.loads(line[5:])
                    if event.get("type") == "error":
                        break
                    if event.get("type") != "complete":
                        continue
                    w, h = int(event["width"]), int(event["height"])
                    if not (1 <= w <= 2048 and 1 <= h <= 2048 and event.get("channels") == 3):
                        raise ValueError("Invalid dimensions")
                    raw = base64.b64decode(event["image"], validate=True)
                    if len(raw) != w*h*3:
                        raise ValueError("Invalid image")
                    output = io.BytesIO()
                    Image.frombytes("RGB", (w,h), raw).save(output, format="PNG")
                    return 200, {"image": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")}
    except requests.Timeout:
        return 504, {"error": "Local Dream timed out."}
    except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
        pass
    finally:
        _lock.release()
    return 502, {"error": "Local Dream could not deliver an image. Check host mode and model selection."}
