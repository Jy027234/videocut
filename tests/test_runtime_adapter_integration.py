"""P0 runtime-to-adapter integration checks."""

from __future__ import annotations

import json
import shutil
import struct
import wave
from pathlib import Path
from typing import Any

import pytest

from video_editing_toolkit.adapters import CAPABILITY_ROUTES, P1_CAPABILITY_ROUTES
from video_editing_toolkit.adapters.audio_quality import AudioQualityAdapter
from video_editing_toolkit.adapters.base import AdapterResult, AdapterStatus
from video_editing_toolkit.adapters.ffmpeg import FFmpegAdapter
from video_editing_toolkit.adapters.opencv import OpenCVAdapter
from video_editing_toolkit.adapters.qc import (
    GENERATE_MEDIA_INSPECTION_EVIDENCE,
    QC_MEDIA_INSPECTION_EVIDENCE_SCHEMA,
)
from video_editing_toolkit.agentctl import run_agentctl
from video_editing_toolkit.resource_guard import ErrorCode
from video_editing_toolkit.runtime import (
    LocalRunService,
    RunRequest,
    RunStatus,
    register_p0_adapter_handlers,
)
from video_editing_toolkit.storage import LocalArtifactStore

from conftest import FIXTURES_DIR, MANIFESTS_DIR, assert_no_public_path_or_command_leak, load_json


@pytest.fixture()
def tiny_probe_wav_path(tmp_path: Path) -> Path:
    """Generate a tiny valid WAV with only Python's standard library."""

    wav_path = tmp_path / "tiny-probe-input.wav"
    sample_rate = 8000
    sample_count = 800
    amplitude = 1000

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(sample_count):
            sample = amplitude if index % 2 == 0 else -amplitude
            wav_file.writeframes(struct.pack("<h", sample))

    return wav_path


def test_every_enabled_manifest_capability_has_a_p0_route() -> None:
    manifest = load_json(MANIFESTS_DIR / "video-editing-toolkit.p0.manifest.json")
    enabled_capabilities = {
        capability["capability"]
        for capability in manifest["capabilities"]
        if capability.get("status") == "enabled"
    }

    assert enabled_capabilities == set(CAPABILITY_ROUTES)


def test_agentctl_rejects_p1_experimental_capabilities_by_default(tmp_path: Path) -> None:
    token = "artifact-secret-token"

    for capability in P1_CAPABILITY_ROUTES:
        artifact_root = tmp_path / capability.replace(".", "_")
        response = run_agentctl(
            {
                "toolkit_id": "video-editing-toolkit",
                "capability": capability,
                "input": {"project_id": "proj_p1_reject"},
                "artifact_refs": [
                    {
                        "artifact_id": f"artifact_{capability.replace('.', '_')}",
                        "artifact_type": "source_video",
                        "mime_type": "video/mp4",
                        "size_bytes": 123,
                        "checksum": "sha256:" + "a" * 64,
                        "download_url": f"/toolkit-artifacts/source/bytes?sat={token}",
                        "storage_uri": "s3://internal/private/source.mov",
                    }
                ],
                "policy_context": {
                    "tenant_id": "tenant_p1_reject",
                    "user_id": "user_p1_reject",
                },
            },
            artifact_root=artifact_root,
        )
        rendered = json.dumps(response, sort_keys=True)

        assert response["ok"] is False, capability
        assert response["processed"]["status"] == "failed", capability
        assert response["processed"]["error_code"] == "handler_not_registered", capability
        assert response["processed"]["artifact_refs"] == [], capability
        assert response["processed"]["usage_summary"]["artifact_counts"]["output"] == 0
        assert not any(artifact_root.iterdir()), capability
        assert token not in rendered
        assert "download_url" not in rendered
        assert "storage_uri" not in rendered
        assert_no_public_path_or_command_leak(response)


def test_agentctl_rejects_p1_qc_evidence_by_default_without_materializing(tmp_path: Path) -> None:
    artifact_root = tmp_path / "default-p1-qc-reject"
    response = run_agentctl(
        {
            "toolkit_id": "video-editing-toolkit",
            "capability": GENERATE_MEDIA_INSPECTION_EVIDENCE,
            "input": {
                "project_id": "proj_p1_qc_reject",
                "artifact_ref": {"artifact_id": "artifact_p1_qc_reject"},
            },
            "artifact_refs": [
                {
                    "artifact_id": "artifact_p1_qc_reject",
                    "artifact_type": "source_video",
                    "mime_type": "video/mp4",
                    "size_bytes": 12,
                    "checksum": "sha256:" + "b" * 64,
                    "download_url": "/local/artifacts/private/source.mp4",
                    "storage_uri": "s3://internal/private/source.mp4",
                }
            ],
        },
        artifact_root=artifact_root,
    )

    assert response["ok"] is False
    assert response["processed"]["status"] == "failed"
    assert response["processed"]["error_code"] == "handler_not_registered"
    assert response["processed"]["artifact_refs"] == []
    assert not artifact_root.exists() or not any(artifact_root.iterdir())
    assert_no_public_path_or_command_leak(response)


