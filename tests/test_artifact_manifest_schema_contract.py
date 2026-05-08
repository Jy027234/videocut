"""P0.6 schema contracts for generated artifact manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def test_asset_index_artifact_file_validates_against_manifest_schema(tmp_path) -> None:
    service = _service(tmp_path)
    media_ref = _put_dummy_media(service, filename="schema-asset-video.mp4")
    audio_ref = _put_dummy_audio(service)
    validator = _artifact_manifest_validator()

    response = _run(
        service,
        "video.asset_ingest.build_asset_index",
        {
            "project_id": "proj_p06_asset_index_schema",
            "artifact_refs": [
                {"artifact_id": media_ref.artifact_id},
                {"artifact_id": audio_ref.artifact_id},
            ],
        },
        artifact_refs=[media_ref, audio_ref],
    )

    assert response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(response.to_public_dict())
    artifact_ref = _single_artifact_ref(response, "asset_index")
    payload = _artifact_json_payload(service, artifact_ref)

    validator.validate(payload)
    assert payload["asset_count"] == len(payload["assets"]) == 2
    assert {asset["artifact_ref"]["artifact_id"] for asset in payload["assets"]} == {
        media_ref.artifact_id,
        audio_ref.artifact_id,
    }


def test_delivery_and_package_artifact_files_validate_against_manifest_schema(tmp_path) -> None:
    service = _service(tmp_path)
    render_ref = _put_dummy_media(
        service,
        filename="schema-render-final.mp4",
        artifact_type="final_render",
    )
    index_ref = _put_dummy_json(
        service,
        filename="schema-asset-index.json",
        artifact_type="asset_index",
        payload={"assets": [{"artifact_id": render_ref.artifact_id, "role": "final_render"}]},
    )
    validator = _artifact_manifest_validator()
    variants = [
        {
            "name": "Web 1080p",
            "delivery_target": "web",
            "format": "mp4",
            "resolution": "1080p",
            "codec": "h264",
            "audio_codec": "aac",
            "bitrate": "5M",
        }
    ]

    delivery_response = _run(
        service,
        "video.delivery.create_delivery_manifest",
        {
            "project_id": "proj_p06_delivery_schema",
            "version": "ver_0006",
            "artifact_refs": [
                {"artifact_id": index_ref.artifact_id},
                {"artifact_id": render_ref.artifact_id},
            ],
            "variants": variants,
        },
        artifact_refs=[index_ref, render_ref],
    )

    assert delivery_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(delivery_response.to_public_dict())
    delivery_payload = _artifact_json_payload(
        service,
        _single_artifact_ref(delivery_response, "delivery_manifest"),
    )
    validator.validate(delivery_payload)
    assert delivery_payload["variant_count"] == len(delivery_payload["variants"]) == 1
    assert [ref["artifact_id"] for ref in delivery_payload["input_artifact_refs"]] == [
        index_ref.artifact_id,
        render_ref.artifact_id,
    ]

    delivery_ref = _single_artifact_ref(delivery_response, "delivery_manifest")
    package_response = _run(
        service,
        "video.delivery.package_artifacts",
        {
            "project_id": "proj_p06_delivery_schema",
            "project_version": "ver_0006",
            "artifact_refs": [
                {"artifact_id": delivery_ref.artifact_id},
                {"artifact_id": render_ref.artifact_id},
            ],
            "variants": variants,
        },
        artifact_refs=[delivery_ref, render_ref],
    )

    assert package_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(package_response.to_public_dict())
    package_payload = _artifact_json_payload(
        service,
        _single_artifact_ref(package_response, "package_manifest"),
    )
    validator.validate(package_payload)
    assert package_payload["variant_count"] == len(package_payload["variants"]) == 1
    assert [ref["artifact_id"] for ref in package_payload["input_artifact_refs"]] == [
        delivery_ref.artifact_id,
        render_ref.artifact_id,
    ]


def test_p1_artifact_manifest_shapes_validate_against_manifest_schema() -> None:
    validator = _artifact_manifest_validator()
    script_ref = _public_ref("art_script_0001", "voiceover_script", "text/plain")
    audio_ref = _public_ref("art_voiceover_0001", "voiceover_audio", "audio/wav")
    media_ref = _public_ref("art_media_0001", "normalized_video", "video/mp4")
    template_ref = _public_ref("art_template_0001", "remotion_template", "application/zip")
    props_ref = _public_ref("art_props_0001", "remotion_props", "application/json")

    payloads = [
        {
            "schema": "video_editing_toolkit.voiceover.v1",
            "project_id": "proj_p11_voiceover",
            "run_id": "run_p11_voiceover",
            "script_artifact_ref": script_ref,
            "audio_artifact_ref": audio_ref,
            "voice_profile": {
                "type": "system_voice",
                "voice_id": "system-neutral-001",
                "locale": "zh-CN",
            },
            "duration_seconds": 4.2,
            "safety": {
                "voice_cloning_used": False,
                "model_downloaded": False,
            },
        },
        {
            "schema": "video_editing_toolkit.qc_report.v1",
            "project_id": "proj_p11_qc",
            "run_id": "run_p11_qc",
            "input_artifact_ref": media_ref,
            "overall_status": "warn",
            "checks": [
                {
                    "check": "visual_quality",
                    "status": "warn",
                    "issue_count": 1,
                    "summary": "Low light detected in one segment.",
                }
            ],
            "warnings": ["Generated by P1.1 contract fixture."],
        },
        {
            "schema": "video_editing_toolkit.remotion_template_validation.v1",
            "project_id": "proj_p11_template",
            "run_id": "run_p11_template_validate",
            "template_artifact_ref": template_ref,
            "component_name": "PromoFlash",
            "valid": True,
            "diagnostics": [
                {
                    "level": "info",
                    "message": "Template metadata parsed without executing Chromium.",
                    "code": "TEMPLATE_METADATA_OK",
                }
            ],
            "runtime": {
                "chromium_ran": False,
                "model_downloaded": False,
            },
        },
        {
            "schema": "video_editing_toolkit.remotion_render_job.v1",
            "project_id": "proj_p11_template",
            "run_id": "run_p11_render_job",
            "job_id": "remotion_job_0001",
            "status": "created",
            "template_artifact_ref": template_ref,
            "props_artifact_ref": props_ref,
            "render_settings": {
                "container": "mp4",
                "resolution": "1080p",
                "fps": 30,
                "duration_seconds": 5,
                "codec": "h264",
                "audio_codec": "aac",
            },
            "runtime": {
                "chromium_ran": False,
                "model_downloaded": False,
            },
        },
    ]

    for payload in payloads:
        assert_no_public_path_or_command_leak(payload)
        validator.validate(payload)


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
    *,
    artifact_refs: list[ArtifactRef] | None = None,
) -> RunResponse:
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability=capability,
        input=input_payload,
        artifact_refs=artifact_refs or [],
    )
    service.submit(request)
    response = service.process_next()
    assert response is not None
    return response


def _artifact_json_payload(service: LocalRunService, artifact_ref: ArtifactRef) -> dict[str, Any]:
    artifact_path = service.artifact_store.open_local_path(artifact_ref.artifact_id)
    assert artifact_path is not None
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert_no_public_path_or_command_leak(payload)
    return payload


def _single_artifact_ref(response: RunResponse, artifact_type: str) -> ArtifactRef:
    refs = [ref for ref in response.artifact_refs if ref.artifact_type == artifact_type]
    assert len(refs) == 1
    return refs[0]


def _put_dummy_media(
    service: LocalRunService,
    *,
    filename: str,
    artifact_type: str = "normalized_video",
) -> ArtifactRef:
    return service.artifact_store.put_bytes(
        content=b"dummy video artifact bytes",
        artifact_type=artifact_type,
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename=filename,
        mime_type="video/mp4",
    )


def _put_dummy_audio(service: LocalRunService) -> ArtifactRef:
    return service.artifact_store.put_bytes(
        content=b"dummy audio artifact bytes",
        artifact_type="extracted_audio",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename="schema-audio.wav",
        mime_type="audio/wav",
    )


def _put_dummy_json(
    service: LocalRunService,
    *,
    filename: str,
    artifact_type: str,
    payload: dict[str, Any],
) -> ArtifactRef:
    return service.artifact_store.put_bytes(
        content=json.dumps(payload, sort_keys=True).encode("utf-8"),
        artifact_type=artifact_type,
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename=filename,
        mime_type="application/json",
    )


def _public_ref(artifact_id: str, artifact_type: str, mime_type: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "mime_type": mime_type,
        "size_bytes": 128,
        "checksum": "sha256:" + "a" * 64,
        "data_class": "medium",
        "retention_policy": "short",
    }
