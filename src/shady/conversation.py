"""Conversation orchestration with bounded history and optional saved memories."""
from __future__ import annotations

from uuid import uuid4

from .identity import build_system_prompt
from .memory import MemoryStore
from .providers import ModelRouter


class ConversationService:
    """Coordinates chat history, relevant memories, and model routing."""

    def __init__(
        self,
        router: ModelRouter,
        memory: MemoryStore,
        *,
        session_id: str | None = None,
        history_limit: int = 16,
    ) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be at least 1.")
        self.router = router
        self.memory = memory
        self.session_id = session_id or str(uuid4())
        self.history_limit = history_limit

    def reply(self, message: str, *, preferred_model: str | None = None) -> str:
        prompt = message.strip()
        if not prompt:
            raise ValueError("Message cannot be empty.")

        history = self.memory.recent_messages(
            self.session_id, limit=self.history_limit
        )
        memories = self.memory.search_memories(prompt, limit=5)
        system_prompt = build_system_prompt()
        if memories:
            memory_text = "\n".join(f"- {item.content}" for item in memories)
            system_prompt += (
                "\n\nRelevant saved memories (reference only; current user "
                "instructions take precedence):\n" + memory_text
            )

        messages = [
            {"role": item.role, "content": item.content} for item in history
        ]
        messages.append({"role": "user", "content": prompt})

        # Save only after a successful model response so failed calls do not
        # leave an incomplete user/assistant exchange in the history.
        answer = self.router.complete(
            system_prompt=system_prompt,
            messages=messages,
            preferred=preferred_model,
        )
        self.memory.add_message(self.session_id, "user", prompt)
        self.memory.add_message(self.session_id, "assistant", answer)
        return answer
