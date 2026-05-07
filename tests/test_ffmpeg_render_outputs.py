"""P0.7 FFmpeg normalize/render materialization contract checks."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from video_editing_toolkit.runtime import (
    LocalRunService,
    RunRequest,
    RunResponse,
    RunStatus,
    register_p0_adapter_handlers,
)
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from conftest import assert_no_public_path_or_command_leak


NORMALIZE_ASSET = "video.asset_ingest.normalize_asset"
RENDER_PREVIEW = "video.render.render_preview"
RENDER_FINAL = "video.render.render_final"
FFMPEG_RENDER_CAPABILITIES = (NORMALIZE_ASSET, RENDER_PREVIEW, RENDER_FINAL)


@pytest.fixture()
def service(tmp_path: Path) -> LocalRunService:
    runtime = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(runtime)
    return runtime


@pytest.fixture()
def tiny_render_artifact(service: LocalRunService, tmp_path: Path) -> ArtifactRef:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are not installed in this environment")

    media_path = tmp_path / "tiny-render-input.mp4"
    _generate_tiny_av_fixture(media_path)
    return service.artifact_store.put_file(
        source_path=media_path,
        artifact_type="input_video",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        mime_type="video/mp4",
    )


@pytest.mark.parametrize("capability", FFMPEG_RENDER_CAPABILITIES)
def test_ffmpeg_render_capabilities_missing_binary_return_stable_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    empty_bin_dir = tmp_path / "empty-bin"
    empty_bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin_dir))

    runtime = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(runtime)
    artifact = runtime.artifact_store.put_bytes(
        content=b"dependency-check-input",
        artifact_type="input_video",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename="dependency-check.mp4",
        mime_type="video/mp4",
    )

    response = _run_ffmpeg_capability(
        runtime,
        capability,
        input_payload={"artifact_ref": {"artifact_id": artifact.artifact_id}},
        artifact_refs=[artifact],
    )

    assert response.status == RunStatus.FAILED
    assert response.error_code == "adapter.unavailable"
    assert response.output["adapter_name"] == "ffmpeg"
    assert_no_public_path_or_command_leak(response.output)
    assert_no_public_path_or_command_leak(response.to_public_dict())


@pytest.mark.parametrize(
    ("capability", "extra_input", "expected_artifact_type"),
    [
        (NORMALIZE_ASSET, {}, "normalized_video"),
        (
            RENDER_PREVIEW,
            {"preview_height": 180, "max_duration_seconds": 1.0},
            "preview_video",
        ),
        (RENDER_FINAL, {}, "final_render"),
    ],
)
def test_ffmpeg_render_capabilities_output_real_caller_safe_mp4(
    service: LocalRunService,
    tiny_render_artifact: ArtifactRef,
    capability: str,
    extra_input: dict[str, Any],
    expected_artifact_type: str,
) -> None:
    input_payload = {
        "artifact_ref": {"artifact_id": tiny_render_artifact.artifact_id},
        **extra_input,
    }
    response = _run_ffmpeg_capability(
        service,
        capability,
        input_payload=input_payload,
        artifact_refs=[tiny_render_artifact],
    )

    public_payload = response.to_public_dict()
    assert response.status == RunStatus.SUCCEEDED
    assert response.error_code is None
    assert response.output["adapter_name"] == "ffmpeg"
    assert_no_public_path_or_command_leak(public_payload)

    artifact_ref = _single_artifact_ref(response, expected_artifact_type)
    assert artifact_ref.mime_type == "video/mp4"
    assert artifact_ref.size_bytes > 0
    assert any(
        ref.get("artifact_type") == expected_artifact_type
        and ref.get("mime_type") == "video/mp4"
        for ref in _public_artifact_refs(public_payload)
    )

    artifact_path = service.artifact_store.open_local_path(artifact_ref.artifact_id)
    assert artifact_path is not None
    _assert_probe_sees_video_mp4(artifact_path)


def _generate_tiny_av_fixture(media_path: Path) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=160x90:rate=5:duration=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=8000:duration=1",
        "-shortest",
        "-c:v",
        "mpeg4",
        "-q:v",
        "5",
        "-c:a",
        "aac",
        "-pix_fmt",
        "yuv420p",
        str(media_path),
    ]
    try:
        subprocess.run(command, capture_output=True, check=True, text=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg could not generate tiny render fixture: {exc.stderr.strip()}")
    except subprocess.TimeoutExpired:
        pytest.skip("ffmpeg timed out while generating tiny render fixture")


def _run_ffmpeg_capability(
    service: LocalRunService,
    capability: str,
    *,
    input_payload: dict[str, Any],
    artifact_refs: list[ArtifactRef],
) -> RunResponse:
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability=capability,
        input=input_payload,
        artifact_refs=artifact_refs,
    )
    service.submit(request)
    response = service.process_next()
    assert response is not None
    return response


def _single_artifact_ref(response: RunResponse, artifact_type: str) -> ArtifactRef:
    refs = [ref for ref in response.artifact_refs if ref.artifact_type == artifact_type]
    assert len(refs) == 1
    return refs[0]


def _assert_probe_sees_video_mp4(media_path: Path) -> None:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(media_path),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=15,
    )
    probe = json.loads(completed.stdout)
    assert any(
        stream.get("codec_type") == "video"
        for stream in probe.get("streams", [])
        if isinstance(stream, dict)
    )
    format_name = probe.get("format", {}).get("format_name", "")
    assert "mp4" in format_name or "mov" in format_name


def _public_artifact_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if {"artifact_id", "artifact_type", "checksum"}.issubset(value):
            refs.append(value)
        for child in value.values():
            refs.extend(_public_artifact_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_public_artifact_refs(child))
    return refs
