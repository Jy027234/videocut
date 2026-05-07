"""P0.2 FFmpeg extract_audio/extract_frames contract checks."""

from __future__ import annotations

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
from video_editing_toolkit.storage import LocalArtifactStore

from conftest import assert_no_public_path_or_command_leak


EXTRACT_AUDIO = "video.asset_ingest.extract_audio"
EXTRACT_FRAMES = "video.asset_ingest.extract_frames"


@pytest.fixture()
def service(tmp_path: Path) -> LocalRunService:
    runtime = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(runtime)
    return runtime


@pytest.fixture()
def tiny_av_artifact(service: LocalRunService, tmp_path: Path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed in this environment")

    media_path = tmp_path / "tiny-av-input.mp4"
    _generate_tiny_av_fixture(media_path)
    return service.artifact_store.put_file(
        source_path=media_path,
        artifact_type="input_video",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        mime_type="video/mp4",
    )


@pytest.mark.parametrize(
    "capability",
    [EXTRACT_AUDIO, EXTRACT_FRAMES],
)
def test_ffmpeg_extract_capabilities_missing_binary_return_stable_unavailable(
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

    response = _run_extract(
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


def test_ffmpeg_extract_audio_outputs_caller_safe_artifact_ref(
    service: LocalRunService,
    tiny_av_artifact,
) -> None:
    response = _run_extract(
        service,
        EXTRACT_AUDIO,
        input_payload={
            "artifact_ref": {"artifact_id": tiny_av_artifact.artifact_id},
            "audio_format": "wav",
        },
        artifact_refs=[tiny_av_artifact],
    )

    _xfail_until_real_extract_lands(response)
    _assert_extract_succeeded_with_artifact(
        response,
        expected_artifact_types={"extracted_audio", "audio_extract", "output_audio"},
        expected_mime_prefixes=("audio/",),
    )


def test_ffmpeg_extract_frames_outputs_caller_safe_artifact_ref(
    service: LocalRunService,
    tiny_av_artifact,
) -> None:
    response = _run_extract(
        service,
        EXTRACT_FRAMES,
        input_payload={
            "artifact_ref": {"artifact_id": tiny_av_artifact.artifact_id},
            "frame_rate": 1,
            "image_format": "jpg",
        },
        artifact_refs=[tiny_av_artifact],
    )

    _xfail_until_real_extract_lands(response)
    _assert_extract_succeeded_with_artifact(
        response,
        expected_artifact_types={"extracted_frames", "frame_extract", "output_frames"},
        expected_mime_prefixes=("image/", "application/zip"),
    )


def _generate_tiny_av_fixture(media_path: Path) -> None:
    timeout_seconds = 15
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
        "-pix_fmt",
        "yuv420p",
        str(media_path),
    ]
    try:
        subprocess.run(command, capture_output=True, check=True, text=True, timeout=timeout_seconds)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg could not generate tiny AV fixture: {exc.stderr.strip()}")
    except subprocess.TimeoutExpired:
        pytest.skip("ffmpeg timed out while generating tiny AV fixture")


def _run_extract(
    service: LocalRunService,
    capability: str,
    *,
    input_payload: dict[str, Any],
    artifact_refs: list[Any],
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


def _xfail_until_real_extract_lands(response: RunResponse) -> None:
    if response.error_code == "adapter.not_implemented":
        pytest.xfail("P0.2 real FFmpeg extract output materialization is pending")


def _assert_extract_succeeded_with_artifact(
    response: RunResponse,
    *,
    expected_artifact_types: set[str],
    expected_mime_prefixes: tuple[str, ...],
) -> None:
    public_payload = response.to_public_dict()
    public_refs = _public_artifact_refs(public_payload)

    assert response.status == RunStatus.SUCCEEDED
    assert response.error_code is None
    assert response.output["adapter_name"] == "ffmpeg"
    assert response.artifact_refs or public_refs
    assert any(ref.get("artifact_type") in expected_artifact_types for ref in public_refs)
    assert any(
        isinstance(ref.get("mime_type"), str)
        and ref["mime_type"].startswith(expected_mime_prefixes)
        for ref in public_refs
    )
    assert_no_public_path_or_command_leak(public_payload)


def _public_artifact_refs(public_payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []

    for ref in public_payload.get("artifact_refs", []):
        if isinstance(ref, dict):
            refs.append(ref)

    output = public_payload.get("output", {})
    if isinstance(output, dict):
        for key in ("artifact_ref", "audio_artifact_ref", "frames_artifact_ref"):
            ref = output.get(key)
            if isinstance(ref, dict):
                refs.append(ref)
        output_refs = output.get("artifact_refs")
        if isinstance(output_refs, list):
            refs.extend(ref for ref in output_refs if isinstance(ref, dict))

    return refs
