import pytest

from shady.approvals import ApprovalStore
from shady.audit import AuditLog
from shady.code_tools import (
    MAX_FILE_BYTES,
    build_code_registry,
    list_files,
    read_file,
    run_python,
    write_file,
)
from shady.tools import ToolExecutor


@pytest.fixture(autouse=True)
def workspace_dir(monkeypatch, tmp_path):
    target = tmp_path / "workspace"
    monkeypatch.setenv("SHADY_WORKSPACE", str(target))
    return target


def test_write_and_read_round_trip():
    write_file("notes/hello.txt", "hi there")
    assert read_file("notes/hello.txt") == "hi there"
    assert "notes/" in list_files(".")
    assert "hello.txt" in list_files("notes")


def test_paths_cannot_escape_the_workspace():
    with pytest.raises(ValueError):
        write_file("../escape.txt", "nope")
    with pytest.raises(ValueError):
        read_file("/etc/passwd")
    with pytest.raises(ValueError):
        read_file("../../etc/passwd")


def test_files_are_size_limited():
    with pytest.raises(ValueError, match="limited"):
        write_file("big.txt", "x" * (MAX_FILE_BYTES + 1))


def test_run_python_returns_output():
    write_file("hello.py", "print('from the workspace')")
    result = run_python("hello.py")
    assert result.startswith("exit=0")
    assert "from the workspace" in result


def test_run_python_rejects_non_python_files():
    write_file("notes.txt", "hello")
    with pytest.raises(ValueError, match=r"\.py"):
        run_python("notes.txt")


def test_write_file_requires_a_one_time_approval(tmp_path):
    registry = build_code_registry()
    database = tmp_path / "approvals.sqlite3"
    executor = ToolExecutor(
        registry, ApprovalStore(database), AuditLog(database)
    )
    with pytest.raises(PermissionError):
        executor.execute("write_file", {"path": "blocked.txt", "content": "x"})

    approval = executor.request_approval("write_file")
    assert executor.approvals.approve(approval)
    assert executor.execute(
        "write_file", {"path": "ok.txt", "content": "x"}, approval_id=approval
    )
    assert (tmp_path / "workspace" / "ok.txt").read_text() == "x"
    with pytest.raises(PermissionError):
        executor.execute(
            "write_file", {"path": "again.txt", "content": "x"}, approval_id=approval
        )
