"""Stable error codes for adapter and resource guard boundaries."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Machine-readable errors returned by adapter calls."""

    ADAPTER_NOT_IMPLEMENTED = "adapter.not_implemented"
    ADAPTER_UNAVAILABLE = "adapter.unavailable"
    CAPABILITY_UNSUPPORTED = "capability.unsupported"
    INVALID_REQUEST = "request.invalid"
    ARTIFACT_REF_INVALID = "artifact_ref.invalid"
    ARTIFACT_ACCESS_DENIED = "artifact_ref.access_denied"
    RESOURCE_LIMIT_EXCEEDED = "resource.limit_exceeded"
    TIMEOUT_EXCEEDED = "resource.timeout_exceeded"
    INPUT_TOO_LARGE = "resource.input_too_large"
    OUTPUT_TOO_LARGE = "resource.output_too_large"
    MEDIA_DURATION_TOO_LONG = "resource.media_duration_too_long"
    CONCURRENCY_LIMIT_EXCEEDED = "resource.concurrency_limit_exceeded"
    INTERNAL_ERROR = "internal.error"
