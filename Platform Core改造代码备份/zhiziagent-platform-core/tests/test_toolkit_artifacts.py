from __future__ import annotations

import base64
import hashlib

from fastapi.testclient import TestClient

from zhiziagent_platform_core.app import create_app
from zhiziagent_platform_core.settings import Settings


def _client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'toolkit-artifacts.db'}",
        jwt_secret="test-secret",
        app_env="test",
        agentctl_admin_token="test-agentctl-admin",
        bootstrap_admin_token="test-bootstrap-admin",
        **overrides,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str, tenant_name: str = "Artifact Tenant") -> dict:
    resp = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password-123",
            "display_name": email.split("@")[0],
            "tenant_name": tenant_name,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _headers(token_payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_payload['access_token']}"}


def _service_token(client: TestClient, token_payload: dict, scopes: list[str]) -> str:
    resp = client.post(
        f"/tenants/{token_payload['tenant_id']}/service-accounts",
        headers=_headers(token_payload),
        json={"app_id": "agentctl", "name": "video toolkit worker", "scopes": scopes},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def test_toolkit_artifact_inline_bytes_are_authorized_for_worker_download(tmp_path):
    content = b"platform-core-video-input"
    digest = hashlib.sha256(content).hexdigest()
    with _client(tmp_path) as client:
        owner = _register(client, "video-artifact-owner@example.com")
        service_token = _service_token(client, owner, ["agentctl.*"])

        created = client.post(
            "/toolkit-artifacts",
            headers=_headers(owner),
            json={
                "toolkit_id": "video-editing-toolkit",
                "capability": "video.asset_ingest.probe_media",
                "artifact_type": "source_video",
                "file_name": "../input.mp4",
                "mime_type": "video/mp4",
                "data_class": "D3",
                "retention_policy": "short_lived",
                "run_id": "run_video_smoke",
                "trace_id": "trace_video_smoke",
                "content_base64": base64.b64encode(content).decode("ascii"),
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["artifact_id"].startswith("tka_")
        assert body["file_name"] == "input.mp4"
        assert body["storage_kind"] == "inline"
        assert body["checksum"] == f"sha256:{digest}"
        assert "content_base64" not in created.text
        assert body["artifact_ref"] == {
            "artifact_id": body["artifact_id"],
            "artifact_type": "source_video",
            "owner_tenant_id": owner["tenant_id"],
            "created_by_run_id": "run_video_smoke",
            "mime_type": "video/mp4",
            "size_bytes": len(content),
            "checksum": f"sha256:{digest}",
            "data_class": "D3",
            "retention_policy": "short_lived",
            "access_policy": {},
            "download_url": f"/toolkit-artifacts/{body['artifact_id']}/bytes",
            "expires_at": None,
        }

        downloaded = client.get(
            body["artifact_ref"]["download_url"],
            headers={"Authorization": f"Bearer {service_token}"},
        )
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == content
        assert downloaded.headers["content-type"].startswith("video/mp4")
        assert downloaded.headers["x-artifact-checksum"] == f"sha256:{digest}"


def test_toolkit_artifacts_are_tenant_scoped_for_metadata_and_bytes(tmp_path):
    content = b"tenant-private-bytes"
    with _client(tmp_path) as client:
        owner = _register(client, "artifact-tenant-owner@example.com")
        other = _register(client, "artifact-other@example.com", "Other Artifact Tenant")
        other_service_token = _service_token(client, other, ["agentctl.*"])

        created = client.post(
            "/toolkit-artifacts",
            headers=_headers(owner),
            json={
                "toolkit_id": "video-editing-toolkit",
                "artifact_type": "source_video",
                "mime_type": "video/mp4",
                "content_base64": base64.b64encode(content).decode("ascii"),
            },
        )
        assert created.status_code == 201, created.text
        artifact_id = created.json()["artifact_id"]

        metadata = client.get(f"/toolkit-artifacts/{artifact_id}", headers=_headers(other))
        assert metadata.status_code == 404
        downloaded = client.get(
            f"/toolkit-artifacts/{artifact_id}/bytes",
            headers={"X-Service-Token": other_service_token},
        )
        assert downloaded.status_code == 404


def test_toolkit_artifact_service_token_requires_artifact_scope(tmp_path):
    content = b"scope-protected-bytes"
    with _client(tmp_path) as client:
        owner = _register(client, "artifact-scope-owner@example.com")
        weak_service_token = _service_token(client, owner, ["usage.write"])

        created = client.post(
            "/toolkit-artifacts",
            headers=_headers(owner),
            json={
                "toolkit_id": "video-editing-toolkit",
                "mime_type": "video/mp4",
                "content_base64": base64.b64encode(content).decode("ascii"),
            },
        )
        assert created.status_code == 201, created.text

        denied = client.get(
            created.json()["artifact_ref"]["download_url"],
            headers={"X-Service-Token": weak_service_token},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "Service token missing toolkit.artifacts.read"


def test_toolkit_artifact_inline_limit_is_enforced(tmp_path):
    with _client(tmp_path, toolkit_artifact_inline_max_bytes=3) as client:
        owner = _register(client, "artifact-limit-owner@example.com")
        too_large = client.post(
            "/toolkit-artifacts",
            headers=_headers(owner),
            json={
                "toolkit_id": "video-editing-toolkit",
                "content_base64": base64.b64encode(b"four").decode("ascii"),
            },
        )
        assert too_large.status_code == 413
        assert too_large.json()["detail"] == "Toolkit artifact exceeds inline byte limit"