def test_agentctl_allowed_p1_qc_evidence_still_requires_request_policy_opt_in(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any) -> AdapterResult:
        raise AssertionError("QC evidence must fail before downstream inspection adapters")

    monkeypatch.setattr(FFmpegAdapter, "invoke", fail_if_called)
    monkeypatch.setattr(AudioQualityAdapter, "invoke", fail_if_called)
    monkeypatch.setattr(OpenCVAdapter, "invoke", fail_if_called)

    artifact_root = tmp_path / "allowed-p1-qc-no-policy"
    artifact_id = "artifact_allowed_p1_qc_no_policy"
    tenant_id = "tenant_allowed_p1_qc_no_policy"
    LocalArtifactStore(artifact_root).put_bytes(
        content=b"pre-materialized source bytes",
        artifact_id=artifact_id,
        artifact_type="source_video",
        owner_tenant_id=tenant_id,
        created_by_run_id="fixture_source",
        filename="source.mp4",
        mime_type="video/mp4",
    )

    response = run_agentctl(
        {
            "toolkit_id": "video-editing-toolkit",
            "capability": GENERATE_MEDIA_INSPECTION_EVIDENCE,
            "input": {
                "project_id": "proj_allowed_p1_qc_no_policy",
                "artifact_ref": {"artifact_id": artifact_id},
            },
            "artifact_refs": [
                {
                    "artifact_id": artifact_id,
                    "artifact_type": "source_video",
                    "mime_type": "video/mp4",
                    "size_bytes": 12,
                    "checksum": "sha256:" + "e" * 64,
                }
            ],
            "policy_context": {
                "tenant_id": tenant_id,
                "user_id": "user_allowed_p1_qc_no_policy",
            },
        },
        artifact_root=artifact_root,
        allowed_p1_capabilities=(GENERATE_MEDIA_INSPECTION_EVIDENCE,),
    )

    assert response["ok"] is False
    assert response["processed"]["status"] == "failed"
    assert response["processed"]["error_code"] == "artifact_ref.access_denied"
    assert response["processed"]["artifact_refs"] == []
    assert_no_public_path_or_command_leak(response)


def test_agentctl_allowed_p1_qc_evidence_registers_and_executes_local_runner(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "allowed-p1-qc-evidence"
    artifact_id = "artifact_allowed_p1_qc_source"
    tenant_id = "tenant_allowed_p1_qc"
    LocalArtifactStore(artifact_root).put_bytes(
        content=b"pre-materialized source bytes",
        artifact_id=artifact_id,
        artifact_type="source_video",
        owner_tenant_id=tenant_id,
        created_by_run_id="fixture_source",
        filename="source.mp4",
        mime_type="video/mp4",
    )

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
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message="audio fixture unavailable",
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

    response = run_agentctl(
        {
            "toolkit_id": "video-editing-toolkit",
            "capability": GENERATE_MEDIA_INSPECTION_EVIDENCE,
            "input": {
                "project_id": "proj_allowed_p1_qc",
                "artifact_ref": {"artifact_id": artifact_id},
            },
            "artifact_refs": [
                {
                    "artifact_id": artifact_id,
                    "artifact_type": "source_video",
                    "mime_type": "video/mp4",
                    "size_bytes": 12,
                    "checksum": "sha256:" + "c" * 64,
                    "storage_uri": "s3://internal/private/source.mp4",
                }
            ],
            "policy_context": {
                "tenant_id": tenant_id,
                "user_id": "user_allowed_p1_qc",
                "allow_p1_qc_media_inspection_execution": True,
            },
        },
        artifact_root=artifact_root,
        allowed_p1_capabilities=(GENERATE_MEDIA_INSPECTION_EVIDENCE,),
    )

    output = response["processed"]["output"]
    evidence = output["media_inspection_evidence"]
    assert response["ok"] is True
    assert response["processed"]["status"] == "succeeded"
    assert output["adapter_name"] == "qc"
    assert evidence["schema"] == QC_MEDIA_INSPECTION_EVIDENCE_SCHEMA
    assert evidence["summary"]["inspection_result_count"] == 3
    assert output["qc_media_inspection_evidence_artifact_ref"]["artifact_type"] == "qc_media_inspection_evidence_json"
    assert len(response["processed"]["artifact_refs"]) == 1
    assert_no_public_path_or_command_leak(response)


def test_local_runtime_processes_registered_project_edit_adapter(tmp_path) -> None:
    service = LocalRunService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts")
    )
    register_p0_adapter_handlers(service)

    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.project_edit.inspect_assets",
        input={"project_id": "proj_demo_0001"},
    )
    queued = service.submit(request)
    processed = service.process_next()

    assert queued.status == RunStatus.QUEUED
    assert processed is not None
    assert processed.status == RunStatus.SUCCEEDED
    assert processed.error_code is None
    assert processed.output["adapter_name"] == "project_edit"
    assert processed.output["queue_topic"] == "video.project_edit"
    assert processed.output["asset_count"] == 0
    assert processed.trace_ref == f"local_trace:{request.run_id}"
    assert processed.retry["attempt"] == 1
    assert processed.retry["terminal_reason"] == "succeeded"
    assert processed.usage_summary["billing_mode"] == "local_preview_no_charge"
    assert processed.usage_summary["capability_usage"][request.capability]["runs"] == 1


