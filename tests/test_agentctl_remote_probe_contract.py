"""P0.9 remote agentctl pre-integration probe contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from conftest import REPO_ROOT, assert_no_public_path_or_command_leak
from video_editing_toolkit.agentctl_remote import (
    AgentctlRemoteClient,
    AgentctlRemoteConfig,
    REQUIRED_AGENTCTL_PATHS,
    build_runspec_validation_payload,
    build_tool_catalog_registration_payload,
    run_agentctl_remote_probe,
)


MANIFEST_PATH = REPO_ROOT / "manifests" / "video-editing-toolkit.p0.manifest.json"


def test_tool_catalog_registration_payload_is_manifest_backed_and_caller_safe() -> None:
    payload = build_tool_catalog_registration_payload(MANIFEST_PATH, tenant_id="tenant_probe")

    capabilities = payload["tool_schema"]["properties"]["capability"]["enum"]
    assert payload["tool_id"] == "video-editing-toolkit"
    assert payload["tenant_id"] == "tenant_probe"
    assert payload["metadata"]["execution_model"] == "external_video_toolkit_worker"
    assert "video.project_edit.create_project" in capabilities
    assert "video.render.render_final" in capabilities
    assert payload["secret_refs"] == []

    rendered = json.dumps(payload, sort_keys=True)
    assert str(REPO_ROOT) not in rendered
    assert_no_public_path_or_command_leak(payload)


def test_runspec_validation_payload_is_no_upload_and_caller_safe() -> None:
    payload = build_runspec_validation_payload(tenant_id="tenant_probe")

    assert payload["kind"] == "RunSpecDraft"
    assert payload["target_agent"] == "video_editing_toolkit_agentctl"
    assert payload["tenant_id"] == "tenant_probe"
    assert payload["input_payload"]["toolkit_id"] == "video-editing-toolkit"
    assert payload["input_payload"]["capability"] == "video.project_edit.create_project"
    assert payload["input_payload"]["artifact_refs"] == []
    assert payload["metadata"]["run_heavy_media_inside_agentctl"] is False
    assert_no_public_path_or_command_leak(payload)


def test_remote_probe_prefers_runtime_worker_protocol_without_mutation() -> None:
    fake = FakeUrlopen()
    client = AgentctlRemoteClient(
        AgentctlRemoteConfig(base_url="http://agentctl.local", token="probe-token"),
        urlopen=fake,
    )

    report = run_agentctl_remote_probe(
        config=client.config,
        manifest_path=MANIFEST_PATH,
        client=client,
    )

    assert report["ok"] is True
    assert report["agentctl"]["api_version"] == "0.2.0b2"
    assert report["compatibility"]["missing_required_paths"] == []
    assert report["runtime"]["protocol_version"] == "0.1.0"
    assert report["performance_decision"]["deployment_model"] == "standalone_video_toolkit_worker"
    assert report["performance_decision"]["run_heavy_media_inside_agentctl"] is False
    assert report["registration"]["dry_run"] is True
    assert report["registration"]["result"]["reason"] == "mutation_not_requested"
    assert report["runspec_validation"]["dry_run"] is True
    assert report["runspec_validation"]["result"]["reason"] == "runspec_validation_not_requested"
    assert "probe-token" not in json.dumps(report, sort_keys=True)
    assert all(request["method"] == "GET" for request in fake.requests)


def test_remote_probe_registers_only_when_explicitly_requested() -> None:
    fake = FakeUrlopen()
    client = AgentctlRemoteClient(
        AgentctlRemoteConfig(base_url="http://agentctl.local", token="probe-token"),
        urlopen=fake,
    )

    report = run_agentctl_remote_probe(
        config=client.config,
        manifest_path=MANIFEST_PATH,
        register=True,
        client=client,
    )

    register_requests = [
        request
        for request in fake.requests
        if request["method"] == "POST" and request["path"] == "/tool-catalog/register"
    ]
    assert report["ok"] is True
    assert report["registration"]["dry_run"] is False
    assert report["registration"]["result"]["registered"] is True
    assert len(register_requests) == 1
    assert register_requests[0]["body"]["tool_id"] == "video-editing-toolkit"
    assert register_requests[0]["body"]["secret_refs"] == []


def test_remote_probe_validates_runspec_only_when_explicitly_requested() -> None:
    fake = FakeUrlopen()
    client = AgentctlRemoteClient(
        AgentctlRemoteConfig(base_url="http://agentctl.local", token="probe-token"),
        urlopen=fake,
    )

    report = run_agentctl_remote_probe(
        config=client.config,
        manifest_path=MANIFEST_PATH,
        validate_runspec=True,
        client=client,
    )

    request = _request(fake, "POST", "/runspecs/validate")
    assert report["ok"] is True
    assert report["runspec_validation"]["dry_run"] is False
    assert report["runspec_validation"]["valid"] is True
    assert request["body"]["target_agent"] == "video_editing_toolkit_agentctl"
    assert request["body"]["input_payload"]["capability"] == "video.project_edit.create_project"
    assert request["body"]["metadata"]["run_heavy_media_inside_agentctl"] is False


def test_worker_smoke_is_opt_in_and_uses_short_heartbeat() -> None:
    fake = FakeUrlopen()
    client = AgentctlRemoteClient(
        AgentctlRemoteConfig(base_url="http://agentctl.local", token="probe-token"),
        urlopen=fake,
    )

    report = run_agentctl_remote_probe(
        config=client.config,
        manifest_path=MANIFEST_PATH,
        worker_smoke=True,
        client=client,
    )

    heartbeat = _request(fake, "POST", "/runtime/backends/workers/heartbeat")
    lease = _request(fake, "POST", "/runtime/backends/jobs/lease")
    assert report["ok"] is True
    assert report["worker_smoke"]["heartbeat_ok"] is True
    assert report["worker_smoke"]["lease_ok"] is True
    assert heartbeat["body"]["worker_id"] == "video-toolkit-p0-probe"
    assert heartbeat["body"]["ttl_seconds"] == 30
    assert lease["body"]["lease_seconds"] == 30


def test_live_agentctl_remote_probe_smoke_when_env_is_configured() -> None:
    base_url = os.environ.get("VIDEO_TOOLKIT_AGENTCTL_LIVE_URL")
    token = os.environ.get("VIDEO_TOOLKIT_AGENTCTL_LIVE_TOKEN")
    if not base_url or not token:
        pytest.skip("Set VIDEO_TOOLKIT_AGENTCTL_LIVE_URL and VIDEO_TOOLKIT_AGENTCTL_LIVE_TOKEN for live smoke.")

    report = run_agentctl_remote_probe(
        config=AgentctlRemoteConfig(base_url=base_url, token=token, timeout_seconds=5),
        manifest_path=MANIFEST_PATH,
    )

    assert report["ok"] is True
    assert report["agentctl"]["health"] == "ok"
    assert report["compatibility"]["missing_required_paths"] == []
    assert token not in json.dumps(report, sort_keys=True)


class FakeUrlopen:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float) -> "FakeResponse":
        path = urlsplit(request.full_url).path
        body = _decode_body(request.data)
        self.requests.append(
            {
                "method": request.get_method(),
                "path": path,
                "body": body,
                "timeout": timeout,
                "authorization": request.headers.get("Authorization"),
            }
        )
        return FakeResponse(_payload_for(request.get_method(), path))


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _payload_for(method: str, path: str) -> Any:
    if method == "GET" and path == "/healthz":
        return {"status": "ok"}
    if method == "GET" and path == "/openapi.json":
        return {
            "info": {"title": "agentctl HTTP API", "version": "0.2.0b2"},
            "paths": {required_path: {} for required_path in REQUIRED_AGENTCTL_PATHS},
            "x-agentctl-route-count": 356,
            "x-agentctl-generated-from": "HttpApi RouteSpec",
        }
    if method == "GET" and path == "/tool-catalog":
        return {"count": 0, "tools": []}
    if method == "GET" and path == "/runtime/backends/workers/protocol":
        return {
            "kind": "AIOSRuntimeWorkerProtocol",
            "protocol_version": "0.1.0",
            "transport": "http-json",
            "lifecycle": ["heartbeat", "lease", "execute", "complete", "repeat"],
        }
    if method == "GET" and path == "/runtime/backends":
        return {
            "default_backend_id": "local",
            "backends": [
                {
                    "id": "local",
                    "kind": "local",
                    "enabled": True,
                    "available": True,
                    "status": "ready",
                    "probe": {"dispatch_mode": "in_process"},
                },
                {
                    "id": "docker",
                    "kind": "docker",
                    "enabled": False,
                    "available": False,
                    "status": "disabled",
                    "probe": {"dispatch_mode": "container"},
                },
            ],
        }
    if method == "GET" and path == "/runtime/backends/jobs":
        return {"jobs": []}
    if method == "POST" and path == "/tool-catalog/register":
        return {"registered": True, "tool_id": "video-editing-toolkit"}
    if method == "POST" and path == "/runspecs/validate":
        return {"valid": True, "errors": []}
    if method == "POST" and path == "/runtime/backends/workers/heartbeat":
        return {"ok": True, "worker_id": "video-toolkit-p0-probe", "backend_id": "local"}
    if method == "POST" and path == "/runtime/backends/jobs/lease":
        return {"lease_id": None, "job": None, "expired_leases_requeued": 0}
    raise AssertionError(f"Unexpected request: {method} {path}")


def _decode_body(body: bytes | None) -> Any:
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))


def _request(fake: FakeUrlopen, method: str, path: str) -> dict[str, Any]:
    for request in fake.requests:
        if request["method"] == method and request["path"] == path:
            return request
    raise AssertionError(f"Missing request: {method} {path}")
