"""Local execution runners for the external agentctl worker."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from video_editing_toolkit.agentctl import run_agentctl
from video_editing_toolkit.worker_pool import (
    DOCKER_EXECUTION_BACKEND,
    IN_PROCESS_EXECUTION_MODE,
    REMOTE_EXECUTION_BACKEND,
    SUBPROCESS_EXECUTION_MODE,
    SUPPORTED_EXECUTION_BACKENDS,
    WorkerExecutionPoolRegistry,
)


SUPPORTED_EXECUTION_MODES = frozenset(
    {
        IN_PROCESS_EXECUTION_MODE,
        SUBPROCESS_EXECUTION_MODE,
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
            "Local toolkit execution exceeded the configured timeout and was terminated.",
        )


class WorkerLocalExecutionCancelled(WorkerLocalExecutionError):
    def __init__(self) -> None:
        super().__init__(
            "worker.execution_cancelled",
            "Local toolkit execution was cancelled and the child process was terminated.",
        )


class WorkerExecutionBackendUnavailable(WorkerLocalExecutionError):
    def __init__(self, execution_backend: str, *, probe: Any | None = None) -> None:
        reason_code = getattr(probe, "reason_code", None) or "worker.execution_backend_unavailable"
        super().__init__(
            str(reason_code),
            "Configured worker execution backend is not available in this P0 execution pool build.",
        )
        self.execution_backend = execution_backend
        self.probe = probe


def run_local_agentctl(
    envelope: Mapping[str, Any],
    *,
    artifact_root: str | Path,
    execution_mode: str,
    timeout_seconds: int | float,
    allowed_p1_capabilities: tuple[str, ...] = (),
    cancellation_checker: Callable[[], bool] | None = None,
    cancel_event: Any | None = None,
    cancellation_check_interval_seconds: int | float = 0.25,
    process_kill_grace_seconds: int | float = 2.0,
    execution_pool_registry: WorkerExecutionPoolRegistry | None = None,
) -> dict[str, Any]:
    if _cancel_requested(cancellation_checker=cancellation_checker, cancel_event=cancel_event):
        raise WorkerLocalExecutionCancelled()
    if execution_mode == IN_PROCESS_EXECUTION_MODE:
        return run_agentctl(
            envelope,
            artifact_root=artifact_root,
            allowed_p1_capabilities=allowed_p1_capabilities,
        )
    if execution_mode == SUBPROCESS_EXECUTION_MODE:
        return run_agentctl_subprocess(
            envelope,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
            allowed_p1_capabilities=allowed_p1_capabilities,
            cancellation_checker=cancellation_checker,
            cancel_event=cancel_event,
            cancellation_check_interval_seconds=cancellation_check_interval_seconds,
            process_kill_grace_seconds=process_kill_grace_seconds,
        )
    if execution_mode in {DOCKER_EXECUTION_BACKEND, REMOTE_EXECUTION_BACKEND}:
        registry = execution_pool_registry or WorkerExecutionPoolRegistry.from_env()
        raise WorkerExecutionBackendUnavailable(execution_mode, probe=registry.probe(execution_mode))
    raise WorkerLocalExecutionError(
        "worker.execution_mode_invalid",
        "Worker execution mode is not supported.",
    )


def run_agentctl_subprocess(
    envelope: Mapping[str, Any],
    *,
    artifact_root: str | Path,
    timeout_seconds: int | float,
    allowed_p1_capabilities: tuple[str, ...] = (),
    cancellation_checker: Callable[[], bool] | None = None,
    cancel_event: Any | None = None,
    cancellation_check_interval_seconds: int | float = 0.25,
    process_kill_grace_seconds: int | float = 2.0,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "video_editing_toolkit.agentctl",
        "--artifact-root",
        str(artifact_root),
    ]
    if allowed_p1_capabilities:
        command.extend(["--allowed-p1-capabilities", ",".join(allowed_p1_capabilities)])
    input_payload = json.dumps(dict(envelope), ensure_ascii=False)
    if cancellation_checker is not None or cancel_event is not None:
        return _run_subprocess_with_cancellation(
            command,
            input_payload=input_payload,
            timeout_seconds=timeout_seconds,
            cancellation_checker=cancellation_checker,
            cancel_event=cancel_event,
            cancellation_check_interval_seconds=cancellation_check_interval_seconds,
            process_kill_grace_seconds=process_kill_grace_seconds,
        )
    try:
        completed = subprocess.run(
            command,
            input=input_payload,
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

    return _decode_subprocess_stdout(completed.stdout)


def _run_subprocess_with_cancellation(
    command: list[str],
    *,
    input_payload: str,
    timeout_seconds: int | float,
    cancellation_checker: Callable[[], bool] | None,
    cancel_event: Any | None,
    cancellation_check_interval_seconds: int | float,
    process_kill_grace_seconds: int | float,
) -> dict[str, Any]:
    if _cancel_requested(cancellation_checker=cancellation_checker, cancel_event=cancel_event):
        raise WorkerLocalExecutionCancelled()
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": _subprocess_env(),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **popen_kwargs)
    except OSError as exc:
        raise WorkerLocalExecutionError(
            "worker.subprocess_unavailable",
            "Local toolkit subprocess could not be started.",
        ) from exc

    deadline = time.monotonic() + max(float(timeout_seconds), 0.1)
    interval = max(min(float(cancellation_check_interval_seconds), 1.0), 0.05)
    next_input: str | None = input_payload
    while True:
        if _cancel_requested(cancellation_checker=cancellation_checker, cancel_event=cancel_event):
            _terminate_process_tree(process, kill_grace_seconds=process_kill_grace_seconds)
            raise WorkerLocalExecutionCancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_tree(process, kill_grace_seconds=process_kill_grace_seconds)
            raise WorkerLocalExecutionTimeout()
        try:
            stdout, _stderr = process.communicate(
                input=next_input,
                timeout=min(interval, remaining),
            )
            return _decode_subprocess_stdout(stdout)
        except subprocess.TimeoutExpired:
            next_input = None


def _decode_subprocess_stdout(stdout_value: str | None) -> dict[str, Any]:
    stdout = (stdout_value or "").strip()
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


def _cancel_requested(
    *,
    cancellation_checker: Callable[[], bool] | None,
    cancel_event: Any | None,
) -> bool:
    if cancel_event is not None:
        is_set = getattr(cancel_event, "is_set", None)
        if callable(is_set) and is_set():
            return True
    if cancellation_checker is not None:
        return bool(cancellation_checker())
    return False


def _terminate_process_tree(process: subprocess.Popen[str], *, kill_grace_seconds: int | float) -> None:
    grace = max(float(kill_grace_seconds), 0.1)
    if process.poll() is not None:
        return
    if os.name == "nt":
        with suppress(Exception):
            process.terminate()
        with suppress(Exception):
            process.wait(timeout=grace)
        if process.poll() is None:
            with suppress(Exception):
                process.kill()
            with suppress(Exception):
                process.wait(timeout=grace)
        return
    with suppress(Exception):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    with suppress(Exception):
        process.wait(timeout=grace)
    if process.poll() is None:
        with suppress(Exception):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        with suppress(Exception):
            process.kill()
        with suppress(Exception):
            process.wait(timeout=grace)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src_root = Path(__file__).resolve().parents[1]
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_root) if not existing else f"{src_root}{os.pathsep}{existing}"
    return env
