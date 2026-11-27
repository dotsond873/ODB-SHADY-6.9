"""Local code workspace: read, write and run files under an approval gate.

Everything here runs on the host with no network service and no paid API, so
code work costs nothing beyond the model call that proposed the plan. The
workspace is a guard rail, not a hardened sandbox: ``run_python`` executes a
script on this machine with CPU, memory and file-size limits, so a plan step
that runs code is classified as consequential and always needs approval.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .permissions import ActionRisk
from .tools import ToolDefinition, ToolRegistry

MAX_FILE_BYTES = 256 * 1024
MAX_READ_BYTES = 64 * 1024
MAX_OUTPUT_CHARS = 4000
MAX_LISTED_ENTRIES = 200
RUN_TIMEOUT_SECONDS = 15
IGNORED_NAMES = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def workspace() -> Path:
    """Return (and create) the directory the code tools may touch."""
    root = Path(os.getenv("SHADY_WORKSPACE", "data/workspace")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve(relative: object, *, must_exist: bool = False) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("A file path inside the code workspace is required.")
    root = workspace()
    candidate = (root / relative.strip()).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Paths must stay inside the code workspace.")
    if must_exist and not candidate.exists():
        raise ValueError(f"No such file: {relative.strip()}")
    return candidate


def list_files(path: str = ".") -> str:
    """List the workspace, or one directory inside it."""
    root = workspace()
    target = _resolve(path)
    if target.is_file():
        return target.relative_to(root).as_posix()
    if not target.is_dir():
        raise ValueError("That path does not exist.")
    entries: list[str] = []
    for item in sorted(target.iterdir(), key=lambda entry: entry.name):
        if item.name in IGNORED_NAMES:
            continue
        entries.append(item.name + ("/" if item.is_dir() else ""))
        if len(entries) >= MAX_LISTED_ENTRIES:
            entries.append("... (truncated)")
            break
    return "\n".join(entries) or "(empty)"


def read_file(path: str) -> str:
    """Return the text of one workspace file, truncated at the read limit."""
    target = _resolve(path, must_exist=True)
    if not target.is_file():
        raise ValueError("That path is a directory.")
    return target.read_bytes()[:MAX_READ_BYTES].decode("utf-8", "replace")


def write_file(path: str, content: str) -> str:
    """Create or replace one workspace file atomically."""
    if not isinstance(content, str):
        raise ValueError("content must be text.")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"Files are limited to {MAX_FILE_BYTES} bytes.")
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    return f"Wrote {len(data)} bytes to {target.relative_to(workspace()).as_posix()}"


def _limit_resources() -> None:  # pragma: no cover - runs in the child process
    try:
        import resource
    except ImportError:
        return
    limits = (
        (resource.RLIMIT_CPU, RUN_TIMEOUT_SECONDS),
        (resource.RLIMIT_AS, 512 * 1024 * 1024),
        (resource.RLIMIT_FSIZE, 8 * 1024 * 1024),
        (resource.RLIMIT_NOFILE, 64),
    )
    for kind, value in limits:
        try:
            resource.setrlimit(kind, (value, value))
        except (ValueError, OSError):
            pass


def run_python(path: str) -> str:
    """Run a workspace ``.py`` file in a child process and return its output."""
    target = _resolve(path, must_exist=True)
    if target.suffix != ".py":
        raise ValueError("run_python only runs .py files in the workspace.")
    if not target.is_file():
        raise ValueError("That path is a directory.")
    environment = {
        "PATH": os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workspace()),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(target)],
            cwd=str(workspace()),
            env=environment,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SECONDS,
            preexec_fn=_limit_resources if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return f"Timed out after {RUN_TIMEOUT_SECONDS} seconds."
    output = (completed.stdout or "") + (completed.stderr or "")
    return f"exit={completed.returncode}\n{output or '(no output)'}"[:MAX_OUTPUT_CHARS]


def build_code_registry() -> ToolRegistry:
    """Register the code tools. Application code owns this allowlist."""
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="list_files",
        description="List files and folders in the local code workspace.",
        risk=ActionRisk.READ_ONLY,
        handler=list_files,
        required_arguments=frozenset(),
        allowed_arguments=frozenset({"path"}),
    ))
    registry.register(ToolDefinition(
        name="read_file",
        description="Read one text file from the local code workspace.",
        risk=ActionRisk.READ_ONLY,
        handler=read_file,
        required_arguments=frozenset({"path"}),
        allowed_arguments=frozenset({"path"}),
    ))
    registry.register(ToolDefinition(
        name="write_file",
        description=(
            "Create or replace a text file in the local code workspace. "
            "The full file content must be supplied."
        ),
        risk=ActionRisk.REVERSIBLE,
        handler=write_file,
        required_arguments=frozenset({"path", "content"}),
        allowed_arguments=frozenset({"path", "content"}),
    ))
    registry.register(ToolDefinition(
        name="run_python",
        description=(
            "Run a Python file already in the workspace and return its output. "
            "Runs on the host with CPU, memory and file-size limits."
        ),
        risk=ActionRisk.CONSEQUENTIAL,
        handler=run_python,
        required_arguments=frozenset({"path"}),
        allowed_arguments=frozenset({"path"}),
    ))
    return registry
