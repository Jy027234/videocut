"""Base contract for video-editing worker adapters.

Adapters expose structured capability methods only. They must not expose raw
shell, raw ffmpeg command strings, worker addresses, or local filesystem paths
to callers across the toolkit boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from video_editing_toolkit.resource_guard import ErrorCode, ResourceLimits


TOOLKIT_ID = "video-editing-toolkit"
CONTRACT_VERSION = "0.1.0"


class AdapterStatus(str, Enum):
    """Lifecycle status for a structured adapter call."""

    ACCEPTED = "accepted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ArtifactRef:
    """Stable artifact handle returned across service boundaries."""

    ref: str
    kind: str
    media_type: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterContext:
    """Identity, policy, and trace envelope supplied by the runtime layer."""

    tenant_id: str
    project_id: str
    run_id: str
    tool_call_id: str
    capability: str
    version: str = CONTRACT_VERSION
    policy_context: Mapping[str, Any] = field(default_factory=dict)
    trace_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterRequest:
    """Structured request passed into worker adapters."""

    context: AdapterContext
    input: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: Sequence[ArtifactRef] = field(default_factory=tuple)
    resource_limits: ResourceLimits | None = None


@dataclass(frozen=True)
class AdapterResult:
    """Structured adapter response consumed by runtime and artifact layers."""

    status: AdapterStatus
    output: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: Sequence[ArtifactRef] = field(default_factory=tuple)
    usage_metrics: Mapping[str, Any] = field(default_factory=dict)
    trace_ref: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None

    @classmethod
    def unsupported(cls, capability: str, adapter_name: str) -> "AdapterResult":
        return cls(
            status=AdapterStatus.UNSUPPORTED,
            error_code=ErrorCode.CAPABILITY_UNSUPPORTED,
            error_message=f"{adapter_name} does not support capability {capability}.",
        )


class AdapterError(Exception):
    """Typed adapter failure with a stable external error code."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class BaseAdapter(ABC):
    """Common contract implemented by every worker adapter."""

    adapter_name: str
    supported_capabilities: frozenset[str]
    default_limits: ResourceLimits

    def supports(self, capability: str) -> bool:
        return capability in self.supported_capabilities

    def describe(self) -> Mapping[str, Any]:
        return {
            "adapter_name": self.adapter_name,
            "toolkit_id": TOOLKIT_ID,
            "contract_version": CONTRACT_VERSION,
            "supported_capabilities": sorted(self.supported_capabilities),
            "default_limits": self.default_limits.to_dict(),
        }

    def handle(self, request: AdapterRequest) -> AdapterResult:
        capability = request.context.capability
        if not self.supports(capability):
            return AdapterResult.unsupported(capability, self.adapter_name)
        return self.invoke(request)

    @abstractmethod
    def invoke(self, request: AdapterRequest) -> AdapterResult:
        """Execute a structured capability request."""


class PlaceholderAdapter(BaseAdapter):
    """P0 skeleton adapter that advertises capabilities without executing work."""

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.ADAPTER_NOT_IMPLEMENTED,
            error_message=(
                f"{self.adapter_name} capability {request.context.capability} "
                "is registered but not implemented yet."
            ),
        )
