"""Repeatable P1 QC smoke runner contract checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from video_editing_toolkit.adapters.audio_quality import AudioQualityAdapter
from video_editing_toolkit.adapters.base import (
    AdapterContext,
    AdapterRequest,
    AdapterResult,
    AdapterStatus,
)
from video_editing_toolkit.adapters.ffmpeg import FFmpegAdapter
from video_editing_toolkit.adapters.opencv import CHECK_VISUAL_QUALITY, OpenCVAdapter
from video_editing_toolkit.adapters.qc import GENERATE_MEDIA_INSPECTION_EVIDENCE
from video_editing_toolkit.p1_qc_smoke import main, run_p1_qc_evidence_smoke

from conftest import assert_no_public_path_or_command_leak


def test_p1_qc_smoke_runs_controlled_local_evidence_loop(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _patch_successful_inspection_adapters(monkeypatch)
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"not a real mp4; downstream adapters are mocked")
    result_json = tmp_path / "qc-smoke-result.json"

    summary = run_p1_qc_evidence_smoke(
        input_video=source_path,
        artifact_root=tmp_path / "artifacts",
        result_json=result_json,
        tenant_id="tenant_p1_qc_smoke_test",
        user_id="user_p1_qc_smoke_test",
        project_id="proj_p1_qc_smoke_test",
        frame_limit=3,
    )

    assert summary["ok"] is True
    assert summary["status"] == "succeeded"
    assert summary["capability"] == GENERATE_MEDIA_INSPECTION_EVIDENCE
    assert summary["p1_controls"] == {
        "allowed_p1_capabilities": [GENERATE_MEDIA_INSPECTION_EVIDENCE],
        "policy_opt_in": True,
        "static_ffmpeg_requested": False,
        "static_ffmpeg_env_enabled": False,
    }
    assert summary["input"]["frame_limit"] == 3
    assert summary["evidence"]["summary"]["status"] == "ready"
    assert summary["evidence"]["summary"]["inspection_result_count"] == 3
    assert [item["check_id"] for item in summary["evidence"]["inspection_results"]] == [
        "media_probe",
        "audio_quality",
        "visual_quality",
    ]
    assert (
        summary["artifacts"]["qc_media_inspection_evidence_artifact_ref"]["artifact_type"]
        == "qc_media_inspection_evidence_json"
    )
    assert summary["artifacts"]["output_artifact_count"] == 1
    assert summary["result_json"] == {"written": True, "filename": result_json.name}

    written = json.loads(result_json.read_text(encoding="utf-8"))
    assert written["schema"] == "video_editing_toolkit.p1_qc_evidence_smoke_result.v0"
    assert written["smoke_summary"] == summary
    assert written["agentctl_response"]["ok"] is True
    assert_no_public_path_or_command_leak(summary)
    assert_no_public_path_or_command_leak(written)
    rendered = json.dumps(written, ensure_ascii=False, sort_keys=True)
    assert str(tmp_path) not in rendered
    assert "storage_uri" not in rendered


def test_p1_qc_smoke_cli_static_ffmpeg_opt_in_is_scoped(
    monkeypatch: Any,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_successful_inspection_adapters(monkeypatch)
    monkeypatch.delenv("VIDEO_TOOLKIT_USE_STATIC_FFMPEG", raising=False)
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")

    exit_code = main(
        [
            "--input-video",
            str(source_path),
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--use-static-ffmpeg",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["ok"] is True
    assert summary["p1_controls"]["static_ffmpeg_requested"] is True
    assert summary["p1_controls"]["static_ffmpeg_env_enabled"] is True
    assert "VIDEO_TOOLKIT_USE_STATIC_FFMPEG" not in os.environ
    assert_no_public_path_or_command_leak(summary)
    assert "storage_uri" not in json.dumps(summary, ensure_ascii=False, sort_keys=True)


def test_p1_qc_smoke_rejects_missing_input_without_leaking_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_path = tmp_path / "missing.mp4"

    exit_code = main(["--input-video", str(missing_path)])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert summary["ok"] is False
    assert summary["error_code"] == "p1_qc_smoke.invalid_request"
    assert summary["error_message"] == "input_video must point to an existing file."
    assert str(missing_path) not in json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert_no_public_path_or_command_leak(summary)


def test_p1_qc_smoke_rejects_existing_artifact_id_with_different_content(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _patch_successful_inspection_adapters(monkeypatch)
    artifact_root = tmp_path / "artifacts"
    first_source = tmp_path / "first.mp4"
    second_source = tmp_path / "second.mp4"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")

    run_p1_qc_evidence_smoke(
        input_video=first_source,
        artifact_root=artifact_root,
        artifact_id="artifact_explicit_p1_qc_smoke",
    )

    with pytest.raises(ValueError, match="artifact_id already exists"):
        run_p1_qc_evidence_smoke(
            input_video=second_source,
            artifact_root=artifact_root,
            artifact_id="artifact_explicit_p1_qc_smoke",
        )


def test_opencv_video_quality_path_skips_image_probe_for_video_suffix(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_if_imread_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("video inputs should not be sent through cv2.imread first")

    class FakeCapture:
        def __init__(self, _path: str) -> None:
            self.released = False

        def isOpened(self) -> bool:
            return False

        def release(self) -> None:
            self.released = True

    fake_cv2 = SimpleNamespace(
        IMREAD_COLOR=1,
        CAP_PROP_FRAME_COUNT=7,
        CAP_PROP_POS_FRAMES=1,
        imread=fail_if_imread_called,
        VideoCapture=FakeCapture,
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    request = AdapterRequest(
        context=AdapterContext(
            tenant_id="tenant_opencv_contract",
            project_id="proj_opencv_contract",
            run_id="run_opencv_contract",
            tool_call_id="tool_call_opencv_contract",
            capability=CHECK_VISUAL_QUALITY,
        ),
        input={
            "_worker_media_path": str(tmp_path / "clip.mp4"),
            "frame_limit": 1,
        },
    )

    result = OpenCVAdapter().invoke(request)

    assert result.status == AdapterStatus.FAILED
    assert result.error_message == "OpenCV could not read visual samples from the supplied media input."


def _patch_successful_inspection_adapters(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        FFmpegAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "probe": {
                    "duration_seconds": 5.0,
                    "streams": [
                        {"codec_type": "video", "width": 1280, "height": 720},
                        {"codec_type": "audio", "sample_rate": 48000},
                    ],
                }
            },
        ),
    )
    monkeypatch.setattr(
        AudioQualityAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "duration_seconds": 5.0,
                "quality_summary": {
                    "status": "pass",
                    "audio_stream_count": 1,
                },
            },
        ),
    )
    monkeypatch.setattr(
        OpenCVAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "analysis_level": "sampled",
                "sampled_frame_count": request.input.get("frame_limit", 0),
                "quality_summary": {
                    "status": "pass",
                    "mean_brightness": 96.0,
                },
            },
        ),
    )
