"""Structured OpenCV analysis adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


ANALYZE_FRAMES = "video.analysis.analyze_frames"
CHECK_VISUAL_QUALITY = "video.analysis.check_visual_quality"
_VIDEO_SUFFIXES = frozenset(
    {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".webm",
        ".wmv",
    }
)


class OpenCVAdapter(BaseAdapter):
    adapter_name = "opencv"
    supported_capabilities = frozenset(
        {
            ANALYZE_FRAMES,
            CHECK_VISUAL_QUALITY,
        }
    )
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == ANALYZE_FRAMES:
            return self._analyze_frames(request)
        if request.context.capability == CHECK_VISUAL_QUALITY:
            return self._check_visual_quality(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def analyze_frames(self, request):
        return self.handle(request)

    def check_visual_quality(self, request):
        return self.handle(request)

    def describe(self) -> Mapping[str, Any]:
        description = dict(super().describe())
        description["dependency_status"] = {
            "cv2": "available" if self._cv2_available() else "missing"
        }
        return description

    def _analyze_frames(self, request: AdapterRequest) -> AdapterResult:
        try:
            import cv2
        except ImportError:
            return self._unavailable_result()

        frame_paths = self._resolved_worker_media_paths(request)
        if not frame_paths:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "analyze_frames requires one or more resolved frame artifact inputs. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        frame_limit = self._frame_limit(request, default=50)
        if frame_limit is None:
            return self._invalid_options("analyze_frames")

        metrics = []
        for index, frame_path in enumerate(frame_paths[:frame_limit], start=1):
            frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if frame is None:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message="OpenCV could not read one of the supplied frame inputs.",
                )
            metrics.append(self._frame_metrics(cv2, frame, index=index))

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "frames": metrics,
                "frame_count": len(metrics),
                "quality_summary": self._quality_summary(metrics),
            },
            usage_metrics={"worker": "opencv", "frame_count": len(metrics)},
        )

    def _check_visual_quality(self, request: AdapterRequest) -> AdapterResult:
        try:
            import cv2
        except ImportError:
            return self._unavailable_result()

        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "check_visual_quality requires one resolved image or video artifact input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        frame_limit = self._frame_limit(request, default=10)
        if frame_limit is None:
            return self._invalid_options("check_visual_quality")

        if self._looks_like_video_media(media_path):
            metrics = self._sample_video_metrics(cv2, media_path, frame_limit)
            media_kind = "video"
        else:
            image = cv2.imread(str(media_path), cv2.IMREAD_COLOR)
            if image is not None:
                metrics = [self._frame_metrics(cv2, image, index=1)]
                media_kind = "image"
            else:
                metrics = self._sample_video_metrics(cv2, media_path, frame_limit)
                media_kind = "video"

        if not metrics:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="OpenCV could not read visual samples from the supplied media input.",
            )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "media_kind": media_kind,
                "sampled_frame_count": len(metrics),
                "quality_summary": self._quality_summary(metrics),
                "samples": metrics,
            },
            usage_metrics={
                "worker": "opencv",
                "operation": "check_visual_quality",
                "sampled_frame_count": len(metrics),
            },
        )

    def _sample_video_metrics(self, cv2: Any, media_path: Path, frame_limit: int) -> list[dict[str, Any]]:
        capture = cv2.VideoCapture(str(media_path))
        if not capture.isOpened():
            return []

        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            sample_indexes = self._sample_indexes(frame_count, frame_limit)
            metrics: list[dict[str, Any]] = []
            if sample_indexes:
                for sample_index in sample_indexes:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, sample_index)
                    ok, frame = capture.read()
                    if ok and frame is not None:
                        metrics.append(
                            self._frame_metrics(
                                cv2,
                                frame,
                                index=len(metrics) + 1,
                                source_frame_index=sample_index,
                            )
                        )
            else:
                while len(metrics) < frame_limit:
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        break
                    metrics.append(self._frame_metrics(cv2, frame, index=len(metrics) + 1))
            return metrics
        finally:
            capture.release()

    def _frame_metrics(
        self,
        cv2: Any,
        frame: Any,
        *,
        index: int,
        source_frame_index: int | None = None,
    ) -> dict[str, Any]:
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        mean_brightness = float(gray.mean())
        stddev_brightness = float(gray.std())
        dark_ratio = float((gray < 16).mean())
        bright_ratio = float((gray > 240).mean())

        payload: dict[str, Any] = {
            "index": index,
            "width": int(width),
            "height": int(height),
            "channels": int(frame.shape[2]) if len(frame.shape) > 2 else 1,
            "mean_brightness": round(mean_brightness, 4),
            "contrast_stddev": round(stddev_brightness, 4),
            "sharpness_laplacian_variance": round(laplacian_variance, 4),
            "dark_pixel_ratio": round(dark_ratio, 6),
            "bright_pixel_ratio": round(bright_ratio, 6),
        }
        if source_frame_index is not None:
            payload["source_frame_index"] = source_frame_index
        return payload

    def _quality_summary(self, metrics: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "mean_brightness": self._mean(metrics, "mean_brightness"),
            "mean_contrast_stddev": self._mean(metrics, "contrast_stddev"),
            "mean_sharpness_laplacian_variance": self._mean(
                metrics, "sharpness_laplacian_variance"
            ),
            "mean_dark_pixel_ratio": self._mean(metrics, "dark_pixel_ratio"),
            "mean_bright_pixel_ratio": self._mean(metrics, "bright_pixel_ratio"),
        }

    def _mean(self, metrics: list[dict[str, Any]], key: str) -> float:
        if not metrics:
            return 0.0
        return round(sum(float(item[key]) for item in metrics) / len(metrics), 6)

    def _sample_indexes(self, frame_count: int, frame_limit: int) -> list[int]:
        if frame_count <= 0:
            return []
        count = min(frame_count, frame_limit)
        if count == 1:
            return [0]
        last_index = frame_count - 1
        return sorted({round(last_index * index / (count - 1)) for index in range(count)})

    def _looks_like_video_media(self, media_path: Path) -> bool:
        return media_path.suffix.casefold() in _VIDEO_SUFFIXES

    def _frame_limit(self, request: AdapterRequest, *, default: int) -> int | None:
        value = request.input.get("frame_limit", request.input.get("max_frames", default))
        if not isinstance(value, int) or value < 1 or value > 100:
            return None
        return value

    def _resolved_worker_media_path(self, request: AdapterRequest) -> Path | None:
        raw_path = request.input.get("_worker_media_path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        return Path(raw_path)

    def _resolved_worker_media_paths(self, request: AdapterRequest) -> tuple[Path, ...]:
        raw_paths = request.input.get("_worker_media_paths")
        if isinstance(raw_paths, (list, tuple)):
            paths = [Path(path) for path in raw_paths if isinstance(path, str) and path]
            if paths:
                return tuple(paths)

        single_path = self._resolved_worker_media_path(request)
        if single_path is None:
            return ()
        return (single_path,)

    def _invalid_options(self, capability: str) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.INVALID_REQUEST,
            error_message=f"{capability} received unsupported visual analysis options.",
        )

    def _unavailable_result(self) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            error_message="opencv adapter dependency unavailable: cv2.",
        )

    def _cv2_available(self) -> bool:
        try:
            import cv2  # noqa: F401
        except ImportError:
            return False
        return True
