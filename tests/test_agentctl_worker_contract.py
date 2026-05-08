"""P0.10 external agentctl runtime worker contract tests."""

from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path
from typing import Any, Mapping

import pytest

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.agentctl_worker import (
    VideoToolkitAgentctlWorker,
    VideoToolkitWorkerConfig,
    enqueue_probe_runspec,
    runtime_job_id_from_enqueue,
    toolkit_envelope_from_job,
)
from video_editing_toolkit.agentctl_worker_runner import WorkerLocalExecutionTimeout
from video_editing_toolkit.agentctl_worker_runner import WorkerLocalExecutionCancelled
from video_editing_toolkit.worker_pool import (
    DOCKER_EXECUTION_BACKEND,
    WORKER_POOL_CONTRACT,
    WorkerExecutionPoolConfig,
    WorkerExecutionPoolRegistry,
)
from video_editing_toolkit.storage import LocalArtifactStore


def test_worker_run_once_idles_without_job(tmp_path: Path) -> None:
    fake = FakeAgentctlWorkerClient(lease_job=None)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, token="worker-token"),
        client=fake,
    )

    result = worker.run_once()

    assert result["ok"] is True
    assert result["status"] == "idle"
    assert result["completion"] is None
    assert fake.paths == [
        "/runtime/backends/workers/heartbeat",
        "/runtime/backends/jobs/lease",
    ]
    assert "worker-token" not in json.dumps(result, sort_keys=True)
    assert_no_public_path_or_command_leak(result)


