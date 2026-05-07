"""Structured PySceneDetect adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_HEAVY_LIMITS, ErrorCode

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


DETECT_SCENES = "video.analysis.detect_scenes"


class PySceneDetectAdapter(BaseAdapter):
    adapter_name = "pyscenedetect"
    supported_capabilities = frozenset({DETECT_SCENES})
    default_limits = CPU_HEAVY_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == DETECT_SCENES:
            return self._detect_scenes(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def detect_scenes(self, request):
        return self.handle(request)

    def describe(self) -> Mapping[str, Any]:
        description = dict(super().describe())
        description["dependency_status"] = {
            "scenedetect": "available" if self._scenedetect_available() else "missing"
        }
        return description

    def _detect_scenes(self, request: AdapterRequest) -> AdapterResult:
        try:
            from scenedetect import SceneManager, open_video
            from scenedetect.detectors import ContentDetector
        except ImportError:
            return self._unavailable_result()

        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "detect_scenes requires one resolved video artifact input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        threshold = request.input.get("threshold", 27.0)
        min_scene_len = request.input.get("min_scene_len", 15)
        if not isinstance(threshold, (int, float)) or threshold <= 0:
            return self._invalid_options()
        if not isinstance(min_scene_len, int) or min_scene_len < 1:
            return self._invalid_options()

        try:
            video = open_video(str(media_path))
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(threshold=float(threshold), min_scene_len=min_scene_len)
            )
            scene_manager.detect_scenes(video=video)
            scene_list = scene_manager.get_scene_list()
        except Exception:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="PySceneDetect could not read or analyze the supplied video input.",
            )

        scenes = [
            {
                "index": index,
                "start_seconds": round(self._timecode_seconds(start), 6),
                "end_seconds": round(self._timecode_seconds(end), 6),
                "duration_seconds": round(
                    self._timecode_seconds(end) - self._timecode_seconds(start),
                    6,
                ),
                "start_frame": self._timecode_frame(start),
                "end_frame": self._timecode_frame(end),
                "start_timecode": start.get_timecode(),
                "end_timecode": end.get_timecode(),
            }
            for index, (start, end) in enumerate(scene_list, start=1)
        ]

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "scenes": scenes,
                "scene_count": len(scenes),
                "detector": "content",
                "threshold": float(threshold),
                "min_scene_len": min_scene_len,
            },
            usage_metrics={"worker": "pyscenedetect", "scene_count": len(scenes)},
        )

    def _resolved_worker_media_path(self, request: AdapterRequest) -> Path | None:
        raw_path = request.input.get("_worker_media_path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        return Path(raw_path)

    def _invalid_options(self) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message="detect_scenes received unsupported scene detection options.",
        )

    def _timecode_seconds(self, timecode: Any) -> float:
        seconds = getattr(timecode, "seconds", None)
        if isinstance(seconds, (int, float)):
            return float(seconds)
        return float(timecode.get_seconds())

    def _timecode_frame(self, timecode: Any) -> int:
        frame_num = getattr(timecode, "frame_num", None)
        if isinstance(frame_num, int):
            return frame_num
        return int(timecode.get_frames())

    def _unavailable_result(self) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            error_message="pyscenedetect adapter dependency unavailable: scenedetect.",
        )

    def _scenedetect_available(self) -> bool:
        try:
            import scenedetect  # noqa: F401
        except ImportError:
            return False
        return True
