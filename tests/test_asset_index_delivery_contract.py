"""P0.5 asset-index and delivery artifact contract checks."""

from __future__ import annotations

import json
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

from conftest import assert_no_public_path_or_command_leak


ASSET_INDEX_ARTIFACT_TYPES = {"asset_index", "asset_index_json"}
DELIVERY_MANIFEST_ARTIFACT_TYPES = {"delivery_manifest", "delivery_manifest_json"}
PACKAGE_MANIFEST_ARTIFACT_TYPES = {"package_manifest", "package_manifest_json"}


def test_build_asset_index_returns_caller_safe_asset_index_artifact(tmp_path) -> None:
    service = _service(tmp_path)
    media_ref = _put_dummy_media(service, filename="clip-for-index.mp4")
    audio_ref = _put_dummy_audio(service)

    response = _run(
        service,
        "video.asset_ingest.build_asset_index",
        {
            "project_id": "proj_p05_asset_index",
            "artifact_refs": [
                {"artifact_id": media_ref.artifact_id},
                {"artifact_id": audio_ref.artifact_id},
            ],
            "index_purpose": "project_create",
        },
        artifact_refs=[media_ref, audio_ref],
    )
    public_payload = response.to_public_dict()

    assert_no_public_path_or_command_leak(public_payload)
    _xfail_if_not_implemented(response, "AssetIndexAdapter")
    assert response.status == RunStatus.SUCCEEDED
    assert response.error_code is None

    index_ref = _single_public_ref(public_payload, ASSET_INDEX_ARTIFACT_TYPES)
    assert index_ref["mime_type"] == "application/json"
    assert index_ref["artifact_id"] not in {media_ref.artifact_id, audio_ref.artifact_id}
    assert index_ref["checksum"].startswith("sha256:")


def test_delivery_manifest_and_package_manifest_return_caller_safe_artifact_refs(tmp_path) -> None:
    service = _service(tmp_path)
    render_ref = _put_dummy_media(service, filename="render-final.mp4", artifact_type="final_render")
    index_ref = _put_dummy_json(
        service,
        filename="asset-index.json",
        artifact_type="asset_index_json",
        payload={"assets": [{"artifact_id": render_ref.artifact_id, "role": "final_render"}]},
    )

    manifest_response = _run(
        service,
        "video.delivery.create_delivery_manifest",
        {
            "project_id": "proj_p05_delivery",
            "version_id": "ver_0002",
            "artifact_refs": [
                {"artifact_id": index_ref.artifact_id},
                {"artifact_id": render_ref.artifact_id},
            ],
            "delivery_targets": [{"target": "download", "format": "mp4"}],
        },
        artifact_refs=[index_ref, render_ref],
    )
    manifest_public = manifest_response.to_public_dict()

    assert_no_public_path_or_command_leak(manifest_public)
    _xfail_if_not_implemented(manifest_response, "DeliveryAdapter create_delivery_manifest")
    assert manifest_response.status == RunStatus.SUCCEEDED
    assert manifest_response.error_code is None
    manifest_ref = _single_public_ref(manifest_public, DELIVERY_MANIFEST_ARTIFACT_TYPES)
    assert manifest_ref["mime_type"] == "application/json"

    package_response = _run(
        service,
        "video.delivery.package_artifacts",
        {
            "project_id": "proj_p05_delivery",
            "delivery_manifest_ref": {"artifact_id": manifest_ref["artifact_id"]},
            "artifact_refs": [{"artifact_id": render_ref.artifact_id}],
        },
        artifact_refs=[*manifest_response.artifact_refs, render_ref],
    )
    package_public = package_response.to_public_dict()

    assert_no_public_path_or_command_leak(package_public)
    _xfail_if_not_implemented(package_response, "DeliveryAdapter package_artifacts")
    assert package_response.status == RunStatus.SUCCEEDED
    assert package_response.error_code is None
    package_ref = _single_public_ref(package_public, PACKAGE_MANIFEST_ARTIFACT_TYPES)
    assert package_ref["mime_type"] == "application/json"