def test_worker_executes_leased_no_upload_job_and_completes(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_success",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_success"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, token="worker-token"),
        client=fake,
    )

    result = worker.run_once()

    complete = fake.requests[-1]
    complete_body = complete["body"]
    agentctl_output = complete_body["result"]

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert complete["path"] == "/runtime/backends/jobs/rtjob_worker_success/complete"
    assert complete_body["worker_id"] == "video-worker-test"
    assert complete_body["lease_id"] == "lease_worker_test"
    assert complete_body["status"] == "completed"
    assert complete_body["error"] is None
    assert agentctl_output["ok"] is True
    assert agentctl_output["processed"]["output"]["project_id"] == "proj_worker_success"
    assert agentctl_output["processed"]["run_id"] == "rtjob_worker_success"
    assert agentctl_output["processed"]["tool_call_id"] == "lease_worker_test"
    assert agentctl_output["processed"]["trace_ref"] == "trace_worker"
    assert complete_body["metadata"]["trace_ref"] == "trace_worker"
    assert complete_body["metadata"]["execution_backend"] == "in_process"
    assert complete_body["metadata"]["usage_metrics"]["attempt"] == 1
    assert complete_body["metadata"]["usage_metrics"]["max_attempts"] == 1
    assert "worker_runtime_ms" in complete_body["metadata"]["usage_metrics"]
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_subprocess_mode_executes_no_upload_job_and_completes(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_subprocess",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_subprocess"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, token="worker-token", execution_mode="subprocess"),
        client=fake,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]
    agentctl_output = complete_body["result"]

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["result"]["execution_mode"] == "subprocess"
    assert complete_body["status"] == "completed"
    assert complete_body["error"] is None
    assert agentctl_output["ok"] is True
    assert agentctl_output["processed"]["output"]["project_id"] == "proj_worker_subprocess"
    assert agentctl_output["processed"]["run_id"] == "rtjob_worker_subprocess"
    assert agentctl_output["processed"]["tool_call_id"] == "lease_worker_test"
    assert "worker-token" not in json.dumps(result, sort_keys=True)
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_subprocess_timeout_reports_stable_failure(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_timeout",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_timeout"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, execution_mode="subprocess"),
        client=fake,
        local_runner=_timeout_runner,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["result"]["execution_mode"] == "subprocess"
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_timeout"
    assert complete_body["result"]["reason_code"] == "resource.timeout_exceeded"
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_skips_cancel_requested_job_before_materialization_or_execution(tmp_path: Path) -> None:
    content = b"cancelled input bytes"
    artifact_id = "artifact_cancel_requested"
    job = _leased_job(
        job_id="rtjob_worker_cancel_requested",
        capability="video.asset_ingest.build_asset_index",
        input_payload={
            "project_id": "proj_worker_cancel_requested",
            "artifact_ids": [artifact_id],
        },
        artifact_refs=[_artifact_ref(artifact_id=artifact_id, content=content)],
    )
    job["cancel_requested"] = True
    fake = FakeAgentctlWorkerClient(lease_job=job)
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, artifact_base_url="http://platform.local"),
        client=fake,
        artifact_fetcher=fetcher,
        local_runner=_unexpected_runner,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_cancelled"
    assert complete_body["result"]["reason_code"] == "worker.cancel_requested"
    assert complete_body["result"]["cancelled"] is True
    assert fetcher.requests == []
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_rejects_attempt_above_policy_before_execution(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_attempt_exhausted",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_attempt_exhausted"},
    )
    job["attempts"] = 3
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, max_attempts=2),
        client=fake,
        local_runner=_unexpected_runner,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.retry_attempts_exhausted"
    assert complete_body["result"]["reason_code"] == "worker.max_attempts_exceeded"
    assert complete_body["metadata"]["attempt"] == 3
    assert complete_body["metadata"]["max_attempts"] == 2
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_registered_docker_backend_fails_stably_until_pool_exists(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_docker_backend",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_docker_backend"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    registry = WorkerExecutionPoolRegistry(
        {
            DOCKER_EXECUTION_BACKEND: WorkerExecutionPoolConfig(
                backend=DOCKER_EXECUTION_BACKEND,
                enabled=False,
                endpoint="https://docker-control.internal/private",
            ),
        }
    )
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, execution_mode="docker"),
        client=fake,
        execution_pool_registry=registry,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]
    rendered = json.dumps({"result": result, "complete": complete_body}, sort_keys=True)

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_backend_unavailable"
    assert complete_body["result"]["reason_code"] == "worker.execution_backend_unavailable"
    assert complete_body["result"]["execution_backend"] == "docker"
    assert complete_body["result"]["execution_pool_probe"]["backend"] == "docker"
    assert complete_body["result"]["execution_pool_probe"]["available"] is False
    assert "docker-control.internal" not in rendered
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_inflight_cancel_checker_reports_stable_failure(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_inflight_cancel",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_inflight_cancel"},
    )
    checks = iter([False, False, True])
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, execution_mode="subprocess"),
        client=fake,
        cancellation_checker=lambda _job: next(checks),
        local_runner=_cancelling_runner,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_cancelled"
    assert complete_body["result"]["reason_code"] == "worker.execution_cancelled"
    assert complete_body["result"]["cancelled"] is True
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_generic_execution_failure_is_redacted(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_malicious_error",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_worker_malicious_error"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, token="worker-token"),
        client=fake,
        local_runner=_malicious_error_runner(tmp_path),
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]
    rendered = json.dumps({"result": result, "complete": complete_body}, sort_keys=True)

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_failed"
    assert complete_body["result"]["error_message"] == "Worker failure details were redacted."
    assert "worker-token" not in rendered
    assert "secret-token-value" not in rendered
    assert "download.example" not in rendered
    assert str(tmp_path) not in rendered
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_rejects_unknown_capability_before_agentctl_execution(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_worker_failed",
        capability="video.unknown.noop",
        input_payload={"project_id": "proj_worker_failed"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path),
        client=fake,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_policy_rejected"
    assert complete_body["result"]["reason_code"] == "worker.capability_unknown"
    assert complete_body["result"]["capability"] == "video.unknown.noop"
    assert_no_public_path_or_command_leak(result)


def test_worker_default_policy_rejects_cpu_heavy_capability_before_materialization(tmp_path: Path) -> None:
    content = b"heavy input bytes"
    artifact_id = "artifact_cpu_heavy"
    job = _leased_job(
        job_id="rtjob_cpu_heavy_rejected",
        capability="video.asset_ingest.probe_media",
        input_payload={
            "project_id": "proj_cpu_heavy",
            "artifact_id": artifact_id,
        },
        artifact_refs=[_artifact_ref(artifact_id=artifact_id, content=content)],
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, artifact_base_url="http://platform.local"),
        client=fake,
        artifact_fetcher=fetcher,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_policy_rejected"
    assert complete_body["result"]["reason_code"] == "worker.resource_class_not_allowed"
    assert complete_body["result"]["resource_class"] == "cpu_heavy"
    assert fetcher.requests == []
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_policy_rejects_capability_outside_allowlist(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_capability_not_allowed",
        capability="video.asset_ingest.build_asset_index",
        input_payload={"project_id": "proj_capability_not_allowed"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(
            tmp_path,
            allowed_capabilities=("video.project_edit.create_project",),
        ),
        client=fake,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_policy_rejected"
    assert complete_body["result"]["reason_code"] == "worker.capability_not_allowed"
    assert complete_body["result"]["capability"] == "video.asset_ingest.build_asset_index"
    assert_no_public_path_or_command_leak(result)


def test_worker_policy_rejects_route_timeout_above_worker_limit(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_timeout_rejected",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_timeout_rejected"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, max_run_timeout_seconds=60),
        client=fake,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_policy_rejected"
    assert complete_body["result"]["reason_code"] == "resource.timeout_exceeded"
    assert complete_body["result"]["resource_class"] == "cpu_light"
    assert_no_public_path_or_command_leak(result)


def test_worker_allows_cpu_heavy_when_resource_policy_is_explicit(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_cpu_heavy_allowed",
        capability="video.asset_ingest.probe_media",
        input_payload={"project_id": "proj_cpu_heavy_allowed"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(
            tmp_path,
            allowed_resource_classes=("cpu_light", "cpu_heavy"),
            max_run_timeout_seconds=900,
        ),
        client=fake,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert complete_body["status"] == "failed"
    assert "video_toolkit_worker.execution_policy_rejected" not in json.dumps(complete_body["result"], sort_keys=True)
    assert complete_body["result"]["processed"]["error_code"] in {
        "adapter.unavailable",
        "artifact_ref.invalid",
        "request.invalid",
    }
    assert_no_public_path_or_command_leak(result)


def test_worker_policy_rejects_declared_input_size_before_download(tmp_path: Path) -> None:
    content = b"small bytes"
    artifact_id = "artifact_declared_too_large"
    artifact_ref = _artifact_ref(artifact_id=artifact_id, content=content)
    artifact_ref["size_bytes"] = 2048
    job = _leased_job(
        job_id="rtjob_declared_too_large",
        capability="video.asset_ingest.build_asset_index",
        input_payload={
            "project_id": "proj_declared_too_large",
            "artifact_ids": [artifact_id],
        },
        artifact_refs=[artifact_ref],
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    worker = VideoToolkitAgentctlWorker(
        _config(
            tmp_path,
            artifact_base_url="http://platform.local",
            max_job_input_bytes=1024,
        ),
        client=fake,
        artifact_fetcher=fetcher,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_policy_rejected"
    assert complete_body["result"]["reason_code"] == "resource.input_too_large"
    assert complete_body["result"]["resource_class"] == "cpu_light"
    assert fetcher.requests == []
    assert_no_public_path_or_command_leak(result)


def test_worker_heartbeat_advertises_execution_policy(tmp_path: Path) -> None:
    fake = FakeAgentctlWorkerClient(lease_job=None)
    worker = VideoToolkitAgentctlWorker(
        _config(
            tmp_path,
            allowed_resource_classes=("cpu_light", "cpu_heavy"),
            allowed_capabilities=("video.project_edit.create_project",),
            max_job_input_bytes=1234,
            max_run_timeout_seconds=321,
        ),
        client=fake,
    )

    result = worker.run_once()
    heartbeat_body = fake.requests[0]["body"]

    assert result["status"] == "idle"
    assert heartbeat_body["metadata"]["allowed_resource_classes"] == ["cpu_light", "cpu_heavy"]
    assert heartbeat_body["metadata"]["allowed_capabilities"] == ["video.project_edit.create_project"]
    assert heartbeat_body["metadata"]["max_job_input_bytes"] == 1234
    assert heartbeat_body["metadata"]["max_run_timeout_seconds"] == 321
    assert heartbeat_body["metadata"]["execution_mode"] == "in_process"
    assert heartbeat_body["metadata"]["execution_backend"] == "in_process"
    assert heartbeat_body["metadata"]["execution_pool_contract"] == WORKER_POOL_CONTRACT
    assert heartbeat_body["metadata"]["execution_pool"]["backend"] == "in_process"
    assert heartbeat_body["metadata"]["execution_pool"]["execution_supported"] is True
    assert heartbeat_body["metadata"]["worker_lifecycle_contract"] == "p0.14_execution_backend_attempt_trace_usage"
    assert heartbeat_body["metadata"]["supported_execution_backends"] == ["docker", "in_process", "remote", "subprocess"]
    assert heartbeat_body["metadata"]["retry_policy"]["mode"] == "attempt_preflight_only"
    assert heartbeat_body["metadata"]["cancel_contract"] == "pre_execution_and_subprocess_in_flight_cancel_or_kill"
    assert heartbeat_body["metadata"]["process_kill_contract"] == "terminate_then_kill_child_or_process_group"
    assert_no_public_path_or_command_leak(result)


def test_worker_materializes_artifact_ref_before_running_job(tmp_path: Path) -> None:
    content = b"worker materialized input bytes"
    artifact_id = "artifact_worker_materialized"
    job = _leased_job(
        job_id="rtjob_worker_materialized",
        capability="video.asset_ingest.build_asset_index",
        input_payload={
            "project_id": "proj_worker_materialized",
            "artifact_ids": [artifact_id],
        },
        artifact_refs=[_artifact_ref(artifact_id=artifact_id, content=content)],
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, token="worker-token", artifact_base_url="http://platform.local"),
        client=fake,
        artifact_fetcher=fetcher,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]
    agentctl_output = complete_body["result"]
    local_path = LocalArtifactStore(tmp_path / "worker-artifacts").open_local_path(artifact_id)

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert local_path is not None
    assert local_path.read_bytes() == content
    assert fetcher.requests[0]["url"] == "http://platform.local/artifacts/download/input.mp4"
    assert fetcher.requests[0]["headers"]["Authorization"] == "Bearer worker-token"
    assert complete_body["status"] == "completed"
    assert agentctl_output["ok"] is True
    assert agentctl_output["processed"]["output"]["asset_count"] == 1
    assert agentctl_output["processed"]["output"]["input_artifact_refs"][0]["artifact_id"] == artifact_id
    assert "worker-token" not in json.dumps(result, sort_keys=True)
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_artifact_download_token_can_differ_from_control_token(tmp_path: Path) -> None:
    content = b"split token input bytes"
    artifact_id = "artifact_worker_split_token"
    job = _leased_job(
        job_id="rtjob_worker_split_token",
        capability="video.asset_ingest.build_asset_index",
        input_payload={
            "project_id": "proj_worker_split_token",
            "artifact_ids": [artifact_id],
        },
        artifact_refs=[_artifact_ref(artifact_id=artifact_id, content=content)],
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    worker = VideoToolkitAgentctlWorker(
        VideoToolkitWorkerConfig(
            base_url="http://agentctl.local",
            token="control-token",
            artifact_token="artifact-token",
            worker_id="video-worker-test",
            backend_id="local",
            ttl_seconds=60,
            lease_seconds=30,
            timeout_seconds=5,
            artifact_root=tmp_path / "worker-artifacts",
            artifact_base_url="http://platform.local",
            max_artifact_bytes=1024,
            max_job_input_bytes=1024,
        ),
        client=fake,
        artifact_fetcher=fetcher,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]
    rendered = json.dumps({"result": result, "complete": complete_body}, sort_keys=True)

    assert result["ok"] is True
    assert fetcher.requests[0]["headers"]["Authorization"] == "Bearer artifact-token"
    assert "control-token" not in rendered
    assert "artifact-token" not in rendered
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_reports_materialization_failure_without_leaking_download_url(tmp_path: Path) -> None:
    content = b"expected-bytes"
    artifact_id = "artifact_worker_bad_checksum"
    job = _leased_job(
        job_id="rtjob_worker_materialization_failed",
        capability="video.asset_ingest.build_asset_index",
        input_payload={
            "project_id": "proj_worker_materialization_failed",
            "artifact_ids": [artifact_id],
        },
        artifact_refs=[_artifact_ref(artifact_id=artifact_id, content=content)],
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    fetcher = FakeArtifactBytesFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": b"mismatch-bytes",
        }
    )
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path, token="worker-token", artifact_base_url="http://platform.local"),
        client=fake,
        artifact_fetcher=fetcher,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.artifact_materialization_failed"
    assert complete_body["result"]["reason_code"] == "artifact_checksum_mismatch"
    assert complete_body["result"]["artifact_id"] == artifact_id
    assert "http://platform.local/artifacts/download/input.mp4" not in json.dumps(result, sort_keys=True)
    assert "worker-token" not in json.dumps(result, sort_keys=True)
    assert_no_public_path_or_command_leak(result)
    assert_no_public_path_or_command_leak(complete_body)


def test_worker_does_not_complete_unexpected_probe_job(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_existing_queue_item",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_existing"},
    )
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path),
        client=fake,
    )

    result = worker.run_once(expected_job_id="rtjob_expected_probe")

    assert result["ok"] is False
    assert result["status"] == "unexpected_job_leased"
    assert result["expected_job_id"] == "rtjob_expected_probe"
    assert result["leased_job_id"] == "rtjob_existing_queue_item"
    assert "/runtime/backends/jobs/rtjob_existing_queue_item/complete" not in fake.paths
    assert_no_public_path_or_command_leak(result)


def test_worker_rejects_non_video_toolkit_job_payload(tmp_path: Path) -> None:
    job = _leased_job(
        job_id="rtjob_wrong_toolkit",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_wrong_toolkit"},
    )
    job["payload"]["input_payload"]["toolkit_id"] = "other-toolkit"
    fake = FakeAgentctlWorkerClient(lease_job=job)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path),
        client=fake,
    )

    result = worker.run_once()
    complete_body = fake.requests[-1]["body"]

    assert result["ok"] is False
    assert complete_body["status"] == "failed"
    assert complete_body["result"]["error_code"] == "video_toolkit_worker.execution_failed"
    assert "not a video-editing-toolkit envelope" in complete_body["error"]
    assert_no_public_path_or_command_leak(result)


