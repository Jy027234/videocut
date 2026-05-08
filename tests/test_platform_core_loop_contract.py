"""P1.8 explicit Platform Core local loop runner contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.platform_core_loop import (
    PlatformCoreLocalLoopConfig,
    build_platform_core_local_loop_preview,
    run_platform_core_local_loop,
)


def test_platform_core_loop_default_is_no_mutation_preview(tmp_path: Path) -> None:
    fake = FakePlatformCoreLoopClient()
    config = _config(tmp_path, token="control-token", artifact_token="artifact-token")

    report = run_platform_core_local_loop(config, client=fake)
    rendered = json.dumps(report, sort_keys=True)

    assert report["contract"] == "platform_core_local_loop_runner_preview.v0"
    assert report["status"] == "preview_only"
    assert report["dry_run"] is True
    assert report["network_mutation"] is False
    assert report["execution_performed"] is False
    assert report["explicit_opt_in_required"] is True
    assert report["local_loop_package"]["execution_performed"] is False
    assert fake.requests == []
    assert "control-token" not in rendered
    assert "artifact-token" not in rendered
    assert_no_public_path_or_command_leak(report)


def test_platform_core_loop_executes_chain_with_fake_client(tmp_path: Path) -> None:
    fake = FakePlatformCoreLoopClient()
    config = _config(
        tmp_path,
        token="control-token",
        artifact_token="artifact-token",
        input_payload={"project_id": "proj_p1_8_loop"},
    )

    report = run_platform_core_local_loop(config, execute=True, client=fake)
    rendered = json.dumps(report, sort_keys=True)

    assert report["contract"] == "platform_core_local_loop_runner.v0"
    assert report["status"] == "completed"
    assert report["dry_run"] is False
    assert report["network_mutation"] is True
    assert report["execution_performed"] is True
    assert report["manifest_registration_dry_run"]["contract"] == "platform_core_manifest_registration_dry_run.v0"
    assert report["manifest_registration_dry_run"]["network_mutation"] is False
    assert report["runspec_enqueue"]["payload"]["dispatch_mode"] == "enqueue"
    assert report["runspec_enqueue"]["runtime_job_id"] == "rtjob_p1_8_loop"
    assert report["worker_run"]["status"] == "completed"
    assert report["platform_core_completion"]["contract"] == "platform_core_toolkit_run_completion.v0"
    assert report["platform_core_completion"]["status"] == "succeeded"
    assert report["platform_core_completion"]["run_id"] == "rtjob_p1_8_loop"
    assert report["platform_core_completion"]["output"]["project_id"] == "proj_p1_8_loop"
    assert report["platform_core_completion"]["artifact_lifecycle_summary"]["status"] == "not_requested"
    assert report["audit_event"]["contract"] == "platform_core_learning_audit_event.v0"
    assert report["audit_event"]["data_minimization"]["raw_input_logged"] is False
    assert fake.paths == [
        "/runspecs/run",
        "/runtime/backends/workers/heartbeat",
        "/runtime/backends/jobs/lease",
        "/runtime/backends/jobs/rtjob_p1_8_loop/complete",
    ]
    assert "control-token" not in rendered
    assert "artifact-token" not in rendered
    assert_no_public_path_or_command_leak(report)


def test_platform_core_loop_rejects_unexpected_leased_job_without_completion(tmp_path: Path) -> None:
    fake = FakePlatformCoreLoopClient(lease_job_id="rtjob_other")
    report = run_platform_core_local_loop(_config(tmp_path), execute=True, client=fake)

    assert report["status"] == "failed"
    assert report["worker_run"]["status"] == "unexpected_job_leased"
    assert report["worker_run"]["expected_job_id"] == "rtjob_p1_8_loop"
    assert report["worker_run"]["leased_job_id"] == "rtjob_other"
    assert "/runtime/backends/jobs/rtjob_other/complete" not in fake.paths
    assert report["platform_core_completion"]["status"] == "failed"
    assert_no_public_path_or_command_leak(report)


def test_platform_core_loop_scrubs_download_url_query_tokens(tmp_path: Path) -> None:
    report = build_platform_core_local_loop_preview(
        _config(
            tmp_path,
            artifact_refs=[
                {
                    "artifact_id": "artifact_loop_source",
                    "artifact_type": "source_video",
                    "mime_type": "video/mp4",
                    "size_bytes": 123,
                    "checksum": "sha256:" + "a" * 64,
                    "download_url": "/toolkit-artifacts/artifact_loop_source/bytes?sat=secret-sat-token&view=1",
                    "storage_uri": "s3://private-bucket/source.mov",
                }
            ],
        )
    )
    rendered = json.dumps(report, sort_keys=True)

    assert "secret-sat-token" not in rendered
    assert "storage_uri" not in rendered
    assert_no_public_path_or_command_leak(report)


def test_platform_core_loop_cli_default_outputs_no_mutation_preview() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "video_editing_toolkit.platform_core_loop"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_local_loop_runner_preview.v0"
    assert payload["network_mutation"] is False
    assert payload["execution_performed"] is False
    assert_no_public_path_or_command_leak(payload)


class FakePlatformCoreLoopClient:
    def __init__(self, *, lease_job_id: str = "rtjob_p1_8_loop") -> None:
        self.lease_job_id = lease_job_id
        self.enqueued_payload: dict[str, Any] | None = None
        self.requests: list[dict[str, Any]] = []

    @property
    def paths(self) -> list[str]:
        return [request["path"] for request in self.requests]

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(body or {})
        self.requests.append({"path": path, "body": payload})
        if path == "/runspecs/run":
            self.enqueued_payload = payload
            return {
                "runspec_id": "runspec_p1_8_loop",
                "status": "queued",
                "dispatch_mode": payload["dispatch_mode"],
                "runtime_job": {
                    "job_id": "rtjob_p1_8_loop",
                    "backend_id": payload["backend_id"],
                    "backend_kind": "local",
                    "status": "queued",
                    "target_agent": payload["target_agent"],
                },
            }
        if path == "/runtime/backends/workers/heartbeat":
            return {
                "kind": "AIOSRuntimeWorkerHeartbeat",
                "worker": {
                    "worker_id": payload["worker_id"],
                    "backend_id": payload["backend_id"],
                    "backend_kind": "local",
                    "status": "ready",
                    "alive": True,
                    "available_slots": 1,
                },
            }
        if path == "/runtime/backends/jobs/lease":
            return {
                "kind": "AIOSRuntimeJobLease",
                "lease_id": "lease_p1_8_loop",
                "lease_seconds": payload["lease_seconds"],
                "expired_leases_requeued": 0,
                "job": self._leased_job(),
            }
        if path.startswith("/runtime/backends/jobs/") and path.endswith("/complete"):
            job_id = path.split("/")[-2]
            return {
                "kind": "AIOSRuntimeDispatchJobCompleted",
                "job": {
                    "job_id": job_id,
                    "status": payload["status"],
                    "backend_id": "local",
                    "leased_by": payload["worker_id"],
                    "attempts": 1,
                    "error": payload.get("error"),
                },
            }
        raise AssertionError(f"Unexpected POST path: {path}")

    def _leased_job(self) -> dict[str, Any]:
        assert self.enqueued_payload is not None
        return {
            "job_id": self.lease_job_id,
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
                "runspec_id": "runspec_p1_8_loop",
                "target_agent": self.enqueued_payload["target_agent"],
                "tenant": self.enqueued_payload["tenant_id"],
                "trace_id": self.enqueued_payload["trace_id"],
                "input_payload": self.enqueued_payload["input_payload"],
            },
            "metadata": {
                "runspec_id": "runspec_p1_8_loop",
                "dispatch_mode": "enqueue",
            },
        }


def _config(
    tmp_path: Path,
    *,
    token: str | None = None,
    artifact_token: str | None = None,
    input_payload: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> PlatformCoreLocalLoopConfig:
    return PlatformCoreLocalLoopConfig(
        tenant_id="tenant_p1_8_loop",
        input_payload=input_payload,
        artifact_refs=artifact_refs or (),
        base_url="http://agentctl.local",
        token=token,
        artifact_token=artifact_token,
        artifact_root=tmp_path / "platform-core-loop-artifacts",
    )
