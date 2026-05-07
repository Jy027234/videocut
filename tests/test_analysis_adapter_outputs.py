"""P0.3 analysis adapter QA skeleton.

These checks stay tolerant while PySceneDetect/OpenCV land in parallel, but
become real-output assertions in the Docker analysis profile.
"""

from __future__ import annotations

import importlib.util
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


DETECT_SCENES = "video.analysis.detect_scenes"
CHECK_VISUAL_QUALITY = "video.analysis.check_visual_quality"
ANALYZE_FRAMES = "video.analysis.analyze_frames"
ANALYSIS_CAPABILITIES = (DETECT_SCENES, CHECK_VISUAL_QUALITY, ANALYZE_FRAMES)


@pytest.fixture()
def service(tmp_path: Path) -> LocalRunService:
    runtime = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(runtime)
    return runtime


@pytest.fixture()
def tiny_analysis_video_artifact(service: LocalRunService, tmp_path: Path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required to generate the tiny analysis video fixture")

    media_path = tmp_path / "tiny-analysis-input.mp4"
    _generate_tiny_scene_change_video(media_path)
    return service.artifact_store.put_file(
        source_path=media_path,
        artifact_type="input_video",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        mime_type="video/mp4",
    )


@pytest.fixture()
def tiny_analysis_frame_artifact(service: LocalRunService, tmp_path: Path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required to generate the tiny analysis frame fixture")

    frame_path = tmp_path / "tiny-analysis-frame.png"
    _generate_tiny_frame(frame_path)
    return service.artifact_store.put_file(
        source_path=frame_path,
        artifact_type="input_frame",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        mime_type="image/png",
    )


@pytest.mark.parametrize("capability", ANALYSIS_CAPABILITIES)
def test_analysis_capabilities_missing_host_dependencies_are_stable_or_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    dependency = "scenedetect" if capability == DETECT_SCENES else "cv2"
    if importlib.util.find_spec(dependency) is not None:
        pytest.skip(f"{dependency} is installed; missing-dependency path is not active")

    empty_bin_dir = tmp_path / "empty-bin"
    empty_bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin_dir))

    runtime = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(runtime)
    artifact = runtime.artifact_store.put_bytes(
        content=b"dependency-check-input",
        artifact_type="input_video" if capability == DETECT_SCENES else "input_frame",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        filename="dependency-check.bin",
        mime_type="video/mp4" if capability == DETECT_SCENES else "image/png",
    )
    response = _run_analysis(
        runtime,
        capability,
        input_payload={"artifact_ref": {"artifact_id": artifact.artifact_id}},
        artifact_refs=[artifact],
    )

    assert response.status == RunStatus.FAILED
    assert response.output["adapter_name"] in {"pyscenedetect", "opencv"}
    assert_no_public_path_or_command_leak(response.output)
    assert_no_public_path_or_command_leak(response.to_public_dict())
    if response.error_code == "adapter.not_implemented":
        pytest.xfail(f"{capability} is still a registered placeholder")
    assert response.error_code == "adapter.unavailable"


def test_analysis_profile_detect_scenes_returns_caller_safe_scene_output(
    service: LocalRunService,
    tiny_analysis_video_artifact,
) -> None:
    _require_analysis_profile("detect_scenes")

    response = _run_analysis(
        service,
        DETECT_SCENES,
        input_payload={
            "artifact_ref": {"artifact_id": tiny_analysis_video_artifact.artifact_id},
            "threshold": 5.0,
            "min_scene_len": 1,
        },
        artifact_refs=[tiny_analysis_video_artifact],
    )

    _xfail_until_analysis_adapter_lands(response)
    _assert_successful_analysis_response(response, expected_adapter="pyscenedetect")
    scenes = _first_list(response.output, ("scenes", "scene_list", "detections"))
    assert scenes, "detect_scenes should return at least one scene for the generated hard-cut video"
    assert all(isinstance(scene, dict) for scene in scenes)
    assert any(
        set(scene).intersection({"start_seconds", "start_time", "start_frame"})
        and set(scene).intersection({"end_seconds", "end_time", "end_frame"})
        for scene in scenes
    )