def test_toolkit_envelope_preserves_existing_run_fields() -> None:
    job = _leased_job(
        job_id="rtjob_preserve",
        capability="video.project_edit.create_project",
        input_payload={"project_id": "proj_preserve"},
    )
    job["payload"]["input_payload"]["run_id"] = "caller_run_id"
    job["payload"]["input_payload"]["tool_call_id"] = "caller_tool_call_id"

    envelope = toolkit_envelope_from_job(job, worker_id="worker", lease_id="lease")

    assert envelope["run_id"] == "caller_run_id"
    assert envelope["tool_call_id"] == "caller_tool_call_id"
    assert envelope["policy_context"]["tenant_id"] == "tenant_worker"


def test_enqueue_probe_runspec_is_explicit(tmp_path: Path) -> None:
    fake = FakeAgentctlWorkerClient(lease_job=None)
    worker = VideoToolkitAgentctlWorker(
        _config(tmp_path),
        client=fake,
    )

    response = enqueue_probe_runspec(worker, tenant_id="tenant_probe")

    request = fake.requests[-1]
    assert request["path"] == "/runspecs/run"
    assert request["body"]["dispatch_mode"] == "enqueue"
    assert request["body"]["backend_id"] == "local"
    assert request["body"]["input_payload"]["toolkit_id"] == "video-editing-toolkit"
    assert runtime_job_id_from_enqueue(response) == "rtjob_enqueued_probe"
    assert response["runtime_job"]["job_id"] == "rtjob_enqueued_probe"
    assert_no_public_path_or_command_leak(request["body"])


