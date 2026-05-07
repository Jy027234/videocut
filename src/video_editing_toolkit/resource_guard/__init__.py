"""Resource guard primitives for video-editing-toolkit adapters."""

from .errors import ErrorCode
from .limits import (
    CPU_HEAVY_LIMITS,
    CPU_LIGHT_LIMITS,
    GPU_OPTIONAL_LIMITS,
    LimitViolation,
    ResourceClass,
    ResourceLimits,
    validate_declared_usage,
)

__all__ = [
    "CPU_HEAVY_LIMITS",
    "CPU_LIGHT_LIMITS",
    "GPU_OPTIONAL_LIMITS",
    "ErrorCode",
    "LimitViolation",
    "ResourceClass",
    "ResourceLimits",
    "validate_declared_usage",
]
