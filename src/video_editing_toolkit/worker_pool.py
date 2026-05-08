"""Execution pool registry for the external worker runtime.

The P0 pool contract is deliberately conservative: local runners execute
directly, while docker/remote pools can be configured and probed but fail
safely until a production dispatcher is connected.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


IN_PROCESS_EXECUTION_MODE = "in_process"
SUBPROCESS_EXECUTION_MODE = "subprocess"
DOCKER_EXECUTION_BACKEND = "docker"
REMOTE_EXECUTION_BACKEND = "remote"
EXECUTABLE_LOCAL_BACKENDS = frozenset(
    {
        IN_PROCESS_EXECUTION_MODE,
        SUBPROCESS_EXECUTION_MODE,
    }
)
MANAGED_EXECUTION_BACKENDS = frozenset(
    {
        DOCKER_EXECUTION_BACKEND,
        REMOTE_EXECUTION_BACKEND,
    }
)
SUPPORTED_EXECUTION_BACKENDS = frozenset(EXECUTABLE_LOCAL_BACKENDS | MANAGED_EXECUTION_BACKENDS)
WORKER_POOL_CONTRACT = "p0_execution_pool_config_probe_safe_failure"


@dataclass(frozen=True)
class WorkerExecutionPoolConfig:
    """Caller-safe execution pool configuration."""

    backend: str
    enabled: bool = False
    endpoint: str | None = None
    image: str | None = None
    max_concurrency: int = 1
    timeout_seconds: float = 10.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def local(cls, backend: str) -> "WorkerExecutionPoolConfig":
        return cls(backend=backend, enabled=True)

    @classmethod
    def from_env(cls, backend: str) -> "WorkerExecutionPoolConfig":
        normalized = backend.upper().replace("-", "_")
        enabled = _bool_env(f"VIDEO_TOOLKIT_{normalized}_POOL_ENABLED", False)
        endpoint = os.environ.get(f"VIDEO_TOOLKIT_{normalized}_POOL_ENDPOINT")
        image = os.environ.get(f"VIDEO_TOOLKIT_{normalized}_POOL_IMAGE")
        return cls(
            backend=backend,
            enabled=enabled,
            endpoint=endpoint,
            image=image,
            max_concurrency=_int_env(f"VIDEO_TOOLKIT_{normalized}_POOL_MAX_CONCURRENCY", 1),
            timeout_seconds=_float_env(f"VIDEO_TOOLKIT_{normalized}_POOL_TIMEOUT_SECONDS", 10.0),
        )

    @property
    def configured(self) -> bool:
        if self.backend in EXECUTABLE_LOCAL_BACKENDS:
            return True
        if self.backend == REMOTE_EXECUTION_BACKEND:
            return self.enabled and bool(self.endpoint)
        return self.enabled

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "contract": WORKER_POOL_CONTRACT,
            "backend": self.backend,
            "enabled": self.enabled,
            "configured": self.configured,
            "endpoint_configured": bool(self.endpoint),
            "image_configured": bool(self.image),
            "max_concurrency": max(int(self.max_concurrency), 1),
            "timeout_seconds": max(float(self.timeout_seconds), 0.1),
        }


@dataclass(frozen=True)
class WorkerExecutionPoolProbeResult:
    """Caller-safe health probe result for a worker execution pool."""

    backend: str
    configured: bool
    available: bool
    execution_supported: bool
    status: str
    reason_code: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract": WORKER_POOL_CONTRACT,
            "backend": self.backend,
            "configured": self.configured,
            "available": self.available,
            "execution_supported": self.execution_supported,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
        }
        if self.metadata:
            payload["metadata"] = _public_metadata(self.metadata)
        return payload


class WorkerExecutionPoolRegistry:
    """Registry and probe facade for local, docker, and remote worker pools."""

    def __init__(self, configs: Mapping[str, WorkerExecutionPoolConfig] | None = None) -> None:
        defaults = {
            IN_PROCESS_EXECUTION_MODE: WorkerExecutionPoolConfig.local(IN_PROCESS_EXECUTION_MODE),
            SUBPROCESS_EXECUTION_MODE: WorkerExecutionPoolConfig.local(SUBPROCESS_EXECUTION_MODE),
            DOCKER_EXECUTION_BACKEND: WorkerExecutionPoolConfig.from_env(DOCKER_EXECUTION_BACKEND),
            REMOTE_EXECUTION_BACKEND: WorkerExecutionPoolConfig.from_env(REMOTE_EXECUTION_BACKEND),
        }
        if configs:
            defaults.update(dict(configs))
        self._configs = defaults

    @classmethod
    def from_env(cls) -> "WorkerExecutionPoolRegistry":
        return cls()

    def config_for(self, backend: str) -> WorkerExecutionPoolConfig | None:
        return self._configs.get(backend)

    def probe(self, backend: str) -> WorkerExecutionPoolProbeResult:
        config = self.config_for(backend)
        if config is None:
            return WorkerExecutionPoolProbeResult(
                backend=backend,
                configured=False,
                available=False,
                execution_supported=False,
                status="unknown",
                reason_code="worker.execution_pool_unknown",
                message="Execution pool is not registered.",
            )
        if backend in EXECUTABLE_LOCAL_BACKENDS:
            return WorkerExecutionPoolProbeResult(
                backend=backend,
                configured=True,
                available=True,
                execution_supported=True,
                status="ready",
                reason_code="worker.execution_pool_ready",
                message="Local execution pool is ready.",
                metadata=config.to_public_dict(),
            )
        if not config.enabled:
            return WorkerExecutionPoolProbeResult(
                backend=backend,
                configured=False,
                available=False,
                execution_supported=False,
                status="disabled",
                reason_code="worker.execution_backend_unavailable",
                message="Managed execution pool is disabled.",
                metadata=config.to_public_dict(),
            )
        if backend == REMOTE_EXECUTION_BACKEND and not config.endpoint:
            return WorkerExecutionPoolProbeResult(
                backend=backend,
                configured=False,
                available=False,
                execution_supported=False,
                status="not_configured",
                reason_code="worker.execution_backend_unavailable",
                message="Remote execution pool is enabled but has no endpoint configured.",
                metadata=config.to_public_dict(),
            )
        if backend == DOCKER_EXECUTION_BACKEND and shutil.which("docker") is None:
            return WorkerExecutionPoolProbeResult(
                backend=backend,
                configured=True,
                available=False,
                execution_supported=False,
                status="probe_failed",
                reason_code="worker.execution_pool_probe_failed",
                message="Docker execution pool is configured but its local probe failed.",
                metadata=config.to_public_dict(),
            )
        return WorkerExecutionPoolProbeResult(
            backend=backend,
            configured=True,
            available=True,
            execution_supported=False,
            status="configured",
            reason_code="worker.execution_pool_dispatcher_required",
            message="Managed execution pool is configured; production dispatcher execution is not wired in this build.",
            metadata=config.to_public_dict(),
        )

    def probe_all(self) -> dict[str, Any]:
        return {
            "contract": WORKER_POOL_CONTRACT,
            "pools": [
                self.probe(backend).to_public_dict()
                for backend in (
                    IN_PROCESS_EXECUTION_MODE,
                    SUBPROCESS_EXECUTION_MODE,
                    DOCKER_EXECUTION_BACKEND,
                    REMOTE_EXECUTION_BACKEND,
                )
            ],
        }


def _public_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        key_string = str(key)
        normalized = key_string.lower()
        if normalized.endswith("_configured") and isinstance(value, bool):
            safe[key_string] = value
            continue
        if any(part in normalized for part in ("token", "secret", "password", "key", "endpoint", "url", "path", "image")):
            safe[f"{key_string}_configured"] = bool(value)
            continue
        if isinstance(value, Mapping):
            safe[key_string] = _public_metadata(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_string] = value
        else:
            safe[key_string] = str(type(value).__name__)
    return safe


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
