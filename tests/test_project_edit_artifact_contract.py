"""P0.8 project-edit timeline and render-config artifact contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from video_editing_toolkit.runtime import (
    LocalRunService,
    RunRequest,
    RunResponse,
    RunStatus,
    register_p0_adapter_handlers,
)
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from conftest import SCHEMAS_DIR, assert_no_public_path_or_command_leak, load_json


jsonschema = pytest.importorskip("jsonschema")

ARTIFACT_MANIFEST_SCHEMA_PATH = SCHEMAS_DIR / "artifact-manifests.schema.json"


def test_project_edit_timeline_and_render_config_artifacts_validate_with_local_runtime(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    validator = _artifact_manifest_validator()
    project_id = f"proj_p08_{uuid4().hex}"

    create_response = _run(
        service,
        "video.project_edit.create_project",
        {"project_id": project_id},
    )
    assert create_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(create_response.to_public_dict())

    patch_response = _run(
        service,
        "video.project_edit.apply_timeline_patch",
        {
            "project_id": project_id,
            "base_version_id": create_response.output["version_id"],
            "timeline_patch": {
                "operations": [
                    {
                        "op": "add_clip",
                        "track_id": "v1",
                        "clip_id": "clip_p08_0001",
                        "asset_ref": {
                            "artifact_id": "artifact_input_0001",
                            "artifact_type": "normalized_video",
                        },
                        "timeline_start_seconds": 0.0,
                        "source_in_seconds": 0.0,
                        "source_out_seconds": 6.25,
                    }
                ]
            },
            "change_reason": "P0.8 project artifact contract.",
            "requested_preview": True,
            "preview_profile": "review",
            "max_duration_seconds": 6.25,
        },
    )
    assert patch_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(patch_response.to_public_dict())

    timeline_ref = _single_artifact_ref(patch_response, "timeline_json")
    render_config_ref = _single_artifact_ref(patch_response, "render_config_json")
    assert patch_response.output["timeline_artifact_ref"]["artifact_id"] == timeline_ref.artifact_id
    assert patch_response.output["render_config_artifact_ref"]["artifact_id"] == render_config_ref.artifact_id

    timeline_payload, timeline_path = _artifact_json_payload(service, timeline_ref)
    assert timeline_path.name == "timeline.json"
    validator.validate(timeline_payload)
    assert_no_public_path_or_command_leak(timeline_payload)
    assert timeline_payload["project_id"] == project_id
    assert timeline_payload["version_id"] == patch_response.output["new_version_id"]
    assert timeline_payload["timeline_summary"]["duration_seconds"] == 6.25
    assert timeline_payload["timeline"]["tracks"]["v1"]["clips"][0]["clip_id"] == "clip_p08_0001"

    patch_render_payload, patch_render_path = _artifact_json_payload(service, render_config_ref)
    assert patch_render_path.name == "render_config.json"
    validator.validate(patch_render_payload)
    assert_no_public_path_or_command_leak(patch_render_payload)
    assert patch_render_payload["source_timeline_artifact_ref"]["artifact_id"] == timeline_ref.artifact_id
    assert patch_render_payload["render_config"]["mode"] == "preview"
    assert patch_render_payload["render_config"]["max_duration_seconds"] == 6.25

    preview_response = _run(
        service,
        "video.project_edit.render_preview",
        {
            "project_id": project_id,
            "version_id": patch_response.output["new_version_id"],
            "preview_profile": "approval",
            "resolution": "480p",
            "include_audio": False,
        },
    )
    assert preview_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(preview_response.to_public_dict())

    preview_render_config_ref = _single_artifact_ref(preview_response, "render_config_json")
    assert (
        preview_response.output["render_config_artifact_ref"]["artifact_id"]
        == preview_render_config_ref.artifact_id
    )
    preview_render_payload, preview_render_path = _artifact_json_payload(
        service,
        preview_render_config_ref,
    )
    assert preview_render_path.name == "render_config.json"
    validator.validate(preview_render_payload)
    assert_no_public_path_or_command_leak(preview_render_payload)
    assert preview_render_payload["source_timeline_artifact_ref"] is None
    assert preview_render_payload["render_config"]["profile"] == "approval"
    assert preview_render_payload["render_config"]["resolution"] == "480p"
    assert preview_render_payload["render_config"]["include_audio"] is False


def _artifact_manifest_validator() -> Any:
    schema = load_json(ARTIFACT_MANIFEST_SCHEMA_PATH)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def _service(tmp_path: Path) -> LocalRunService:
    service = LocalRunService(
        artifact_store=LocalArtifactStore(
            tmp_path / "artifacts",
            public_base_path="https://artifacts.local/download",
        )
    )
    register_p0_adapter_handlers(service)
    return service


def _run(
    service: LocalRunService,
    capability: str,
    input_payload: dict[str, Any],
) -> RunResponse:
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability=capability,
        input=input_payload,
    )
    service.submit(request)
    response = service.process_next()
    assert response is not None
    return response


def _artifact_json_payload(
    service: LocalRunService,
    artifact_ref: ArtifactRef,
) -> tuple[dict[str, Any], Path]:
    artifact_path = service.artifact_store.open_local_path(artifact_ref.artifact_id)
    assert artifact_path is not None
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    return payload, artifact_path


def _single_artifact_ref(response: RunResponse, artifact_type: str) -> ArtifactRef:
    refs = [ref for ref in response.artifact_refs if ref.artifact_type == artifact_type]
    assert len(refs) == 1
    return refs[0]
