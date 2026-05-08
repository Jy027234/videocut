"""P0 retry scheduling and local usage accounting contracts."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.runtime.models import RunRequest, RunResponse, RunStatus
from video_editing_toolkit.runtime.queue import InMemoryLocalQueue
from video_editing_toolkit.runtime.service import LocalRunService
from video_editing_toolkit.storage import LocalArtifactStore


def test_retryable_failure_requeues_with_stable_backoff_and_usage(tmp_path: Path) -> None:
    service = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    input_ref = service.artifact_store.put_bytes(
        content=b"input-bytes",
        artifact_type="input_video",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename="input.mp4",
        mime_type="video/mp4",
    )
    calls = {"count": 0}

    def flaky_handler(request: RunRequest, artifact_store: LocalArtifactStore) -> RunResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            return RunResponse(
                run_id=request.run_id,
                tool_call_id=request.tool_call_id,
                status=RunStatus.FAILED,
                usage_metrics={"resource_class": "cpu_light"},
                trace_ref=request.trace_ref,
                error_code="internal.error",
                error_message="temporary failure",
            )

        output_ref = artifact_store.put_bytes(
            content=b"output-bytes",
            artifact_type="analysis_json",
            owner_tenant_id=request.policy_context.tenant_id,
            created_by_run_id=request.run_id,
            filename="output.json",
            mime_type="application/json",
        )
        return RunResponse(
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            status=RunStatus.SUCCEEDED,
            output={"ok": True},
            artifact_refs=[output_ref],
            usage_metrics={
                "resource_class": "cpu_light",
                "output_bytes": output_ref.size_bytes,
            },
            trace_ref=request.trace_ref,
        )

    service.register_handler("video-editing-toolkit", "video.test.flaky", flaky_handler)
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.test.flaky",
        input={},
        artifact_refs=[input_ref],
        max_attempts=2,
    )

    queued = service.submit(request)
    first = service.process_next()
    second = service.process_next()

    assert queued.retry["attempt"] == 0
    assert queued.retry["max_attempts"] == 2
    assert first is not None
    assert first.status == RunStatus.QUEUED
    assert first.retry["attempt"] == 1
    assert first.retry["retryable_failure"] is True
    assert first.retry["scheduled"] is True
    assert first.retry["next_retry_delay_seconds"] == 1.0
    assert first.retry["backoff_schedule_seconds"] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert first.usage_summary["status"] == "queued"
    assert second is not None
    assert second.status == RunStatus.SUCCEEDED
    assert second.retry["attempt"] == 2
    assert second.retry["terminal_reason"] == "succeeded"
    assert second.usage_summary["billing_ready"] is True
    assert second.usage_summary["billing_mode"] == "local_preview_no_charge"
    assert second.usage_summary["charged"] is False
    assert second.usage_summary["input_bytes"] == input_ref.size_bytes
    assert second.usage_summary["output_bytes"] == second.artifact_refs[0].size_bytes
    assert second.usage_summary["artifact_counts"] == {
        "input": 1,
        "output": 1,
        "total": 2,
    }
    assert second.usage_summary["capability_usage"]["video.test.flaky"]["attempts"] == 2
    assert second.usage_summary["resource_usage"]["cpu_light"]["runs"] == 1
    assert_no_public_path_or_command_leak(second.to_public_dict())


def test_terminal_failure_does_not_retry_even_with_budget(tmp_path: Path) -> None:
    service = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))

    def invalid_handler(request: RunRequest, artifact_store: LocalArtifactStore) -> RunResponse:
        return RunResponse(
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            status=RunStatus.FAILED,
            usage_metrics={"resource_class": "cpu_light"},
            trace_ref=request.trace_ref,
            error_code="request.invalid",
            error_message="invalid request",
        )

    service.register_handler("video-editing-toolkit", "video.test.invalid", invalid_handler)
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.test.invalid",
        input={},
        max_attempts=3,
    )

    service.submit(request)
    processed = service.process_next()

    assert processed is not None
    assert processed.status == RunStatus.FAILED
    assert processed.retry["attempt"] == 1
    assert processed.retry["retryable_failure"] is False
    assert processed.retry["scheduled"] is False
    assert processed.retry["terminal_reason"] == "terminal_error"
    assert service.process_next() is None


def test_cancelled_run_never_schedules_retry(tmp_path: Path) -> None:
    service = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.test.cancelled",
        input={},
        max_attempts=3,
    )

    service.submit(request)
    cancelled = service.cancel(request.run_id)

    assert cancelled is not None
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.retry["attempt"] == 0
    assert cancelled.retry["scheduled"] is False
    assert cancelled.retry["terminal_reason"] == "cancelled"
    assert service.process_next() is None


def test_local_queue_snapshot_roundtrip(tmp_path: Path) -> None:
    queue = InMemoryLocalQueue()
    queue.enqueue("run_keep")
    queue.enqueue("run_cancelled")
    assert queue.cancel("run_cancelled") is True

    snapshot = queue.snapshot()
    snapshot_path = tmp_path / "queue-snapshot.json"
    queue.save_snapshot(snapshot_path)
    loaded = InMemoryLocalQueue.load_snapshot(snapshot_path)

    assert snapshot["schema"] == "video_editing_toolkit.runtime.local_queue_snapshot.v0"
    assert snapshot["queued_run_ids"] == ["run_keep"]
    assert snapshot["cancelled_run_ids"] == ["run_cancelled"]
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == snapshot
    assert loaded.dequeue() == "run_keep"
    assert loaded.dequeue() is None
