"""P0.13 local execution runner contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from video_editing_toolkit.agentctl_worker_runner import (
    WorkerLocalExecutionError,
    WorkerLocalExecutionTimeout,
    run_local_agentctl,
)


def test_run_local_agentctl_rejects_unknown_execution_mode(tmp_path: Path) -> None:
    with pytest.raises(WorkerLocalExecutionError) as exc_info:
        run_local_agentctl(
            {
                "toolkit_id": "video-editing-toolkit",
                "capability": "video.project_edit.create_project",
                "input": {"project_id": "proj_invalid_mode"},
            },
            artifact_root=tmp_path / "artifacts",
            execution_mode="shell",
            timeout_seconds=10,
        )

    assert exc_info.value.reason_code == "worker.execution_mode_invalid"


def test_subprocess_timeout_is_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["python"], timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WorkerLocalExecutionTimeout) as exc_info:
        run_local_agentctl(
            {
                "toolkit_id": "video-editing-toolkit",
                "capability": "video.project_edit.create_project",
                "input": {"project_id": "proj_timeout"},
            },
            artifact_root=tmp_path / "artifacts",
            execution_mode="subprocess",
            timeout_seconds=1,
        )

    assert exc_info.value.reason_code == "resource.timeout_exceeded"


def test_subprocess_uses_stdin_without_shell_or_envelope_in_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=command, returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    response = run_local_agentctl(
        {
            "toolkit_id": "video-editing-toolkit",
            "capability": "video.project_edit.create_project",
            "input": {"project_id": "proj_stdin_only"},
        },
        artifact_root=tmp_path / "artifacts with spaces",
        execution_mode="subprocess",
        timeout_seconds=10,
    )

    rendered_argv = " ".join(captured["command"])
    assert response == {"ok": True}
    assert "proj_stdin_only" not in rendered_argv
    assert "proj_stdin_only" in captured["kwargs"]["input"]
    assert captured["kwargs"].get("shell") in {None, False}
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["check"] is False


def test_subprocess_invalid_json_is_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["python"], returncode=0, stdout="not json", stderr="secret")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WorkerLocalExecutionError) as exc_info:
        run_local_agentctl(
            {
                "toolkit_id": "video-editing-toolkit",
                "capability": "video.project_edit.create_project",
                "input": {"project_id": "proj_invalid_json"},
            },
            artifact_root=tmp_path / "artifacts",
            execution_mode="subprocess",
            timeout_seconds=10,
        )

    assert exc_info.value.reason_code == "worker.subprocess_invalid_json"
    assert "secret" not in exc_info.value.error_message
