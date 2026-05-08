"""P0 checks that caller-facing artifact refs do not expose local storage."""

from __future__ import annotations

from video_editing_toolkit.runtime import RunResponse, RunStatus
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore
from video_editing_toolkit.storage.signed_urls import extract_signed_artifact_token, verify_signed_artifact_token

from conftest import FIXTURES_DIR, assert_no_public_path_or_command_leak, load_json, require_json_files


REQUIRED_ARTIFACT_REF_FIELDS = {
    "artifact_id",
    "artifact_type",
    "mime_type",
    "size_bytes",
    "checksum",
    "data_class",
    "retention_policy",
    "expires_at",
    "access_policy",
}

ALLOWED_CALLER_ARTIFACT_KEYS = REQUIRED_ARTIFACT_REF_FIELDS | {
    "download_url",
    "evidence_ref",
}


def test_caller_facing_artifact_refs_hide_storage_details() -> None:
    fixture_paths = require_json_files(
        FIXTURES_DIR / "artifact_refs",
        "No artifact_ref fixtures exist yet; add public-output fixtures before release.",
    )

    for path in fixture_paths:
        payload = load_json(path)
        assert_no_public_path_or_command_leak(payload)
        for artifact_ref in _artifact_refs(payload):
            missing = REQUIRED_ARTIFACT_REF_FIELDS - set(artifact_ref)
            assert not missing, f"{path} artifact_ref missing fields: {sorted(missing)}"
            unexpected = set(artifact_ref) - ALLOWED_CALLER_ARTIFACT_KEYS
            assert not unexpected, f"{path} exposes non-caller artifact_ref keys: {sorted(unexpected)}"


def test_artifact_ref_public_projection_hides_storage_uri_and_local_paths(tmp_path) -> None:
    store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
    )
    internal_ref = store.put_bytes(
        content=b"preview bytes",
        artifact_type="preview_video",
        owner_tenant_id="tenant_demo",
        created_by_run_id="run_demo",
        filename="preview.mp4",
        mime_type="video/mp4",
    )

    assert internal_ref.storage_uri.startswith("local-artifact://")
    public_ref = _public_artifact_ref(internal_ref)

    assert "storage_uri" not in public_ref
    assert "local_path" not in public_ref
    assert_no_public_path_or_command_leak(public_ref)


def test_local_artifact_store_can_issue_signed_download_url_without_storage_details(tmp_path) -> None:
    store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
        signing_secret="local-signing-secret",
        signed_url_ttl_seconds=600,
    )
    internal_ref = store.put_bytes(
        content=b"signed preview bytes",
        artifact_type="preview_video",
        owner_tenant_id="tenant_demo",
        created_by_run_id="run_demo",
        filename="preview.mp4",
        mime_type="video/mp4",
    )

    public_ref = internal_ref.to_public_dict()
    download_url = str(public_ref["download_url"])
    signed_token = extract_signed_artifact_token(download_url)

    assert signed_token is not None
    access = verify_signed_artifact_token(
        signed_token,
        secret="local-signing-secret",
        artifact_id=internal_ref.artifact_id,
        checksum=internal_ref.checksum,
    )
    assert access.scope == "read"
    assert "storage_uri" not in public_ref
    assert "local_path" not in public_ref
    assert "local-artifact://" not in download_url
    assert str(tmp_path) not in download_url
    assert_no_public_path_or_command_leak(public_ref)


def test_run_response_public_output_hides_internal_artifact_locations(tmp_path) -> None:
    store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
    )
    internal_ref = store.put_bytes(
        content=b"timeline bytes",
        artifact_type="timeline_json",
        owner_tenant_id="tenant_demo",
        created_by_run_id="run_demo",
        filename="timeline.json",
        mime_type="application/json",
    )
    response = RunResponse(
        run_id="run_demo",
        tool_call_id="tool_call_demo",
        status=RunStatus.SUCCEEDED,
        output={"artifact_ref": _public_artifact_ref(internal_ref)},
        artifact_refs=[internal_ref],
        trace_ref="local_trace:run_demo",
    )

    public_payload = _public_run_response_payload(response)

    assert response.artifact_refs[0].storage_uri.startswith("local-artifact://")
    assert "storage_uri" not in public_payload["artifact_refs"][0]
    assert "local_path" not in public_payload["artifact_refs"][0]
    assert_no_public_path_or_command_leak(public_payload)


def _artifact_refs(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        refs = []
        if isinstance(payload.get("artifact_refs"), list):
            refs.extend(item for item in payload["artifact_refs"] if isinstance(item, dict))
        if isinstance(payload.get("preview_artifact_ref"), dict):
            refs.append(payload["preview_artifact_ref"])
        if isinstance(payload.get("artifact_ref"), dict):
            refs.append(payload["artifact_ref"])
        return refs
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _public_run_response_payload(response: RunResponse) -> dict[str, object]:
    return {
        "run_id": response.run_id,
        "tool_call_id": response.tool_call_id,
        "status": response.status.value,
        "output": response.output,
        "artifact_refs": [_public_artifact_ref(ref) for ref in response.artifact_refs],
        "usage_metrics": response.usage_metrics,
        "trace_ref": response.trace_ref,
        "error_code": response.error_code,
        "error_message": response.error_message,
    }


def _public_artifact_ref(ref: ArtifactRef) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_id": ref.artifact_id,
        "artifact_type": ref.artifact_type,
        "mime_type": ref.mime_type,
        "size_bytes": ref.size_bytes,
        "checksum": ref.checksum,
        "data_class": ref.data_class,
        "retention_policy": ref.retention_policy,
        "access_policy": ref.access_policy,
    }
    if ref.expires_at is not None:
        payload["expires_at"] = ref.expires_at.isoformat()
    if ref.download_url is not None:
        payload["download_url"] = ref.download_url
    return payload
