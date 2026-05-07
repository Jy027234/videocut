"""Local execution runners for the external agentctl worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from video_editing_toolkit.agentctl import run_agentctl


IN_PROCESS_EXECUTION_MODE = "in_process"
SUBPROCESS_EXECUTION_MODE = "subprocess"
DOCKER_EXECUTION_BACKEND = "docker"
REMOTE_EXECUTION_BACKEND = "remote"
SUPPORTED_EXECUTION_MODES = frozenset(
    {
        IN_PROCESS_EXECUTION_MODE,
        SUBPROCESS_EXECUTION_MODE,
    }
)
SUPPORTED_EXECUTION_BACKENDS = frozenset(
    {
        IN_PROCESS_EXECUTION_MODE,
        SUBPROCESS_EXECUTION_MODE,
        DOCKER_EXECUTION_BACKEND,
        REMOTE_EXECUTION_BACKEND,
    }
)


class WorkerLocalExecutionError(RuntimeError):
    def __init__(self, reason_code: str, error_message: str) -> None:
        super().__init__(error_message)
        self.reason_code = reason_code
        self.error_message = error_message


class WorkerLocalExecutionTimeout(WorkerLocalExecutionError):
    def __init__(self) -> None:
        super().__init__(
            "resource.timeout_exceeded",
            "Local toolkit execution exceeded the configured timeout.",
        )


class WorkerExecutionBackendUnavailable(WorkerLocalExecutionError):
    def __init__(self, execution_backend: str) -> None:
        super().__init__(
            "worker.execution_backend_unavailable",
            "Configured worker execution backend is not available in this P0.14 build.",
        )
        self.execution_backend = execution_backend


def run_local_agentctl(
    envelope: Mapping[str, Any],
    *,
    artifact_root: str | Path,
    execution_mode: str,
    timeout_seconds: int | float,
) -> dict[str, Any]:
    if execution_mode == IN_PROCESS_EXECUTION_MODE:
        return run_agentctl(envelope, artifact_root=artifact_root)
    if execution_mode == SUBPROCESS_EXECUTION_MODE:
        return run_agentctl_subprocess(
            envelope,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
        )
    if execution_mode in {DOCKER_EXECUTION_BACKEND, REMOTE_EXECUTION_BACKEND}:
        raise WorkerExecutionBackendUnavailable(execution_mode)
    raise WorkerLocalExecutionError(
        "worker.execution_mode_invalid",
        "Worker execution mode is not supported.",
    )


def run_agentctl_subprocess(
    envelope: Mapping[str, Any],
    *,
    artifact_root: str | Path,
    timeout_seconds: int | float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "video_editing_toolkit.agentctl",
        "--artifact-root",
        str(artifact_root),
    ]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(dict(envelope), ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerLocalExecutionTimeout() from exc
    except OSError as exc:
        raise WorkerLocalExecutionError(
            "worker.subprocess_unavailable",
            "Local toolkit subprocess could not be started.",
        ) from exc

    stdout = completed.stdout.strip()
    if not stdout:
        raise WorkerLocalExecutionError(
            "worker.subprocess_no_output",
            "Local toolkit subprocess did not return JSON output.",
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WorkerLocalExecutionError(
            "worker.subprocess_invalid_json",
            "Local toolkit subprocess returned invalid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise WorkerLocalExecutionError(
            "worker.subprocess_invalid_json",
            "Local toolkit subprocess returned a non-object JSON payload.",
        )
    return payload


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src_root = Path(__file__).resolve().parents[1]
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing else f"{src_root}{os.pathsep}{existing}"
    return env
