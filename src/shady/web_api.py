"""Small authenticated API boundary for the Shady web interface."""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
import uuid
from typing import Any

from .approvals import ApprovalStore
from .audit import AuditLog
from .code_tools import build_code_registry
from .conversation import ConversationService
from .memory import Memory, MemoryStore
from .planner import TaskPlanner, TaskPlanningError
from .provider_config import build_router_from_env
from .providers import ModelRouter
from .task_engine import TaskCoordinator, TaskProgress
from .tasks import Task, TaskStore
from .tools import ToolExecutor, ToolRegistry

logger = logging.getLogger("shady.api")


class ShadyAPI:
    """Owner-token-protected chat, memory and code-task API."""

    SESSION_SECONDS = 7 * 24 * 3600
    MAX_MESSAGE_CHARS = 6000
    MAX_MEMORY_CHARS = 2000
    MAX_TASK_REQUEST_CHARS = 4000

    def __init__(
        self,
        *,
        access_token: str,
        collaborator_token: str = "",
        router: ModelRouter | None = None,
        memory: MemoryStore | None = None,
        registry: ToolRegistry | None = None,
        approvals: ApprovalStore | None = None,
        audit: AuditLog | None = None,
        tasks: TaskStore | None = None,
    ) -> None:
        if len(access_token) < 32:
            raise ValueError("SHADY_ACCESS_TOKEN must be at least 32 characters.")
        if collaborator_token and len(collaborator_token) < 32:
            raise ValueError("SHADY_BETH_ACCESS_TOKEN must be at least 32 characters.")
        self._tokens = tuple(token.encode() for token in (access_token, collaborator_token) if token)
        self.router = router or build_router_from_env()
        self.memory = memory or MemoryStore()
        self._registry = registry
        self._approvals = approvals
        self._audit = audit
        self._tasks = tasks
        self._coordinator: TaskCoordinator | None = None

    def start_session(self, code: str | None) -> str | None:
        if not isinstance(code, str):
            return None
        for key in self._tokens:
            if hmac.compare_digest(code.encode(), key):
                stamp = f"s1.{int(time.time()) + self.SESSION_SECONDS}.{secrets.token_hex(16)}"
                signature = hmac.digest(key, stamp.encode(), "sha256").hex()
                return f"{stamp}.{signature}"
        return None

    def authorized(self, supplied_token: str | None) -> bool:
        if not isinstance(supplied_token, str):
            return False
        if any(hmac.compare_digest(supplied_token.encode(), key) for key in self._tokens):
            return True
        parts = supplied_token.split(".")
        if len(parts) != 4 or parts[0] != "s1" or not parts[1].isascii() or not parts[1].isdigit() or len(parts[1]) > 12:
            return False
        if int(parts[1]) <= time.time():
            return False
        stamp = ".".join(parts[:3]).encode()
        return any(hmac.compare_digest(parts[3].encode(), hmac.digest(key, stamp, "sha256").hex().encode())
                   for key in self._tokens)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ODB SHADY 6.9",
            "model_configured": bool(self.router.available_models),
        }

    def models(self, supplied_token: str | None) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        return 200, {"models": self.router.available_models}

    def _preferred_error(self, preferred: Any) -> dict[str, Any] | None:
        if preferred is None or preferred == "":
            return None
        if not isinstance(preferred, str):
            return {"error": "Preferred model must be text."}
        if preferred not in self.router.available_models:
            return {"error": "That model is not configured."}
        return None

    def chat(self, supplied_token: str | None, payload: Any) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        if not isinstance(payload, dict):
            return 400, {"error": "Request body must be a JSON object."}

        message = payload.get("message")
        session_id = payload.get("session_id")
        preferred = payload.get("preferred_model")
        if not isinstance(message, str) or not message.strip():
            return 400, {"error": "Enter a message first."}
        if len(message) > self.MAX_MESSAGE_CHARS:
            return 413, {
                "error": f"Message is too long (maximum {self.MAX_MESSAGE_CHARS} characters)."
            }
        if not isinstance(session_id, str):
            return 400, {"error": "A valid session ID is required."}
        try:
            session_id = str(uuid.UUID(session_id))
        except (ValueError, AttributeError):
            return 400, {"error": "Session ID must be a UUID."}
        invalid = self._preferred_error(preferred)
        if invalid:
            return 400, invalid

        service = ConversationService(
            self.router, self.memory, session_id=session_id
        )
        try:
            answer, provider = service.reply_with_provider(message, preferred_model=preferred or None)
        except Exception as exc:
            # Provider exceptions can contain implementation details. Keep the
            # public response generic; the local log records the failure type.
            logger.warning("chat request failed: %s", type(exc).__name__)
            return 502, {"error": "Shady could not reach a working model. Try again shortly."}
        return 200, {"reply": answer, "session_id": session_id, "provider": provider}

    @staticmethod
    def _memory_payload(memory: Memory) -> dict[str, Any]:
        return {
            "id": memory.id,
            "content": memory.content,
            "created_at": memory.created_at,
        }

    def list_memories(
        self, supplied_token: str | None, *, limit: int = 100
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        memories = self.memory.list_memories(limit=limit)
        return 200, {
            "memories": [self._memory_payload(item) for item in memories]
        }

    def add_memory(
        self, supplied_token: str | None, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        if not isinstance(payload, dict):
            return 400, {"error": "Request body must be a JSON object."}
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            return 400, {"error": "Enter something to remember."}
        if len(content) > self.MAX_MEMORY_CHARS:
            return 413, {
                "error": f"Memories are limited to {self.MAX_MEMORY_CHARS} characters."
            }
        memory = self.memory.add_memory(content)
        return 201, {"memory": self._memory_payload(memory)}

    def delete_memory(
        self, supplied_token: str | None, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        if not isinstance(payload, dict):
            return 400, {"error": "Request body must be a JSON object."}
        memory_id = payload.get("id")
        if not isinstance(memory_id, int) or isinstance(memory_id, bool):
            return 400, {"error": "A numeric memory id is required."}
        if not self.memory.delete_memory(memory_id):
            return 404, {"error": "That memory is already gone."}
        return 200, {"deleted": True}

    def _code_layer(self) -> tuple[TaskCoordinator, TaskStore]:
        """Build the code tooling on first use so chat-only use stays light."""
        if self._coordinator is None:
            self._registry = self._registry or build_code_registry()
            self._approvals = self._approvals or ApprovalStore()
            self._audit = self._audit or AuditLog()
            self._tasks = self._tasks or TaskStore()
            executor = ToolExecutor(self._registry, self._approvals, self._audit)
            self._coordinator = TaskCoordinator(
                self._tasks, executor, self._approvals
            )
        return self._coordinator, self._tasks

    @staticmethod
    def _task_payload(task: Task) -> dict[str, Any]:
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "steps": [
                {
                    "position": step.position,
                    "tool_name": step.tool_name,
                    "description": step.description,
                    "status": step.status.value,
                    "approval_id": step.approval_id,
                    "result_summary": step.result_summary,
                    "error_type": step.error_type,
                    "arguments_preview": json.dumps(step.arguments)[:400],
                }
                for step in task.steps
            ],
        }

    def _progress(
        self, progress: TaskProgress
    ) -> dict[str, Any]:
        return {
            "task": self._task_payload(progress.task),
            "state": progress.state,
            "message": progress.message,
            "approval_id": progress.approval_id,
            "step_result": progress.step_result,
        }

    def create_task(
        self, supplied_token: str | None, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        if not isinstance(payload, dict):
            return 400, {"error": "Request body must be a JSON object."}
        request = payload.get("request")
        preferred = payload.get("preferred_model")
        if not isinstance(request, str) or not request.strip():
            return 400, {"error": "Describe what Shady should build."}
        if len(request) > self.MAX_TASK_REQUEST_CHARS:
            return 413, {
                "error": f"Keep the request under {self.MAX_TASK_REQUEST_CHARS} characters."
            }
        invalid = self._preferred_error(preferred)
        if invalid:
            return 400, invalid

        coordinator, _ = self._code_layer()
        planner = TaskPlanner(self.router, self._registry, max_steps=6)
        try:
            plan = planner.propose(request, preferred_model=preferred or None)
        except TaskPlanningError as exc:
            return 422, {"error": str(exc)}
        except Exception as exc:
            logger.warning("planner failed: %s", type(exc).__name__)
            return 502, {"error": "Shady could not draft a plan right now."}
        if not plan.steps:
            return 422, {
                "error": "That request cannot be expressed with the available tools."
            }
        task = coordinator.create(plan.title, plan.steps)
        return 201, {
            "task": self._task_payload(task),
            "state": "planned",
            "message": "Plan ready. Review the steps, then run them one at a time.",
            "approval_id": None,
            "step_result": None,
        }

    def list_tasks(
        self, supplied_token: str | None, *, limit: int = 20
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        _, store = self._code_layer()
        return 200, {"tasks": [self._task_payload(task) for task in store.list_tasks(limit=limit)]}

    def _task_id(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        task_id = payload.get("task_id")
        return task_id if isinstance(task_id, str) and task_id.strip() else None

    def run_task_step(
        self, supplied_token: str | None, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        task_id = self._task_id(payload)
        if task_id is None:
            return 400, {"error": "A task id is required."}
        coordinator, _ = self._code_layer()
        try:
            progress = coordinator.run_next(task_id)
        except KeyError:
            return 404, {"error": "That task no longer exists."}
        return 200, self._progress(progress)

    def approve_task(
        self, supplied_token: str | None, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        task_id = self._task_id(payload)
        approval_id = payload.get("approval_id") if isinstance(payload, dict) else None
        if task_id is None or not isinstance(approval_id, str):
            return 400, {"error": "A task id and approval id are required."}
        coordinator, _ = self._code_layer()
        try:
            progress = coordinator.approve_and_run(
                task_id, approval_id, user_confirmed=True
            )
        except KeyError:
            return 404, {"error": "That task no longer exists."}
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return 200, self._progress(progress)

    def deny_task(
        self, supplied_token: str | None, payload: Any
    ) -> tuple[int, dict[str, Any]]:
        if not self.authorized(supplied_token):
            return 401, {"error": "Authentication required."}
        task_id = self._task_id(payload)
        approval_id = payload.get("approval_id") if isinstance(payload, dict) else None
        if task_id is None or not isinstance(approval_id, str):
            return 400, {"error": "A task id and approval id are required."}
        coordinator, _ = self._code_layer()
        try:
            task = coordinator.deny(task_id, approval_id, user_confirmed=True)
        except KeyError:
            return 404, {"error": "That task no longer exists."}
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return 200, {
            "task": self._task_payload(task),
            "state": "denied",
            "message": "Step denied. Nothing was run.",
            "approval_id": None,
            "step_result": None,
        }
