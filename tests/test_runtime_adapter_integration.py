"""P0 runtime-to-adapter integration checks."""

from __future__ import annotations

import shutil
import struct
import wave
from pathlib import Path
from typing import Any

import pytest

from video_editing_toolkit.adapters import CAPABILITY_ROUTES
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
