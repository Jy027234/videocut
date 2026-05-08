"""Reusable agentctl queue smoke contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.agentctl_live_smoke import run_agentctl_queue_smoke
from video_editing_toolkit.agentctl_remote import build_runspec_enqueue_payload
from video_editing_toolkit.agentctl_worker import VideoToolkitWorkerConfig


def test_runspec_enqueue_payload_targets_existing_artifact_refs() -> None:
    content = b"queue smoke bytes"
    artifact_ref = _artifact_ref("artifact_queue_payload", content)

    payload = build_runspec_enqueue_payload(
        tenant_id="tenant_queue",
        backend_id="local",
        capability="video.asset_ingest.build_asset_index",
        input_payload={"project_id": "proj_queue", "artifact_ids": ["artifact_queue_payload"]},
        artifact_refs=[artifact_ref],
    )

    assert payload["dispatch_mode"] == "enqueue"
    assert payload["backend_id"] == "local"
    assert payload["input_payload"]["capability"] == "video.asset_ingest.build_asset_index"
    assert payload["input_payload"]["artifact_refs"] == [artifact_ref]
    assert payload["input_payload"]["policy_context"]["tenant_id"] == "tenant_queue"
    assert_no_public_path_or_command_leak(payload)


def test_queue_smoke_enqueues_leases_downloads_and_completes_with_split_tokens(tmp_path: Path) -> None:
    content = b"real queue smoke artifact bytes"
    artifact_id = "artifact_queue_smoke"
    artifact_ref = _artifact_ref(artifact_id, content)
    fake_client = FakeQueueSmokeClient()
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    config = VideoToolkitWorkerConfig(
        base_url="http://agentctl.local",
        token="control-token",
        artifact_token="artifact-token",
        worker_id="video-worker-queue-smoke",
        backend_id="local",
        ttl_seconds=60,
        lease_seconds=30,
        timeout_seconds=5,
        artifact_root=tmp_path / "worker-artifacts",
        artifact_base_url="http://platform.local",
        max_artifact_bytes=1024,
        max_job_input_bytes=1024,
    )

    report = run_agentctl_queue_smoke(
        config=config,
        tenant_id="tenant_worker",
        input_payload={"project_id": "proj_queue_smoke", "artifact_ids": [artifact_id]},
        artifact_refs=[artifact_ref],
        client=fake_client,
        artifact_fetcher=fetcher,
    )

    complete = fake_client.requests[-1]
    assert report["ok"] is True
    assert report["status"] == "completed"
    assert report["control_plane"]["dispatch_mode"] == "enqueue"
    assert report["artifact_download"]["separate_artifact_credentials"] is True
    assert fake_client.paths == [
        "/runspecs/run",
        "/runtime/backends/workers/heartbeat",
        "/runtime/backends/jobs/lease",
        "/runtime/backends/jobs/rtjob_queue_smoke/complete",
    ]
    assert fetcher.requests[0]["headers"]["Authorization"] == "Bearer artifact-token"
    assert complete["body"]["status"] == "completed"
    assert complete["body"]["result"]["processed"]["output"]["asset_count"] == 1
    rendered = json.dumps({"report": report, "complete": complete["body"]}, sort_keys=True)
    assert "control-token" not in rendered
    assert "artifact-token" not in rendered
    assert_no_public_path_or_command_leak(report)
    assert_no_public_path_or_command_leak(complete["body"])


class FakeQueueSmokeClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.enqueued_payload: dict[str, Any] | None = None

    @property
    def paths(self) -> list[str]:
        return [request["path"] for request in self.requests]

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(body or {})
        self.requests.append({"path": path, "body": payload})
        if path == "/runspecs/run":
            self.enqueued_payload = payload
            return {
                "runspec_id": "runspec_queue_smoke",
                "status": "queued",
                "dispatch_mode": payload["dispatch_mode"],
                "runtime_job": {
                    "job_id": "rtjob_queue_smoke",
                    "backend_id": payload["backend_id"],
                    "backend_kind": "local",
                    "status": "queued",
                    "target_agent": payload["target_agent"],
                },
            }
        if path == "/runtime/backends/workers/heartbeat":
            return {
                "worker": {
                    "worker_id": payload["worker_id"],
                    "backend_id": payload["backend_id"],
                    "backend_kind": "local",
                    "status": "ready",
                    "alive": True,
                    "available_slots": 1,
                }
            }
        if path == "/runtime/backends/jobs/lease":
            assert self.enqueued_payload is not None
            return {
                "lease_id": "lease_queue_smoke",
                "lease_seconds": payload["lease_seconds"],
                "expired_leases_requeued": 0,
                "job": {
                    "job_id": "rtjob_queue_smoke",
                    "source": "runspec",
                    "backend_id": "local",
                    "backend_kind": "local",
                    "status": "leased",
                    "target_agent": self.enqueued_payload["target_agent"],
                    "tenant": self.enqueued_payload["tenant_id"],
                    "trace_id": self.enqueued_payload["trace_id"],
                    "attempts": 1,
                    "payload": {
                        "source": "runspec",
                        "runspec_id": "runspec_queue_smoke",
                        "target_agent": self.enqueued_payload["target_agent"],
                        "tenant": self.enqueued_payload["tenant_id"],
                        "trace_id": self.enqueued_payload["trace_id"],
                        "input_payload": self.enqueued_payload["input_payload"],
                    },
                    "metadata": {
                        "runspec_id": "runspec_queue_smoke",
                        "dispatch_mode": "enqueue",
                    },
                },
            }
        if path == "/runtime/backends/jobs/rtjob_queue_smoke/complete":
            return {
                "job": {
                    "job_id": "rtjob_queue_smoke",
                    "status": payload["status"],
                    "backend_id": "local",
                    "leased_by": payload["worker_id"],
                    "attempts": 1,
                    "error": payload.get("error"),
                }
            }
        raise AssertionError(f"Unexpected POST path: {path}")


class FakeArtifactBytesFetcher:
    def __init__(self, responses: Mapping[str, bytes]) -> None:
        self.responses = dict(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> bytes:
        self.requests.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "max_bytes": max_bytes,
            }
        )
        return self.responses[url]


def _artifact_ref(artifact_id: str, content: bytes) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": "source_video",
        "owner_tenant_id": "tenant_worker",
        "created_by_run_id": "run_source",
        "mime_type": "video/mp4",
        "size_bytes": len(content),
        "checksum": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "data_class": "sensitive",
        "retention_policy": "short_lived",
        "download_url": "/artifacts/download/input.mp4",
    }