def test_analysis_profile_check_visual_quality_returns_caller_safe_metrics(
    service: LocalRunService,
    tiny_analysis_frame_artifact,
) -> None:
    _require_analysis_profile("check_visual_quality")

    response = _run_analysis(
        service,
        CHECK_VISUAL_QUALITY,
        input_payload={"artifact_ref": {"artifact_id": tiny_analysis_frame_artifact.artifact_id}},
        artifact_refs=[tiny_analysis_frame_artifact],
    )

    _xfail_until_analysis_adapter_lands(response)
    _assert_successful_analysis_response(response, expected_adapter="opencv")
    assert _has_any_key(
        response.output,
        {
            "quality_score",
            "quality_summary",
            "sharpness",
            "brightness",
            "contrast",
            "sampled_frame_count",
            "metrics",
            "warnings",
            "is_usable",
        },
    )


def test_analysis_profile_analyze_frames_returns_caller_safe_frame_output(
    service: LocalRunService,
    tiny_analysis_frame_artifact,
) -> None:
    _require_analysis_profile("analyze_frames")

    response = _run_analysis(
        service,
        ANALYZE_FRAMES,
        input_payload={"artifact_ref": {"artifact_id": tiny_analysis_frame_artifact.artifact_id}},
        artifact_refs=[tiny_analysis_frame_artifact],
    )

    _xfail_until_analysis_adapter_lands(response)
    _assert_successful_analysis_response(response, expected_adapter="opencv")
    assert _has_any_key(
        response.output,
        {
            "frames",
            "frame_count",
            "analysis",
            "features",
            "dominant_colors",
            "objects",
            "summary",
        },
    )


def _run_analysis(
    service: LocalRunService,
    capability: str,
    *,
    input_payload: dict[str, Any],
    artifact_refs: list[Any] | None = None,
) -> RunResponse:
    request = RunRequest(
        toolkit_id="video-editing-toolkit",
        capability=capability,
        input=input_payload,
        artifact_refs=artifact_refs or [],
    )
    service.submit(request)
    response = service.process_next()
    assert response is not None
    return response


def _generate_tiny_scene_change_video(media_path: Path) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:size=160x90:rate=5:duration=1.2",
        "-f",
        "lavfi",
        "-i",
        "color=c=white:size=160x90:rate=5:duration=1.2",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p",
        str(media_path),
    ]
    _run_fixture_ffmpeg(command, "tiny analysis video")


def _generate_tiny_frame(frame_path: Path) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=160x90:rate=1:duration=1",
        "-frames:v",
        "1",
        str(frame_path),
    ]
    _run_fixture_ffmpeg(command, "tiny analysis frame")


def _run_fixture_ffmpeg(command: list[str], fixture_name: str) -> None:
    try:
        subprocess.run(command, capture_output=True, check=True, text=True, timeout=15)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"ffmpeg could not generate {fixture_name}: {exc.stderr.strip()}")
    except subprocess.TimeoutExpired:
        pytest.skip(f"ffmpeg timed out while generating {fixture_name}")


def _require_analysis_profile(capability_name: str) -> None:
    import os

    if os.environ.get("VIDEO_TOOLKIT_WORKER_PROFILE") != "analysis":
        pytest.skip(f"{capability_name} real-output check runs in the analysis Docker profile")


def _xfail_until_analysis_adapter_lands(response: RunResponse) -> None:
    if response.error_code == "adapter.not_implemented":
        pytest.xfail("P0.3 real PySceneDetect/OpenCV analysis implementation is pending")
    if response.error_code == "adapter.unavailable":
        pytest.xfail("P0.3 analysis dependencies or artifact resolution are not wired yet")


def _assert_successful_analysis_response(response: RunResponse, *, expected_adapter: str) -> None:
    public_payload = response.to_public_dict()
    assert response.status == RunStatus.SUCCEEDED
    assert response.error_code is None
    assert response.output["adapter_name"] == expected_adapter
    assert response.output["artifact_policy"] == "artifact_ref_only"
    assert_no_public_path_or_command_leak(public_payload)


def _first_list(output: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = output.get(key)
        if isinstance(value, list):
            return value
    return []


def _has_any_key(value: Any, expected_keys: set[str]) -> bool:
    if isinstance(value, dict):
        if expected_keys.intersection(value):
            return True
        return any(_has_any_key(child, expected_keys) for child in value.values())
    if isinstance(value, list):
        return any(_has_any_key(child, expected_keys) for child in value)
    return False
