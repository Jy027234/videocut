"""P0.7 local HTTP API contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from conftest import REPO_ROOT, assert_no_public_path_or_command_leak, walk_json
from video_editing_toolkit.agentctl import run_agentctl
from video_editing_toolkit.local_api import create_app


def test_local_api_posts_agentctl_like_envelope_and_queries_status(tmp_path: Path) -> None:
    artifact_root = tmp_path / "local-api-artifacts"
    secret_value = "local-api-private-key"
    client = TestClient(
        create_app(
            artifact_root=artifact_root,
            manifests_dir=REPO_ROOT / "manifests",
        )
    )
    payload = {
        "run_id": "run_local_api_create_project",
        "tool_call_id": "tool_call_local_api_create_project",
        "trace_ref": "trace_platform_local_api",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.project_edit.create_project",
        "version": "0.1.0-p0",
        "max_attempts": 2,
        "artifact_store_root": str(tmp_path / "input-root-should-not-leak"),
        "private_key": secret_value,
        "policy_context": {
            "tenant_id": "tenant_local_api",
            "user_id": "user_local_api",
            "data_policy": {"classification": "medium"},
            "quota_policy": {"mode": "demo"},
        },
        "input": {
            "project_id": "proj_local_api_create",
            "_worker_media_path": str(tmp_path / "private-input.mp4"),
        },
        "artifact_refs": [
            {
                "artifact_id": "artifact_optional_local_api_ref",
                "artifact_type": "input_video",
                "mime_type": "video/mp4",
                "size_bytes": 123,
                "checksum": "sha256:optional",
                "storage_uri": f"local-artifact://artifact_optional_local_api_ref/{secret_value}",
            }
        ],
    }

    created = client.post("/local/toolkit-runs", json=payload)

    assert created.status_code == 200
    body = created.json()
    assert body["run_id"] == payload["run_id"]
    assert body["tool_call_id"] == payload["tool_call_id"]
    assert body["trace_ref"] == "trace_platform_local_api"
    assert body["status"] == "succeeded"
    assert body["output"]["project_id"] == "proj_local_api_create"
    assert body["output"]["adapter_name"] == "project_edit"
    assert body["retry"]["attempt"] == 1
    assert body["retry"]["max_attempts"] == 2
    assert body["retry"]["terminal_reason"] == "succeeded"
    assert body["usage_summary"]["billing_ready"] is True
    assert body["usage_summary"]["charged"] is False
    assert body["usage_summary"]["capability"] == payload["capability"]
    assert body["usage_summary"]["capability_usage"][payload["capability"]]["runs"] == 1
    _assert_local_api_safe(body, artifact_root, secret_value)

    status = client.get(f"/local/toolkit-runs/{payload['run_id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
    assert status.json()["trace_ref"] == "trace_platform_local_api"
    assert status.json()["output"]["project_id"] == "proj_local_api_create"
    assert status.json()["retry"]["max_attempts"] == 2
    assert status.json()["usage_summary"]["billing_mode"] == "local_preview_no_charge"
    _assert_local_api_safe(status.json(), artifact_root, secret_value)


def test_local_api_unknown_capability_returns_queryable_failure(tmp_path: Path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    payload = {
        "run_id": "run_local_api_unknown",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.unknown.noop",
        "max_attempts": 3,
        "input": {"project_id": "proj_local_api_unknown"},
    }

    created = client.post("/local/toolkit-runs", json=payload)

    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "handler_not_registered"
    assert "No local handler registered" in body["error_message"]
    assert body["retry"]["attempt"] == 1
    assert body["retry"]["max_attempts"] == 3
    assert body["retry"]["scheduled"] is False
    assert body["retry"]["terminal_reason"] == "terminal_error"
    _assert_local_api_safe(body, tmp_path / "artifacts")

    status = client.get("/local/toolkit-runs/run_local_api_unknown")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert status.json()["error_code"] == "handler_not_registered"


def test_local_api_and_agentctl_no_upload_request_stay_caller_safe_consistent(tmp_path: Path) -> None:
    local_api_root = tmp_path / "local-api-artifacts"
    agentctl_root = tmp_path / "agentctl-artifacts"
    secret_value = "shared-no-upload-private-key"
    payload = {
        "run_id": "run_no_upload_consistency",
        "tool_call_id": "tool_call_no_upload_consistency",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.delivery.generate_variants",
        "version": "0.1.0-p0",
        "artifact_store_root": str(tmp_path / "payload-root-should-not-leak"),
        "private_key": secret_value,
        "policy_context": {
            "tenant_id": "tenant_no_upload",
            "user_id": "user_no_upload",
        },
        "artifact_refs": [
            {
                "artifact_id": "artifact_no_upload_future_handoff",
                "artifact_type": "input_video",
                "mime_type": "video/mp4",
                "size_bytes": 123,
                "checksum": "sha256:future",
                "storage_uri": f"local-artifact://artifact_no_upload_future_handoff/{secret_value}",
            }
        ],
        "input": {
            "project_id": "proj_no_upload_consistency",
            "version": "ver_no_upload_0001",
            "variants": [
                {
                    "name": "web",
                    "delivery_target": "web",
                    "format": "mp4",
                    "resolution": "1080p",
                }
            ],
        },
    }

    agentctl_body = run_agentctl(payload, artifact_root=agentctl_root)
    client = TestClient(create_app(artifact_root=local_api_root))
    created = client.post("/local/toolkit-runs", json=payload)

    assert created.status_code == 200
    local_api_body = created.json()
    assert agentctl_body["ok"] is True
    assert _normalize_agentctl_run(agentctl_body) == _normalize_local_api_run(
        local_api_body,
        capability=payload["capability"],
    )
    _assert_local_api_safe(agentctl_body, agentctl_root, secret_value)
    _assert_local_api_safe(local_api_body, local_api_root, secret_value)

    status = client.get(f"/local/toolkit-runs/{payload['run_id']}")
    assert status.status_code == 200
    assert _normalize_agentctl_run(agentctl_body) == _normalize_local_api_run(
        status.json(),
        capability=payload["capability"],
    )
    _assert_local_api_safe(status.json(), local_api_root, secret_value)


def test_local_api_artifact_endpoint_returns_public_metadata_only(tmp_path: Path) -> None:
    artifact_root = tmp_path / "local-api-artifacts"
    client = TestClient(create_app(artifact_root=artifact_root))
    payload = {
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.delivery.create_delivery_manifest",
        "input": {
            "project_id": "proj_local_api_delivery",
            "version": "ver_local_api_0001",
            "variants": ["web"],
        },
    }

    created = client.post("/local/toolkit-runs", json=payload)

    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "succeeded"
    artifact_ref = body["artifact_refs"][0]
    artifact_id = artifact_ref["artifact_id"]
    assert artifact_ref["download_url"] == f"/local/artifacts/{artifact_id}"

    artifact = client.get(f"/local/artifacts/{artifact_id}")
    assert artifact.status_code == 200
    metadata = artifact.json()
    assert metadata == artifact_ref
    assert metadata["artifact_type"] == "delivery_manifest"
    assert "storage_uri" not in metadata
    _assert_local_api_safe(metadata, artifact_root)

    missing = client.get("/local/artifacts/artifact_missing")
    assert missing.status_code == 404


def test_local_api_manifests_returns_manifest_payload_without_paths(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            artifact_root=tmp_path / "artifacts",
            manifests_dir=REPO_ROOT / "manifests",
        )
    )

    response = client.get("/local/manifests")

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "video_editing_toolkit.local_http_api.v0"
    assert body["transport"] == "local.http"
    assert body["toolkit_id"] == "video-editing-toolkit"
    assert body["manifests"]
    assert body["manifests"][0]["file_name"] == "video-editing-toolkit.p0.manifest.json"
    assert body["manifests"][0]["manifest"]["toolkit_id"] == "video-editing-toolkit"
    _assert_local_api_safe(body, tmp_path / "artifacts")


def test_local_api_missing_run_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))

    response = client.get("/local/toolkit-runs/run_missing")

    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "local_api.run_not_found"


def test_local_api_cancels_queued_run_without_processing(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            artifact_root=tmp_path / "artifacts",
            process_sync=False,
        )
    )
    payload = {
        "run_id": "run_local_api_cancel",
        "tool_call_id": "tool_call_local_api_cancel",
        "trace_id": "trace_cancel_from_platform",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.project_edit.create_project",
        "max_attempts": 3,
        "input": {"project_id": "proj_should_not_process"},
    }

    created = client.post("/local/toolkit-runs", json=payload)
    cancelled = client.post("/local/toolkit-runs/run_local_api_cancel/cancel")
    status = client.get("/local/toolkit-runs/run_local_api_cancel")
    missing = client.post("/local/toolkit-runs/run_missing/cancel")

    assert created.status_code == 200
    assert created.json()["status"] == "queued"
    assert created.json()["trace_ref"] == "trace_cancel_from_platform"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["trace_ref"] == "trace_cancel_from_platform"
    assert cancelled.json()["retry"]["scheduled"] is False
    assert cancelled.json()["retry"]["terminal_reason"] == "cancelled"
    assert status.status_code == 200
    assert status.json()["status"] == "cancelled"
    assert missing.status_code == 404
    assert missing.json()["detail"]["error_code"] == "local_api.run_not_found"
    _assert_local_api_safe(cancelled.json(), tmp_path / "artifacts")


def _assert_local_api_safe(
    body: dict[str, Any],
    artifact_root: Path,
    secret_value: str | None = None,
) -> None:
    assert_no_public_path_or_command_leak(body)
    rendered = json.dumps(body, sort_keys=True)
    assert str(artifact_root) not in rendered
    if secret_value is not None:
        assert secret_value not in rendered
    for path, node in walk_json(body):
        if isinstance(node, dict):
            leaked = {
                "private_key",
                "api_key",
                "client_secret",
                "token",
                "password",
            }.intersection(node)
            assert not leaked, f"{path} exposes private keys: {sorted(leaked)}"


def _normalize_agentctl_run(body: dict[str, Any]) -> dict[str, Any]:
    processed = body["processed"]
    return {
        "capability": body["capability"],
        "run_id": processed["run_id"],
        "tool_call_id": processed["tool_call_id"],
        "status": processed["status"],
        "output": processed["output"],
    }


def _normalize_local_api_run(body: dict[str, Any], *, capability: str) -> dict[str, Any]:
    return {
        "capability": capability,
        "run_id": body["run_id"],
        "tool_call_id": body["tool_call_id"],
        "status": body["status"],
        "output": body["output"],
    }