def test_live_worker_enqueue_probe_smoke_when_env_is_configured(tmp_path: Path) -> None:
    base_url = os.environ.get("VIDEO_TOOLKIT_AGENTCTL_LIVE_URL")
    token = os.environ.get("VIDEO_TOOLKIT_AGENTCTL_LIVE_TOKEN")
    if not base_url or not token:
        pytest.skip("Set VIDEO_TOOLKIT_AGENTCTL_LIVE_URL and VIDEO_TOOLKIT_AGENTCTL_LIVE_TOKEN for live worker smoke.")

    worker = VideoToolkitAgentctlWorker(
        VideoToolkitWorkerConfig(
            base_url=base_url,
            token=token,
            worker_id="video-toolkit-live-worker-test",
            backend_id="local",
            lease_seconds=30,
            ttl_seconds=60,
            timeout_seconds=5,
            artifact_root=tmp_path / "live-worker-artifacts",
        )
    )
    enqueue_probe_runspec(worker, tenant_id="demo_tenant")
    result = worker.run_once()

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert token not in json.dumps(result, sort_keys=True)


class FakeAgentctlWorkerClient:
    def __init__(self, *, lease_job: dict[str, Any] | None) -> None:
        self.lease_job = lease_job
        self.requests: list[dict[str, Any]] = []

    @property
    def paths(self) -> list[str]:
        return [request["path"] for request in self.requests]

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(body or {})
        self.requests.append({"path": path, "body": payload})
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
                "lease_id": "lease_worker_test" if self.lease_job is not None else None,
                "lease_seconds": payload["lease_seconds"],
                "expired_leases_requeued": 0,
                "job": self.lease_job,
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
        if path == "/runspecs/run":
            return {
                "runspec_id": "runspec_probe",
                "status": "queued",
                "dispatch_mode": payload["dispatch_mode"],
                "runtime_job": {
                    "job_id": "rtjob_enqueued_probe",
                    "backend_id": payload["backend_id"],
                    "backend_kind": "local",
                    "status": "queued",
                    "target_agent": payload["target_agent"],
                },
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


def _timeout_runner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise WorkerLocalExecutionTimeout()


def _cancelling_runner(*_args: Any, cancellation_checker: Any, **_kwargs: Any) -> dict[str, Any]:
    assert cancellation_checker() is True
    raise WorkerLocalExecutionCancelled()


def _unexpected_runner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise AssertionError("runner should not be called")


def _malicious_error_runner(tmp_path: Path) -> Any:
    def runner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            f"failed at {tmp_path / 'private.mp4'} token=secret-token-value "
            "http://download.example/private.mp4"
        )

    return runner


