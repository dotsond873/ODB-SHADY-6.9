"""Small authenticated API boundary for the Shady web interface."""
from __future__ import annotations

import hmac
import uuid
from typing import Any

from .conversation import ConversationService
from .memory import MemoryStore
from .provider_config import build_router_from_env
from .providers import ModelRouter


class ShadyAPI:
    """Owner-token-protected chat API; tokens are never returned or logged."""

    def __init__(
        self,
        *,
        access_token: str,
        router: ModelRouter | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        if len(access_token) < 32:
            raise ValueError("SHADY_ACCESS_TOKEN must be at least 32 characters.")
        self._access_token = access_token
        self.router = router or build_router_from_env()
        self.memory = memory or MemoryStore()

    def _authorized(self, supplied_token: str | None) -> bool:
        return isinstance(supplied_token, str) and hmac.compare_digest(
            supplied_token, self._access_token
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ODB SHADY 6.9",
            "model_configured": bool(self.router.available_models),
        }

    def chat(self, supplied_token: str | None, payload: Any) -> tuple[int, dict[str, Any]]:
        if not self._authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        if not isinstance(payload, dict):
            return 400, {"error": "Request body must be a JSON object."}

        message = payload.get("message")
        session_id = payload.get("session_id")
        preferred = payload.get("preferred_model")
        if not isinstance(message, str) or not message.strip():
            return 400, {"error": "Enter a message first."}
        if len(message) > 6000:
            return 413, {"error": "Message is too long (maximum 6000 characters)."}
        if not isinstance(session_id, str):
            return 400, {"error": "A valid session ID is required."}
        try:
            session_id = str(uuid.UUID(session_id))
        except (ValueError, AttributeError):
            return 400, {"error": "Session ID must be a UUID."}
        if preferred is not None and not isinstance(preferred, str):
            return 400, {"error": "Preferred model must be text."}
        if preferred and preferred not in self.router.available_models:
            return 400, {"error": "That model is not configured."}

        service = ConversationService(
            self.router, self.memory, session_id=session_id
        )
        try:
            answer = service.reply(message, preferred_model=preferred)
        except Exception:
            # Provider exceptions can contain implementation details. Keep the
            # public response generic; detailed diagnostics belong in protected logs.
            return 502, {"error": "Shady could not reach a working model. Try again shortly."}
        return 200, {"reply": answer, "session_id": session_id}