def test_ffmpeg_probe_media_succeeds_with_minimal_wav_when_ffprobe_is_available(
    tmp_path,
    tiny_probe_wav_path: Path,
) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe is not installed in this environment")

    service = LocalRunService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts")
    )
    register_p0_adapter_handlers(service)
    artifact_ref = service.artifact_store.put_file(
        source_path=tiny_probe_wav_path,
        artifact_type="input_audio",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        mime_type="audio/wav",
    )

    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.asset_ingest.probe_media",
        input={"artifact_ref": {"artifact_id": artifact_ref.artifact_id}},
        artifact_refs=[artifact_ref],
    )
    service.submit(request)
    processed = service.process_next()

    assert processed is not None
    assert processed.status == RunStatus.SUCCEEDED
    assert processed.error_code is None
    assert processed.output["adapter_name"] == "ffmpeg"
    assert processed.output["queue_topic"] == "video.asset.probe"
    assert processed.output["probe"]["streams"]

    public_payload = processed.to_public_dict()
    assert "filename" not in _json_keys(public_payload["output"])
    assert "tiny-probe-input.wav" not in str(public_payload["output"])
    assert_no_public_path_or_command_leak(public_payload)


def test_ffmpeg_missing_binary_returns_stable_unavailable_or_placeholder_error(
    tmp_path,
    monkeypatch,
) -> None:
    empty_bin_dir = tmp_path / "empty-bin"
    empty_bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin_dir))

    service = LocalRunService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts")
    )
    register_p0_adapter_handlers(service)
    artifact_ref = service.artifact_store.put_bytes(
        content=b"dependency-check-input",
        artifact_type="input_video",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename="dependency-check.mp4",
        mime_type="video/mp4",
    )

    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.asset_ingest.probe_media",
        input={"artifact_ref": {"artifact_id": artifact_ref.artifact_id}},
        artifact_refs=[artifact_ref],
    )
    service.submit(request)
    processed = service.process_next()

    assert processed is not None
    assert processed.status == RunStatus.FAILED
    assert processed.error_code == "adapter.unavailable"
    assert processed.output["adapter_name"] == "ffmpeg"
    assert_no_public_path_or_command_leak(processed.output)

    public_payload = processed.to_public_dict()
    assert "filename" not in _json_keys(public_payload["output"])
    assert_no_public_path_or_command_leak(public_payload["output"])


@pytest.mark.parametrize(
    ("fixture_path", "case_name"),
    [
        (FIXTURES_DIR / "timeline_patch" / "valid" / "add_clip_with_preview.json", "valid_patch"),
        (FIXTURES_DIR / "timeline_patch" / "invalid" / "script_injection.json", "script_injection"),
        (FIXTURES_DIR / "timeline_patch" / "invalid" / "missing_base_version.json", "missing_base_version"),
    ],
)
def test_project_edit_timeline_patch_cases_return_current_stable_result(
    tmp_path,
    fixture_path,
    case_name,
) -> None:
    payload = load_json(fixture_path)
    service = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(service)
    _create_demo_project(service)

    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.project_edit.apply_timeline_patch",
        input=payload["request"],
    )
    service.submit(request)
    processed = service.process_next()

    assert processed is not None, case_name
    assert processed.output["adapter_name"] == "project_edit"
    assert processed.output["queue_topic"] == "video.project_edit"
    assert_no_public_path_or_command_leak(processed.output)

    if case_name == "valid_patch":
        assert processed.status == RunStatus.SUCCEEDED
        assert processed.error_code is None
        assert processed.output["project_id"] == payload["request"]["project_id"]
        assert processed.output["timeline_summary"]["duration_seconds"] == 12.5
        assert "preview_artifact_ref" in processed.output
    else:
        assert processed.status == RunStatus.FAILED
        assert processed.error_code == "request.invalid"
        assert processed.output["stable_error_code"] == payload["expected_error_code"]


def _create_demo_project(service: LocalRunService) -> None:
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability="video.project_edit.create_project",
        input={"project_id": "proj_demo_0001"},
    )
    service.submit(request)
    response = service.process_next()
    assert response is not None
    assert response.status == RunStatus.SUCCEEDED


def _json_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_json_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_json_keys(child))
        return keys
    return set()
