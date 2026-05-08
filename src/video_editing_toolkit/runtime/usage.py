"""Billing-ready local usage summaries without real billing side effects."""

from __future__ import annotations

from typing import Any

from video_editing_toolkit.runtime.models import RunRequest, RunResponse, RunStatus
from video_editing_toolkit.storage.artifacts import ArtifactRef


USAGE_SUMMARY_SCHEMA = "video_editing_toolkit.runtime.usage_summary.v0"
BILLING_MODE = "local_preview_no_charge"


def build_usage_summary(
    *,
    request: RunRequest,
    response: RunResponse,
    runtime_ms: float,
    attempt: int,
) -> dict[str, Any]:
    """Aggregate runtime, bytes, artifacts, capability, and resource usage."""

    usage_metrics = dict(response.usage_metrics)
    resource_class = _string_or_default(usage_metrics.get("resource_class"), "unclassified")
    input_bytes = _bytes_from_refs(request.artifact_refs)
    output_bytes = _bytes_from_refs(response.artifact_refs)
    input_bytes = _non_negative_int(
        usage_metrics.get("input_bytes"),
        default=input_bytes,
    )
    output_bytes = _non_negative_int(
        usage_metrics.get("output_bytes"),
        default=output_bytes,
    )

    base_counters = {
        "runs": 1,
        "attempts": attempt,
        "runtime_ms": runtime_ms,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "input_artifact_count": len(request.artifact_refs),
        "output_artifact_count": len(response.artifact_refs),
    }
    return {
        "schema": USAGE_SUMMARY_SCHEMA,
        "billing_ready": True,
        "billing_mode": BILLING_MODE,
        "charged": False,
        "tenant_id": request.policy_context.tenant_id,
        "user_id": request.policy_context.user_id,
        "capability": request.capability,
        "resource_class": resource_class,
        "status": response.status.value if isinstance(response.status, RunStatus) else str(response.status),
        "runtime_ms": runtime_ms,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "artifact_counts": {
            "input": len(request.artifact_refs),
            "output": len(response.artifact_refs),
            "total": len(request.artifact_refs) + len(response.artifact_refs),
        },
        "attempts": attempt,
        "capability_usage": {
            request.capability: dict(base_counters),
        },
        "resource_usage": {
            resource_class: dict(base_counters),
        },
    }


def _bytes_from_refs(refs: list[ArtifactRef]) -> int:
    return sum(
        ref.size_bytes
        for ref in refs
        if isinstance(ref.size_bytes, int) and ref.size_bytes >= 0
    )


def _non_negative_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    return default


def _string_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default