def _config(
    tmp_path: Path,
    *,
    token: str | None = None,
    artifact_base_url: str | None = None,
    allowed_resource_classes: tuple[str, ...] = ("cpu_light",),
    allowed_capabilities: tuple[str, ...] = (),
    max_job_input_bytes: int = 1024,
    max_run_timeout_seconds: int = 120,
    execution_mode: str = "in_process",
    max_attempts: int = 1,
) -> VideoToolkitWorkerConfig:
    return VideoToolkitWorkerConfig(
        base_url="http://agentctl.local",
        token=token,
        worker_id="video-worker-test",
        backend_id="local",
        ttl_seconds=60,
        lease_seconds=30,
        timeout_seconds=5,
        artifact_root=tmp_path / "worker-artifacts",
        artifact_base_url=artifact_base_url or "http://agentctl.local",
        max_artifact_bytes=1024,
        allowed_resource_classes=allowed_resource_classes,
        allowed_capabilities=allowed_capabilities,
        max_job_input_bytes=max_job_input_bytes,
        max_run_timeout_seconds=max_run_timeout_seconds,
        execution_mode=execution_mode,
        max_attempts=max_attempts,
    )


def _leased_job(
    *,
    job_id: str,
    capability: str,
    input_payload: dict[str, Any],
    artifact_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    toolkit_input = {
        "toolkit_id": "video-editing-toolkit",
        "capability": capability,
        "input": input_payload,
        "artifact_refs": artifact_refs or [],
        "policy_context": {
            "tenant_id": "tenant_worker",
            "user_id": "worker_test",
        },
    }
    return {
        "job_id": job_id,
        "source": "runspec",
        "backend_id": "local",
        "backend_kind": "local",
        "status": "leased",
        "target_agent": "video_editing_toolkit_agentctl",
        "tenant": "tenant_worker",
        "trace_id": "trace_worker",
        "attempts": 1,
        "payload": {
            "source": "runspec",
            "runspec_id": "runspec_worker",
            "target_agent": "video_editing_toolkit_agentctl",
            "tenant": "tenant_worker",
            "trace_id": "trace_worker",
            "input_payload": toolkit_input,
        },
        "metadata": {
            "runspec_id": "runspec_worker",
            "dispatch_mode": "enqueue",
        },
    }


def _artifact_ref(*, artifact_id: str, content: bytes) -> dict[str, Any]:
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
