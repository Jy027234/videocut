"""Bridge local runtime requests into structured worker adapters."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from video_editing_toolkit.resource_guard import ErrorCode
from video_editing_toolkit.adapters import (
    AdapterContext,
    AdapterRequest,
    AdapterStatus,
    build_adapter,
    resolve_route,
)
from video_editing_toolkit.adapters import ArtifactRef as AdapterArtifactRef
from video_editing_toolkit.runtime.models import RunRequest, RunResponse, RunStatus
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore


def adapter_run_handler(
    request: RunRequest,
    artifact_store: LocalArtifactStore,
) -> RunResponse:
    """Handle a local run through the registered P0 adapter route."""

    route = resolve_route(request.capability)
    adapter = build_adapter(request.capability)
    resolved_input = _with_worker_artifact_paths(request, artifact_store, adapter.adapter_name)
    if isinstance(resolved_input, RunResponse):
        return resolved_input

    adapter_request = AdapterRequest(
        context=AdapterContext(
            tenant_id=request.policy_context.tenant_id,
            project_id=str(resolved_input.get("project_id") or "project_unset"),
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            capability=request.capability,
            version=request.version,
            policy_context=_policy_context_dict(request),
            trace_context={"trace_ref": request.trace_ref or f"local_trace:{request.run_id}"},
        ),
        input=resolved_input,
        artifact_refs=tuple(_to_adapter_artifact_ref(ref) for ref in request.artifact_refs),
        resource_limits=route.resource_limits,
    )
    result = adapter.handle(adapter_request)

    status = (
        RunStatus.SUCCEEDED
        if result.status == AdapterStatus.SUCCEEDED
        else RunStatus.FAILED
    )
    return RunResponse(
        run_id=request.run_id,
        tool_call_id=request.tool_call_id,
        status=status,
        output=dict(result.output)
        | {
            "adapter_name": adapter.adapter_name,
            "queue_topic": route.queue_topic,
            "artifact_policy": route.artifact_policy,
        },
        artifact_refs=[
            ref for ref in result.artifact_refs if isinstance(ref, ArtifactRef)
        ],
        usage_metrics=dict(result.usage_metrics)
        | {
            "resource_class": route.resource_limits.resource_class.value,
            "timeout_seconds": route.resource_limits.timeout_seconds,
        },
        trace_ref=result.trace_ref or request.trace_ref or f"local_trace:{request.run_id}",
        error_code=result.error_code.value if result.error_code else None,
        error_message=result.error_message,
    )


def register_p0_adapter_handlers(service: Any) -> None:
    """Register every P0 route in a LocalRunService-compatible object."""

    from video_editing_toolkit.adapters import CAPABILITY_ROUTES

    for capability in CAPABILITY_ROUTES:
        service.register_handler("video-editing-toolkit", capability, adapter_run_handler)


def _to_adapter_artifact_ref(ref: ArtifactRef) -> AdapterArtifactRef:
    return AdapterArtifactRef(
        ref=ref.artifact_id,
        kind=ref.artifact_type,
        media_type=ref.mime_type,
        checksum=ref.checksum,
        size_bytes=ref.size_bytes,
        metadata={
            "data_class": ref.data_class,
            "retention_policy": ref.retention_policy,
        },
    )


def _with_worker_artifact_paths(
    request: RunRequest,
    artifact_store: LocalArtifactStore,
    adapter_name: str,
) -> dict[str, Any] | RunResponse:
    """Resolve caller artifact refs into private adapter-only worker paths."""

    resolved = {
        key: value
        for key, value in request.input.items()
        if not key.startswith("_")
    }
    if adapter_name in {"asset_index", "delivery", "ffmpeg", "project_edit"}:
        resolved["_artifact_store"] = artifact_store

    requested_ids = _input_artifact_ids(request.input)
    selected_refs = _select_input_artifact_refs(request)
    if not selected_refs:
        if requested_ids:
            return _artifact_resolution_failure(
                request,
                ErrorCode.ARTIFACT_REF_INVALID,
                "Artifact ref could not be matched to the request artifact set.",
            )
        return resolved
    if requested_ids and len(selected_refs) != len(requested_ids):
        return _artifact_resolution_failure(
            request,
            ErrorCode.ARTIFACT_REF_INVALID,
            "One or more artifact refs could not be matched to the request artifact set.",
        )

    worker_paths: list[str] = []
    for selected_ref in selected_refs:
        if selected_ref.owner_tenant_id != request.policy_context.tenant_id:
            return _artifact_resolution_failure(
                request,
                ErrorCode.ARTIFACT_ACCESS_DENIED,
                "Artifact ref is not authorized for this tenant.",
            )

        worker_path = artifact_store.open_local_path(selected_ref.artifact_id)
        if worker_path is None:
            return _artifact_resolution_failure(
                request,
                ErrorCode.ARTIFACT_REF_INVALID,
                "Artifact ref could not be resolved for worker execution.",
            )
        worker_paths.append(str(worker_path))

    resolved["_worker_media_path"] = worker_paths[0]
    resolved["_worker_media_paths"] = tuple(worker_paths)
    return resolved


def _select_input_artifact_refs(request: RunRequest) -> tuple[ArtifactRef, ...]:
    if not request.artifact_refs:
        return ()

    requested_ids = _input_artifact_ids(request.input)
    if not requested_ids:
        if request.capability == "video.analysis.analyze_frames":
            return tuple(request.artifact_refs)
        if len(request.artifact_refs) == 1:
            return (request.artifact_refs[0],)
        return ()

    selected_refs: list[ArtifactRef] = []
    remaining_ids = list(requested_ids)
    for ref in request.artifact_refs:
        if ref.artifact_id in remaining_ids:
            selected_refs.append(ref)
            remaining_ids.remove(ref.artifact_id)
    return tuple(selected_refs)


def _input_artifact_ids(input_payload: dict[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    artifact_ref = input_payload.get("artifact_ref")
    if isinstance(artifact_ref, str) and artifact_ref:
        ids.append(artifact_ref)
    if isinstance(artifact_ref, dict):
        value = artifact_ref.get("artifact_id") or artifact_ref.get("ref")
        if isinstance(value, str) and value:
            ids.append(value)

    artifact_refs = input_payload.get("artifact_refs")
    if isinstance(artifact_refs, list):
        for item in artifact_refs:
            if isinstance(item, str) and item:
                ids.append(item)
            elif isinstance(item, dict):
                value = item.get("artifact_id") or item.get("ref")
                if isinstance(value, str) and value:
                    ids.append(value)

    artifact_id = input_payload.get("artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        ids.append(artifact_id)

    artifact_ids = input_payload.get("artifact_ids")
    if isinstance(artifact_ids, list):
        ids.extend(item for item in artifact_ids if isinstance(item, str) and item)

    return tuple(dict.fromkeys(ids))


def _artifact_resolution_failure(
    request: RunRequest,
    error_code: ErrorCode,
    message: str,
) -> RunResponse:
    return RunResponse(
        run_id=request.run_id,
        tool_call_id=request.tool_call_id,
        status=RunStatus.FAILED,
        output={"adapter_name": "runtime"},
        usage_metrics={},
        trace_ref=request.trace_ref or f"local_trace:{request.run_id}",
        error_code=error_code.value,
        error_message=message,
    )


def _policy_context_dict(request: RunRequest) -> dict[str, Any]:
    payload = asdict(request.policy_context)
    payload["artifact_store_public_base_path"] = artifact_store_hint()
    return payload


def artifact_store_hint() -> str:
    """Return a non-sensitive marker for traces and local debugging."""

    return "artifact_ref_only"
