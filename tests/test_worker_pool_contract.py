"""P0 execution pool registry contract tests."""

from __future__ import annotations

import json

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.worker_pool import (
    DOCKER_EXECUTION_BACKEND,
    IN_PROCESS_EXECUTION_MODE,
    REMOTE_EXECUTION_BACKEND,
    WORKER_POOL_CONTRACT,
    WorkerExecutionPoolConfig,
    WorkerExecutionPoolRegistry,
)


def test_default_pool_registry_exposes_caller_safe_health() -> None:
    registry = WorkerExecutionPoolRegistry(
        {
            DOCKER_EXECUTION_BACKEND: WorkerExecutionPoolConfig(
                backend=DOCKER_EXECUTION_BACKEND,
                enabled=False,
                endpoint="https://docker-control.internal/private",
                image="registry.internal/video-toolkit/private:latest",
            ),
        }
    )

    health = registry.probe_all()
    rendered = json.dumps(health, sort_keys=True)

    assert health["contract"] == WORKER_POOL_CONTRACT
    assert health["pools"][0]["backend"] == IN_PROCESS_EXECUTION_MODE
    assert health["pools"][0]["available"] is True
    assert health["pools"][0]["execution_supported"] is True
    docker = next(pool for pool in health["pools"] if pool["backend"] == DOCKER_EXECUTION_BACKEND)
    assert docker["available"] is False
    assert docker["reason_code"] == "worker.execution_backend_unavailable"
    assert "docker-control.internal" not in rendered
    assert "registry.internal" not in rendered
    assert_no_public_path_or_command_leak(health)


def test_remote_pool_probe_is_configurable_but_not_executable_in_p0() -> None:
    registry = WorkerExecutionPoolRegistry(
        {
            REMOTE_EXECUTION_BACKEND: WorkerExecutionPoolConfig(
                backend=REMOTE_EXECUTION_BACKEND,
                enabled=True,
                endpoint="https://remote-worker.internal/dispatch?token=secret",
                max_concurrency=3,
            ),
        }
    )

    probe = registry.probe(REMOTE_EXECUTION_BACKEND).to_public_dict()
    rendered = json.dumps(probe, sort_keys=True)

    assert probe["configured"] is True
    assert probe["available"] is True
    assert probe["execution_supported"] is False
    assert probe["reason_code"] == "worker.execution_pool_dispatcher_required"
    assert probe["metadata"]["endpoint_configured"] is True
    assert probe["metadata"]["max_concurrency"] == 3
    assert "remote-worker.internal" not in rendered
    assert "secret" not in rendered
    assert_no_public_path_or_command_leak(probe)
