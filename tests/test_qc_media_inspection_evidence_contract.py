"""P1.9 QC media inspection evidence adapter contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.adapters import (
    AdapterContext,
    AdapterRequest,
    AdapterResult,
    AdapterStatus,
    QCAdapter,
    build_p1_experimental_adapter,
    resolve_p1_experimental_route,
    resolve_route,
)
from video_editing_toolkit.adapters.audio_quality import AudioQualityAdapter
from video_editing_toolkit.adapters.ffmpeg import FFmpegAdapter
from video_editing_toolkit.adapters.opencv import OpenCVAdapter
from video_editing_toolkit.adapters.qc import (
    GENERATE_MEDIA_INSPECTION_EVIDENCE,
    PLAN_MEDIA_INSPECTION,
    QC_MEDIA_INSPECTION_EVIDENCE_ARTIFACT_TYPE,
    QC_MEDIA_INSPECTION_EVIDENCE_SCHEMA,
)
from video_editing_toolkit.adapters.routing import CAPABILITY_ROUTES, P1_CAPABILITY_ROUTES
from video_editing_toolkit.resource_guard import ErrorCode
from video_editing_toolkit.storage import LocalArtifactStore


def test_qc_media_inspection_evidence_resolves_through_p1_route_only() -> None:
    route = resolve_p1_experimental_route(GENERATE_MEDIA_INSPECTION_EVIDENCE)
    adapter = build_p1_experimental_adapter(GENERATE_MEDIA_INSPECTION_EVIDENCE)

    assert GENERATE_MEDIA_INSPECTION_EVIDENCE not in CAPABILITY_ROUTES
    assert GENERATE_MEDIA_INSPECTION_EVIDENCE in P1_CAPABILITY_ROUTES
    assert route.adapter_name == QCAdapter.adapter_name
    assert route.adapter_class is QCAdapter
    assert route.queue_topic == "video.qc.media_inspection_evidence"
    assert adapter.adapter_name == "qc"
    assert adapter.supports(GENERATE_MEDIA_INSPECTION_EVIDENCE)

    try:
        resolve_route(GENERATE_MEDIA_INSPECTION_EVIDENCE)
    except ValueError as exc:
        assert "No adapter route registered" in str(exc)
    else:
        raise AssertionError("P1 QC evidence should not resolve through the default P0 route table")


def test_qc_media_inspection_evidence_requires_policy_opt_in(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    result = _run_qc_media_evidence(
        {
            "_artifact_store": artifact_store,
            "_worker_media_path": str(tmp_path / "private" / "source.mp4"),
        }
    )

    assert result.status == AdapterStatus.FAILED
    assert result.error_code == ErrorCode.ARTIFACT_ACCESS_DENIED
    assert result.artifact_refs == ()
    assert_no_public_path_or_command_leak(result.output)
    assert_no_public_path_or_command_leak({"error_message": result.error_message})


def test_qc_media_inspection_plan_remains_plan_only_without_downstream_execution(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any) -> AdapterResult:
        raise AssertionError("plan_media_inspection must not call runtime inspection adapters")

    monkeypatch.setattr(FFmpegAdapter, "invoke", fail_if_called)
    monkeypatch.setattr(AudioQualityAdapter, "invoke", fail_if_called)
    monkeypatch.setattr(OpenCVAdapter, "invoke", fail_if_called)

    result = QCAdapter().handle(
        AdapterRequest(
            context=_context(PLAN_MEDIA_INSPECTION),
            input={
                "_artifact_store": LocalArtifactStore(tmp_path / "artifacts"),
                "_worker_media_path": str(tmp_path / "private" / "source.mp4"),
            },
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.artifact_refs == ()
    plan = result.output["media_inspection_plan"]
    assert plan["summary"]["plan_only"] is True
    assert plan["summary"]["execution_enabled"] is False
    assert all(value == 0 for value in plan["runtime_invocation_counts"].values())
    assert_no_public_path_or_command_leak(result.output)


def test_qc_media_inspection_evidence_writes_partial_artifact_without_leaks(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def probe_success(self: FFmpegAdapter, request: AdapterRequest) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "probe": {
                    "duration_seconds": 1.25,
                    "filename": str(tmp_path / "private" / "source.mp4"),
                    "streams": [{"codec_type": "video", "width": 16, "height": 16}],
                }
            },
        )

    def audio_failure(self: AudioQualityAdapter, request: AdapterRequest) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message=f"ffprobe -i {tmp_path / 'private' / 'source.mp4'} failed with secret token",
        )

    def visual_success(self: OpenCVAdapter, request: AdapterRequest) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "media_kind": "video",
                "quality_summary": {"mean_brightness": 123.0},
                "download_url": "https://download.example/source.mp4?token=secret",
            },
        )

    monkeypatch.setattr(FFmpegAdapter, "invoke", probe_success)
    monkeypatch.setattr(AudioQualityAdapter, "invoke", audio_failure)
    monkeypatch.setattr(OpenCVAdapter, "invoke", visual_success)

    artifact_store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
        signing_secret="signed-evidence-secret",
    )
    result = _run_qc_media_evidence(
        {
            "_artifact_store": artifact_store,
            "_worker_media_path": str(tmp_path / "private" / "source.mp4"),
            "artifact_ref": _source_artifact_ref(),
        },
        policy_context={"allow_p1_qc_media_inspection_execution": True},
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert len(result.artifact_refs) == 1
    artifact_ref = result.artifact_refs[0]
    assert artifact_ref.artifact_type == QC_MEDIA_INSPECTION_EVIDENCE_ARTIFACT_TYPE
    assert "download_url" not in result.output["qc_media_inspection_evidence_artifact_ref"]
    assert "storage_uri" not in result.output["qc_media_inspection_evidence_artifact_ref"]

    evidence = result.output["media_inspection_evidence"]
    assert evidence["schema"] == QC_MEDIA_INSPECTION_EVIDENCE_SCHEMA
    assert evidence["summary"]["status"] == "warning"
    assert evidence["summary"]["inspection_result_count"] == 3
    assert evidence["summary"]["evidence_item_count"] == 2
    assert evidence["summary"]["warning_count"] == 1
    assert {item["check_id"] for item in evidence["inspection_results"]} == {
        "media_probe",
        "audio_quality",
        "visual_quality",
    }
    assert {item["evidence_id"] for item in evidence["evidence_items"]} == {
        "media_probe",
        "visual_quality",
    }

    artifact_path = artifact_store.open_local_path(artifact_ref.artifact_id)
    assert artifact_path is not None
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["schema"] == QC_MEDIA_INSPECTION_EVIDENCE_SCHEMA
    assert artifact_payload["summary"]["status"] == "warning"

    rendered = json.dumps(result.output, sort_keys=True)
    assert "_worker_media_path" not in rendered
    assert "source.mp4" not in rendered
    assert str(tmp_path) not in rendered
    assert "ffprobe -i" not in rendered
    assert "secret" not in rendered
    assert_no_public_path_or_command_leak(result.output)
    assert_no_public_path_or_command_leak(artifact_payload)


def test_qc_media_inspection_evidence_writes_success_artifact(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        FFmpegAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"probe": {"duration_seconds": 1.0, "streams": [{"codec_type": "video"}]}},
        ),
    )
    monkeypatch.setattr(
        AudioQualityAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"quality_summary": {"duration_seconds": 1.0, "has_audio_stream": True}},
        ),
    )
    monkeypatch.setattr(
        OpenCVAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"quality_summary": {"mean_brightness": 100.0}},
        ),
    )

    artifact_store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
        signing_secret="signed-evidence-secret",
    )
    result = _run_qc_media_evidence(
        {
            "_artifact_store": artifact_store,
            "_worker_media_path": str(tmp_path / "private" / "source.mp4"),
        },
        policy_context={"allow_p1_qc_media_inspection_execution": True},
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert len(result.artifact_refs) == 1
    evidence = result.output["media_inspection_evidence"]
    assert evidence["summary"]["status"] == "ready"
    assert evidence["summary"]["inspection_result_count"] == 3
    assert evidence["summary"]["evidence_item_count"] == 0
    assert evidence["summary"]["warning_count"] == 0
    assert_no_public_path_or_command_leak(result.output)


def _run_qc_media_evidence(
    input_payload: dict[str, Any],
    *,
    policy_context: dict[str, Any] | None = None,
) -> AdapterResult:
    return QCAdapter().handle(
        AdapterRequest(
            context=_context(
                GENERATE_MEDIA_INSPECTION_EVIDENCE,
                policy_context=policy_context,
            ),
            input=input_payload,
        )
    )


def _context(
    capability: str,
    *,
    policy_context: dict[str, Any] | None = None,
) -> AdapterContext:
    return AdapterContext(
        tenant_id="demo_tenant",
        project_id="demo_project",
        run_id="run_qc_media_evidence_contract",
        tool_call_id="tool_call_qc_media_evidence_contract",
        capability=capability,
        policy_context=policy_context or {},
    )


def _source_artifact_ref() -> dict[str, Any]:
    return {
        "artifact_id": "artifact_source_public_ref",
        "artifact_type": "source_video",
        "mime_type": "video/mp4",
        "size_bytes": 1234,
        "checksum": "sha256:" + "a" * 64,
        "data_class": "sensitive",
        "retention_policy": "short_lived",
        "storage_uri": "s3://internal/private/source.mp4",
        "download_url": "https://download.example/source.mp4?token=secret",
    }