def test_local_chain_upload_asset_index_project_patch_delivery_manifest_or_graceful_xfail(tmp_path) -> None:
    service = _service(tmp_path)
    input_ref = _put_dummy_media(service, filename="chain-input.mp4")

    index_response = _run(
        service,
        "video.asset_ingest.build_asset_index",
        {
            "project_id": "proj_p05_chain",
            "artifact_refs": [{"artifact_id": input_ref.artifact_id}],
        },
        artifact_refs=[input_ref],
    )
    assert_no_public_path_or_command_leak(index_response.to_public_dict())
    _xfail_if_not_implemented(index_response, "AssetIndexAdapter chain step")
    assert index_response.status == RunStatus.SUCCEEDED
    asset_index_public_ref = _single_public_ref(
        index_response.to_public_dict(),
        ASSET_INDEX_ARTIFACT_TYPES,
    )

    create_response = _run(
        service,
        "video.project_edit.create_project",
        {"project_id": "proj_p05_chain"},
    )
    assert create_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(create_response.to_public_dict())

    patch_response = _run(
        service,
        "video.project_edit.apply_timeline_patch",
        {
            "project_id": "proj_p05_chain",
            "base_version_id": create_response.output["version_id"],
            "timeline_patch": {
                "operations": [
                    {
                        "op": "add_clip",
                        "track_id": "v1",
                        "clip_id": "clip_chain_0001",
                        "asset_ref": {
                            "artifact_id": input_ref.artifact_id,
                            "asset_index_artifact_id": asset_index_public_ref["artifact_id"],
                        },
                        "timeline_start_seconds": 0.0,
                        "source_in_seconds": 0.0,
                        "source_out_seconds": 2.0,
                    }
                ]
            },
            "change_reason": "P0.5 local contract chain.",
            "requested_preview": True,
        },
    )
    assert patch_response.status == RunStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(patch_response.to_public_dict())

    delivery_response = _run(
        service,
        "video.delivery.create_delivery_manifest",
        {
            "project_id": "proj_p05_chain",
            "version_id": patch_response.output["new_version_id"],
            "asset_index_ref": {"artifact_id": asset_index_public_ref["artifact_id"]},
            "preview_artifact_ref": patch_response.output["preview_artifact_ref"],
        },
        artifact_refs=index_response.artifact_refs,
    )
    delivery_public = delivery_response.to_public_dict()

    assert_no_public_path_or_command_leak(delivery_public)
    _xfail_if_not_implemented(delivery_response, "DeliveryAdapter chain step")
    assert delivery_response.status == RunStatus.SUCCEEDED
    _single_public_ref(delivery_public, DELIVERY_MANIFEST_ARTIFACT_TYPES)


def _service(tmp_path) -> LocalRunService:
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
        filename="clip-audio.wav",
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


def _xfail_if_not_implemented(response: RunResponse, component: str) -> None:
    if response.status == RunStatus.FAILED and response.error_code == "adapter.not_implemented":
        pytest.xfail(f"{component} is registered but not implemented yet.")


def _single_public_ref(
    public_payload: dict[str, Any],
    allowed_artifact_types: set[str],
) -> dict[str, Any]:
    refs_by_id = {
        str(ref["artifact_id"]): ref
        for ref in _public_refs(public_payload)
        if ref.get("artifact_type") in allowed_artifact_types
    }
    refs = list(refs_by_id.values())
    assert len(refs) == 1, (
        f"expected one {sorted(allowed_artifact_types)} artifact ref, got {refs!r}"
    )
    ref = refs[0]
    for key in (
        "artifact_id",
        "artifact_type",
        "mime_type",
        "size_bytes",
        "checksum",
        "data_class",
        "retention_policy",
        "expires_at",
        "access_policy",
    ):
        assert key in ref
    assert_no_public_path_or_command_leak(ref)
    return ref


def _public_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if _looks_like_public_ref(value):
            refs.append(value)
        for child in value.values():
            refs.extend(_public_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_public_refs(child))
    return refs


def _looks_like_public_ref(value: dict[str, Any]) -> bool:
    return {
        "artifact_id",
        "artifact_type",
        "mime_type",
        "checksum",
    }.issubset(value)
