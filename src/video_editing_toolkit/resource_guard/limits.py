"""Resource limit primitives for video worker adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ErrorCode


class ResourceClass(str, Enum):
    """Coarse execution pool requested by a capability."""

    CPU_LIGHT = "cpu_light"
    CPU_HEAVY = "cpu_heavy"
    GPU_OPTIONAL = "gpu_optional"
    GPU_REQUIRED = "gpu_required"


@dataclass(frozen=True)
class ResourceLimits:
    """Per-call guardrails consumed before worker execution."""

    resource_class: ResourceClass
    timeout_seconds: int
    max_concurrency: int
    max_input_bytes: int
    max_output_bytes: int
    max_media_duration_seconds: int | None = None
    max_memory_mb: int | None = None
    requires_gpu: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_class": self.resource_class.value,
            "timeout_seconds": self.timeout_seconds,
            "max_concurrency": self.max_concurrency,
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_media_duration_seconds": self.max_media_duration_seconds,
            "max_memory_mb": self.max_memory_mb,
            "requires_gpu": self.requires_gpu,
        }


@dataclass(frozen=True)
class LimitViolation:
    """Structured result for preflight resource checks."""

    code: ErrorCode
    message: str


def validate_declared_usage(
    limits: ResourceLimits,
    *,
    input_bytes: int | None = None,
    expected_output_bytes: int | None = None,
    media_duration_seconds: int | None = None,
) -> LimitViolation | None:
    """Validate known request sizes before an adapter starts work."""

    if input_bytes is not None and input_bytes > limits.max_input_bytes:
        return LimitViolation(ErrorCode.INPUT_TOO_LARGE, "Input artifact exceeds limit.")
    if (
        expected_output_bytes is not None
        and expected_output_bytes > limits.max_output_bytes
    ):
        return LimitViolation(ErrorCode.OUTPUT_TOO_LARGE, "Expected output exceeds limit.")
    if (
        media_duration_seconds is not None
        and limits.max_media_duration_seconds is not None
        and media_duration_seconds > limits.max_media_duration_seconds
    ):
        return LimitViolation(
            ErrorCode.MEDIA_DURATION_TOO_LONG,
            "Media duration exceeds capability limit.",
        )
    return None


CPU_LIGHT_LIMITS = ResourceLimits(
    resource_class=ResourceClass.CPU_LIGHT,
    timeout_seconds=120,
    max_concurrency=8,
    max_input_bytes=512 * 1024 * 1024,
    max_output_bytes=256 * 1024 * 1024,
    max_media_duration_seconds=30 * 60,
    max_memory_mb=1024,
)

CPU_HEAVY_LIMITS = ResourceLimits(
    resource_class=ResourceClass.CPU_HEAVY,
    timeout_seconds=900,
    max_concurrency=2,
    max_input_bytes=4 * 1024 * 1024 * 1024,
    max_output_bytes=4 * 1024 * 1024 * 1024,
    max_media_duration_seconds=2 * 60 * 60,
    max_memory_mb=4096,
)

GPU_OPTIONAL_LIMITS = ResourceLimits(
    resource_class=ResourceClass.GPU_OPTIONAL,
    timeout_seconds=1800,
    max_concurrency=1,
    max_input_bytes=2 * 1024 * 1024 * 1024,
    max_output_bytes=512 * 1024 * 1024,
    max_media_duration_seconds=2 * 60 * 60,
    max_memory_mb=8192,
)
