"""Structured project-edit adapter."""

from __future__ import annotations

from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS
from video_editing_toolkit.project_edit import (
    ProjectEditError,
    apply_timeline_patch,
    compare_versions,
    create_project,
    generate_edit_plan,
    inspect_assets,
    render_preview,
    rollback_version,
)
from video_editing_toolkit.project_edit.artifacts import (
    RENDER_CONFIG_ARTIFACT_TYPE,
    TIMELINE_ARTIFACT_TYPE,
    json_bytes,
    render_config_artifact_payload,
    timeline_artifact_payload,
)
from video_editing_toolkit.project_edit.core import summarize_timeline
from video_editing_toolkit.project_edit.models import get_default_store
from video_editing_toolkit.resource_guard import ErrorCode
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


APPLY_TIMELINE_PATCH = "video.project_edit.apply_timeline_patch"
RENDER_PREVIEW = "video.project_edit.render_preview"


class ProjectEditAdapter(BaseAdapter):
    adapter_name = "project_edit"
    supported_capabilities = frozenset(
        {
            "video.project_edit.create_project",
            "video.project_edit.inspect_assets",
            "video.project_edit.generate_edit_plan",
            "video.project_edit.apply_timeline_patch",
            "video.project_edit.render_preview",
            "video.project_edit.compare_versions",
            "video.project_edit.rollback_version",
        }
    )
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        handlers = {
            "video.project_edit.create_project": create_project,
            "video.project_edit.inspect_assets": inspect_assets,
            "video.project_edit.generate_edit_plan": generate_edit_plan,
            APPLY_TIMELINE_PATCH: apply_timeline_patch,
            RENDER_PREVIEW: render_preview,
            "video.project_edit.compare_versions": compare_versions,
            "video.project_edit.rollback_version": rollback_version,
        }
        if request.context.capability in {APPLY_TIMELINE_PATCH, RENDER_PREVIEW}:
            artifact_store = self._artifact_store(request)
            if artifact_store is None:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message=(
                        f"{request.context.capability} requires a configured artifact store."
                    ),
                )
        else:
            artifact_store = None

        try:
            output = handlers[request.context.capability](request.input)
        except ProjectEditError as exc:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                output={"stable_error_code": exc.stable_code},
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=str(exc),
            )

        artifact_refs: tuple[ArtifactRef, ...] = ()
        if request.context.capability == APPLY_TIMELINE_PATCH:
            output, artifact_refs = self._materialize_patch_artifacts(
                request,
                dict(output),
                artifact_store,
            )
        elif request.context.capability == RENDER_PREVIEW:
            output, artifact_refs = self._materialize_render_preview_artifact(
                request,
                dict(output),
                artifact_store,
            )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output=output,
            artifact_refs=artifact_refs,
            usage_metrics=_usage_metrics(request.context.capability, artifact_refs),
        )

    def _materialize_patch_artifacts(
        self,
        request: AdapterRequest,
        output: dict[str, Any],
        artifact_store: LocalArtifactStore | None,
    ) -> tuple[dict[str, Any], tuple[ArtifactRef, ...]]:
        if artifact_store is None:
            return output, ()

        project_id = str(output["project_id"])
        version_id = str(output["new_version_id"])
        version = get_default_store().get_version(project_id, version_id)
        if version is None:
            raise RuntimeError(f"Project version {project_id}/{version_id} was not stored.")

        timeline_ref = artifact_store.put_bytes(
            content=json_bytes(
                timeline_artifact_payload(
                    version=version,
                    run_id=request.context.run_id,
                )
            ),
            artifact_type=TIMELINE_ARTIFACT_TYPE,
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="timeline.json",
            mime_type="application/json",
        )

        artifact_refs: list[ArtifactRef] = [timeline_ref]
        output["timeline_artifact_ref"] = timeline_ref.to_public_dict()

        if request.input.get("requested_preview"):
            render_config_ref = self._put_render_config_artifact(
                request=request,
                artifact_store=artifact_store,
                project_id=project_id,
                version_id=version_id,
                timeline_summary=output.get("timeline_summary", {}),
                source_timeline_artifact_ref=timeline_ref.to_public_dict(),
            )
            artifact_refs.append(render_config_ref)
            output["render_config_artifact_ref"] = render_config_ref.to_public_dict()

        output["artifact_refs"] = [ref.to_public_dict() for ref in artifact_refs]
        return output, tuple(artifact_refs)

    def _materialize_render_preview_artifact(
        self,
        request: AdapterRequest,
        output: dict[str, Any],
        artifact_store: LocalArtifactStore | None,
    ) -> tuple[dict[str, Any], tuple[ArtifactRef, ...]]:
        if artifact_store is None:
            return output, ()

        project_id = str(output["project_id"])
        version_id = str(output["version_id"])
        version = get_default_store().get_version(project_id, version_id)
        timeline_summary: Mapping[str, Any]
        if version is not None:
            timeline_summary = summarize_timeline(version.timeline)
        else:
            timeline_summary = {
                "duration_seconds": 0.0,
                "video_tracks": 0,
                "audio_tracks": 0,
                "text_tracks": 0,
            }

        render_config_ref = self._put_render_config_artifact(
            request=request,
            artifact_store=artifact_store,
            project_id=project_id,
            version_id=version_id,
            timeline_summary=timeline_summary,
        )
        output["render_config_artifact_ref"] = render_config_ref.to_public_dict()
        output["artifact_refs"] = [render_config_ref.to_public_dict()]
        return output, (render_config_ref,)

    def _put_render_config_artifact(
        self,
        *,
        request: AdapterRequest,
        artifact_store: LocalArtifactStore,
        project_id: str,
        version_id: str,
        timeline_summary: Mapping[str, Any],
        source_timeline_artifact_ref: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        return artifact_store.put_bytes(
            content=json_bytes(
                render_config_artifact_payload(
                    project_id=project_id,
                    version_id=version_id,
                    run_id=request.context.run_id,
                    input_payload=request.input,
                    timeline_summary=timeline_summary,
                    source_timeline_artifact_ref=source_timeline_artifact_ref,
                )
            ),
            artifact_type=RENDER_CONFIG_ARTIFACT_TYPE,
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="render_config.json",
            mime_type="application/json",
        )

    def _artifact_store(self, request: AdapterRequest) -> LocalArtifactStore | None:
        artifact_store = request.input.get("_artifact_store")
        if isinstance(artifact_store, LocalArtifactStore):
            return artifact_store
        return None


def _usage_metrics(capability: str, artifact_refs: tuple[ArtifactRef, ...]) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "operation": capability.rsplit(".", maxsplit=1)[-1],
    }
    if artifact_refs:
        metrics["artifact_count"] = len(artifact_refs)
        metrics["output_bytes"] = sum(ref.size_bytes for ref in artifact_refs)
    return metrics
