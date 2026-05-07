"""Local runtime request and response contracts.

These models mirror the future agentctl call shape while staying dependency-free
for the P0 local runtime skeleton.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from video_editing_toolkit.storage.artifacts import ArtifactRef


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class PolicyContext:
    tenant_id: str = "demo_tenant"
    user_id: str = "demo_user"
    share_id: str | None = None
    data_policy: dict[str, Any] = field(default_factory=dict)
    quota_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunRequest:
    toolkit_id: str
    capability: str
    input: dict[str, Any]
    version: str = "0.1.0"
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex}")
    tool_call_id: str = field(default_factory=lambda: f"tool_call_{uuid4().hex}")
    artifact_refs: list[ArtifactRef] = field(default_factory=list)
    policy_context: PolicyContext = field(default_factory=PolicyContext)
    dry_run: bool = False
    trace_ref: str | None = None


@dataclass(slots=True)
class RunResponse:
    run_id: str
    tool_call_id: str
    status: RunStatus
    output: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = field(default_factory=list)
    usage_metrics: dict[str, Any] = field(default_factory=dict)
    trace_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Return a caller-safe response payload."""

        return {
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "status": self.status.value,
            "output": _to_public_value(self.output),
            "artifact_refs": [
                artifact_ref.to_public_dict()
                for artifact_ref in self.artifact_refs
            ],
            "usage_metrics": _to_public_value(self.usage_metrics),
            "trace_ref": self.trace_ref,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


def _to_public_value(value: Any) -> Any:
    if isinstance(value, ArtifactRef):
        return value.to_public_dict()
    if isinstance(value, RunStatus):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {
            key: _to_public_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_to_public_value(child) for child in value]
    if isinstance(value, tuple):
        return [_to_public_value(child) for child in value]
    return value


@dataclass(slots=True)
class RunRecord:
    request: RunRequest
    response: RunResponse
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    cancelled_at: datetime | None = None

    def update_status(
        self,
        status: RunStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.response.status = status
        self.response.error_code = error_code
        self.response.error_message = error_message
        self.updated_at = utc_now()


RunHandlerResult = dict[str, Any] | RunResponse
RunHandler = Any
