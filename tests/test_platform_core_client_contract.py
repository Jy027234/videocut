"""Offline Platform Core client contract tests."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from video_editing_toolkit.platform_core import (
    PlatformCoreClient,
    build_toolkit_artifact_create_payload,
    verify_artifact_bytes,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeUrlopen:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append(request)
        path = request.full_url.removeprefix("http://platform.test")
        body = json.loads((request.data or b"{}").decode("utf-8"))
        if path == "/auth/register":
            return _json_response(
                {
                    "access_token": "owner-token-from-platform",
                    "tenant_id": "tenant_smoke",
                    "user_id": "user_smoke",
                    "permissions": ["service_accounts.manage"],
                }
            )
        if path == "/tenants/tenant_smoke/service-accounts":
            assert request.headers["Authorization"] == "Bearer owner-token"
            return _json_response(
                {
                    "id": "svc_001",
                    "tenant_id": "tenant_smoke",
                    "app_id": body["app_id"],
                    "scopes": body["scopes"],
                    "token": "service-token-from-platform",
                }
            )
        if path == "/toolkit-artifacts":
            assert request.headers["Authorization"] == "Bearer service-token"
            content = body["content_base64"].encode("ascii")
            return _json_response(
                {
                    "artifact_id": "tka_001",
                    "artifact_ref": {
                        "artifact_id": "tka_001",
                        "artifact_type": body["artifact_type"],
                        "owner_tenant_id": "tenant_smoke",
                        "created_by_run_id": body["run_id"],
                        "mime_type": body["mime_type"],
                        "size_bytes": 25,
                        "checksum": "sha256:99b841c5aedb1a62fc0bba735f234319e13aa919c98a41805b65b6ac5afe17cd",
                        "data_class": body["data_class"],
                        "retention_policy": body["retention_policy"],
                        "access_policy": {},
                        "download_url": "/toolkit-artifacts/tka_001/bytes",
                    },
                    "observed_content_base64_length": len(content),
                }
            )
        if path == "/toolkit-artifacts/tka_001/bytes":
            assert request.headers["Authorization"] == "Bearer service-token"
            return FakeResponse(b"platform-core-video-input")
        raise AssertionError(f"unexpected request path: {path}")


def test_platform_core_client_covers_register_service_artifact_and_download_flow() -> None:
    fake_urlopen = FakeUrlopen()
    client = PlatformCoreClient(base_url="http://platform.test", urlopen=fake_urlopen)

    registered = client.register(
        email="smoke@example.com",
        password="not-a-real-password",
        display_name="Smoke User",
        tenant_name="Smoke Tenant",
    )
    service = client.create_service_account(
        tenant_id=registered["tenant_id"],
        scopes=["toolkit.artifacts.read", "toolkit.artifacts.write", "agentctl.run"],
        token="owner-token",
    )
    created = client.create_toolkit_artifact(
        content=b"platform-core-video-input",
        capability="video.asset_ingest.probe_media",
        file_name="../input.mp4",
        mime_type="video/mp4",
        run_id="run_smoke",
        trace_id="trace_smoke",
        token="service-token",
    )
    downloaded = client.download_artifact_bytes(
        created["artifact_ref"]["download_url"],
        token="service-token",
    )

    assert service["id"] == "svc_001"
    assert service["scopes"] == ["toolkit.artifacts.read", "toolkit.artifacts.write", "agentctl.run"]
    assert created["artifact_ref"]["artifact_id"] == "tka_001"
    assert downloaded == b"platform-core-video-input"
    assert [request.get_method() for request in fake_urlopen.requests] == ["POST", "POST", "POST", "GET"]
    assert fake_urlopen.requests[2].get_header("Content-type") == "application/json"


def test_build_toolkit_artifact_payload_is_inline_base64_without_local_paths() -> None:
    payload = build_toolkit_artifact_create_payload(
        content=b"abc",
        capability="video.asset_ingest.probe_media",
        file_name="input.mp4",
        mime_type="video/mp4",
        run_id="run_001",
        trace_id="trace_001",
    )

    assert payload["toolkit_id"] == "video-editing-toolkit"
    assert payload["artifact_type"] == "source_video"
    assert payload["content_base64"] == "YWJj"
    assert payload["file_name"] == "input.mp4"
    assert "local_path" not in payload
    assert "token" not in payload


def test_verify_artifact_bytes_returns_reusable_smoke_metadata() -> None:
    content = b"platform-core-video-input"
    digest = hashlib.sha256(content).hexdigest()

    result = verify_artifact_bytes(
        content,
        expected_size_bytes=len(content),
        expected_checksum=f"sha256:{digest}",
    )

    assert result == {"size_bytes": len(content), "sha256": digest}


def _json_response(payload: dict[str, Any]) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))
