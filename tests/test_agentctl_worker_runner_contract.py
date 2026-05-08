"""P0.13 local execution runner contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from video_editing_toolkit.agentctl_worker_runner import (
    WorkerExecutionBackendUnavailable,
    WorkerLocalExecutionCancelled,
    WorkerLocalExecutionError,
    WorkerLocalExecutionTimeout,
    run_local_agentctl,
)
from video_editing_toolkit.worker_pool import (
    DOCKER_EXECUTION_BACKEND,
    WorkerExecutionPoolConfig,
    WorkerExecutionPoolRegistry,
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


def test_subprocess_inflight_cancel_terminates_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    checks = iter([False, False, True])

    class FakeProcess:
        pid = 4242

        def poll(self) -> int | None:
            return None

        def communicate(self, *_args: Any, **_kwargs: Any) -> tuple[str, str]:
            raise subprocess.TimeoutExpired(cmd=["python"], timeout=0.05)

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    def fake_terminate(process: FakeProcess, *, kill_grace_seconds: int | float) -> None:
        captured["terminated_pid"] = process.pid
        captured["kill_grace_seconds"] = kill_grace_seconds

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "video_editing_toolkit.agentctl_worker_runner._terminate_process_tree",
        fake_terminate,
    )

    with pytest.raises(WorkerLocalExecutionCancelled) as exc_info:
        run_local_agentctl(
            {
                "toolkit_id": "video-editing-toolkit",
                "capability": "video.project_edit.create_project",
                "input": {"project_id": "proj_cancel"},
            },
            artifact_root=tmp_path / "artifacts",
            execution_mode="subprocess",
            timeout_seconds=10,
            cancellation_checker=lambda: next(checks),
            cancellation_check_interval_seconds=0.05,
            process_kill_grace_seconds=0.25,
        )

    assert exc_info.value.reason_code == "worker.execution_cancelled"
    assert captured["terminated_pid"] == 4242
    assert captured["kill_grace_seconds"] == 0.25
    assert "proj_cancel" not in " ".join(captured["command"])
    assert captured["kwargs"]["stdout"] is subprocess.PIPE
    assert captured["kwargs"]["stderr"] is subprocess.PIPE


def test_managed_pool_unavailable_error_includes_safe_probe(tmp_path: Path) -> None:
    registry = WorkerExecutionPoolRegistry(
        {
            DOCKER_EXECUTION_BACKEND: WorkerExecutionPoolConfig(
                backend=DOCKER_EXECUTION_BACKEND,
                enabled=False,
                endpoint="https://docker.internal/private",
            ),
        }
    )

    with pytest.raises(WorkerExecutionBackendUnavailable) as exc_info:
        run_local_agentctl(
            {
                "toolkit_id": "video-editing-toolkit",
                "capability": "video.project_edit.create_project",
                "input": {"project_id": "proj_docker"},
            },
            artifact_root=tmp_path / "artifacts",
            execution_mode=DOCKER_EXECUTION_BACKEND,
            timeout_seconds=10,
            execution_pool_registry=registry,
        )

    assert exc_info.value.reason_code == "worker.execution_backend_unavailable"
    probe = exc_info.value.probe.to_public_dict()
    assert probe["backend"] == DOCKER_EXECUTION_BACKEND
    assert probe["available"] is False
    assert "docker.internal" not in str(probe)
