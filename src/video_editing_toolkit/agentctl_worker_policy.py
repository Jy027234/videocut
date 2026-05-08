"""Execution policy checks for the external agentctl worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from video_editing_toolkit.adapters import P1_CAPABILITY_ROUTES, resolve_route
from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode


DEFAULT_ALLOWED_RESOURCE_CLASSES = ("cpu_light",)


@dataclass(frozen=True)
class WorkerExecutionPolicyConfig:
    allowed_resource_classes: tuple[str, ...] = DEFAULT_ALLOWED_RESOURCE_CLASSES
    allowed_capabilities: tuple[str, ...] = ()
    max_job_input_bytes: int = CPU_LIGHT_LIMITS.max_input_bytes
    max_run_timeout_seconds: int = CPU_LIGHT_LIMITS.timeout_seconds


@dataclass(frozen=True)
class WorkerExecutionPolicySummary:
    capability: str
    route_known: bool
    resource_class: str | None
    declared_input_bytes: int
    route_timeout_seconds: int | None


class WorkerExecutionPolicyError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        error_message: str,
        *,
        capability: str | None = None,
        resource_class: str | None = None,
    ) -> None:
        super().__init__(error_message)
        self.reason_code = reason_code
        self.error_message = error_message
        self.capability = capability
        self.resource_class = resource_class


def validate_worker_execution_policy(
    envelope: Mapping[str, Any],
    *,
    config: WorkerExecutionPolicyConfig,
) -> WorkerExecutionPolicySummary:
    """Validate a leased toolkit envelope before materialization and execution."""

    capability = _capability(envelope)
    if config.allowed_capabilities and capability not in set(config.allowed_capabilities):
        raise WorkerExecutionPolicyError(
            "worker.capability_not_allowed",
            "Capability is not enabled for this worker.",
            capability=capability,
        )

    if capability in P1_CAPABILITY_ROUTES:
        raise WorkerExecutionPolicyError(
            "worker.p1_capability_disabled",
            "P1 capability routes are disabled for this worker by default.",
            capability=capability,
        )

    try:
        route = resolve_route(capability)
    except ValueError as exc:
        raise WorkerExecutionPolicyError(
            "worker.capability_unknown",
            "Capability is not registered for this worker.",
            capability=capability,
        ) from exc

    resource_class = route.resource_limits.resource_class.value
    allowed_classes = set(config.allowed_resource_classes)
    if allowed_classes and resource_class not in allowed_classes:
        raise WorkerExecutionPolicyError(
            "worker.resource_class_not_allowed",
            "Capability resource class is not enabled for this worker.",
            capability=capability,
            resource_class=resource_class,
        )

    if route.resource_limits.timeout_seconds > config.max_run_timeout_seconds:
        raise WorkerExecutionPolicyError(
            ErrorCode.TIMEOUT_EXCEEDED.value,
            "Capability timeout exceeds this worker policy.",
            capability=capability,
            resource_class=resource_class,
        )

    declared_input_bytes = _declared_input_bytes(envelope)
    if declared_input_bytes > min(route.resource_limits.max_input_bytes, config.max_job_input_bytes):
        raise WorkerExecutionPolicyError(
            ErrorCode.INPUT_TOO_LARGE.value,
            "Declared input artifacts exceed this worker policy.",
            capability=capability,
            resource_class=resource_class,
        )

    return WorkerExecutionPolicySummary(
        capability=capability,
        route_known=True,
        resource_class=resource_class,
        declared_input_bytes=declared_input_bytes,
        route_timeout_seconds=route.resource_limits.timeout_seconds,
    )


def parse_csv_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _capability(envelope: Mapping[str, Any]) -> str:
    capability = envelope.get("capability")
    if not isinstance(capability, str) or not capability.strip():
        raise WorkerExecutionPolicyError(
            "worker.capability_required",
            "Capability is required for worker execution.",
        )
    return capability.strip()


def _declared_input_bytes(envelope: Mapping[str, Any]) -> int:
    total = 0
    for ref in _artifact_ref_mappings(envelope):
        size = _non_negative_int(ref.get("size_bytes"))
        if size is not None:
            total += size
    return total


def _artifact_ref_mappings(envelope: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    refs: list[Mapping[str, Any]] = []
    raw_refs = envelope.get("artifact_refs")
    if isinstance(raw_refs, list):
        refs.extend(ref for ref in raw_refs if isinstance(ref, Mapping))
    raw_ref = envelope.get("artifact_ref")
    if isinstance(raw_ref, Mapping):
        refs.append(raw_ref)
    raw_ids = envelope.get("artifact_ids")
    if isinstance(raw_ids, list):
        refs.extend(ref for ref in raw_ids if isinstance(ref, Mapping))

    unique: dict[str, Mapping[str, Any]] = {}
    for ref in refs:
        artifact_id = ref.get("artifact_id") or ref.get("ref")
        if isinstance(artifact_id, str) and artifact_id:
            unique.setdefault(artifact_id, ref)
    return tuple(unique.values())


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None
