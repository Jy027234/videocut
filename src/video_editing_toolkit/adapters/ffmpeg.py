"""Structured FFmpeg adapter skeleton.

The public surface is capability-oriented. Command construction is private and
controlled by operation definitions; raw commands and local paths are never
returned to callers.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_HEAVY_LIMITS, ErrorCode
from video_editing_toolkit.storage import LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


PROBE_MEDIA = "video.asset_ingest.probe_media"
NORMALIZE_ASSET = "video.asset_ingest.normalize_asset"
EXTRACT_AUDIO = "video.asset_ingest.extract_audio"
EXTRACT_FRAMES = "video.asset_ingest.extract_frames"
RENDER_PREVIEW = "video.render.render_preview"
RENDER_FINAL = "video.render.render_final"


@dataclass(frozen=True)
class FFmpegOperation:
    """Private operation descriptor for a structured FFmpeg capability."""

    capability: str
    binary_requirements: frozenset[str]
    implemented: bool = False


class FFmpegAdapter(BaseAdapter):
    adapter_name = "ffmpeg"
    supported_capabilities = frozenset(
        {
            PROBE_MEDIA,
            NORMALIZE_ASSET,
            EXTRACT_AUDIO,
            EXTRACT_FRAMES,
            RENDER_PREVIEW,
            RENDER_FINAL,
        }
    )
    default_limits = CPU_HEAVY_LIMITS
    _operations: Mapping[str, FFmpegOperation] = {
        PROBE_MEDIA: FFmpegOperation(
            capability=PROBE_MEDIA,
            binary_requirements=frozenset({"ffprobe"}),
            implemented=True,
        ),
        NORMALIZE_ASSET: FFmpegOperation(
            capability=NORMALIZE_ASSET,
            binary_requirements=frozenset({"ffmpeg", "ffprobe"}),
            implemented=True,
        ),
        EXTRACT_AUDIO: FFmpegOperation(
            capability=EXTRACT_AUDIO,
            binary_requirements=frozenset({"ffmpeg", "ffprobe"}),
            implemented=True,
        ),
        EXTRACT_FRAMES: FFmpegOperation(
            capability=EXTRACT_FRAMES,
            binary_requirements=frozenset({"ffmpeg", "ffprobe"}),
            implemented=True,
        ),
        RENDER_PREVIEW: FFmpegOperation(
            capability=RENDER_PREVIEW,
            binary_requirements=frozenset({"ffmpeg", "ffprobe"}),
            implemented=True,
        ),
        RENDER_FINAL: FFmpegOperation(
            capability=RENDER_FINAL,
            binary_requirements=frozenset({"ffmpeg", "ffprobe"}),
            implemented=True,
        ),
    }

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        operation = self._operations[request.context.capability]
        missing = self._missing_binaries(operation)
        if missing:
            return self._unavailable_result(missing)
        if operation.capability == PROBE_MEDIA:
            return self._probe_media(request)
        if operation.capability == NORMALIZE_ASSET:
            return self._normalize_asset(request)
        if operation.capability == EXTRACT_AUDIO:
            return self._extract_audio(request)
        if operation.capability == EXTRACT_FRAMES:
            return self._extract_frames(request)
        if operation.capability == RENDER_PREVIEW:
            return self._render_preview(request)
        if operation.capability == RENDER_FINAL:
            return self._render_final(request)
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.ADAPTER_NOT_IMPLEMENTED,
            error_message=(
                f"{self.adapter_name} capability {operation.capability} "
                "is registered but not implemented yet."
            ),
        )

    def probe_media(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def normalize_asset(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def extract_audio(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def extract_frames(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def render_preview(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def render_final(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def describe(self) -> Mapping[str, Any]:
        description = dict(super().describe())
        description["dependency_status"] = {
            name: "available" if _binary_path(name) else "missing"
            for name in ("ffmpeg", "ffprobe")
        }
        description["operations"] = [
            {
                "capability": operation.capability,
                "implemented": operation.implemented,
                "requires": sorted(operation.binary_requirements),
            }
            for operation in self._operations.values()
        ]
        return description

    def _probe_media(self, request: AdapterRequest) -> AdapterResult:
        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "probe_media requires one resolved worker media input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        timeout_seconds = (
            request.resource_limits.timeout_seconds
            if request.resource_limits is not None
            else self.default_limits.timeout_seconds
        )
        try:
            probe = self._run_ffprobe_json(media_path, timeout_seconds)
        except subprocess.TimeoutExpired:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.TIMEOUT_EXCEEDED,
                error_message="ffprobe exceeded the configured timeout.",
            )
        except subprocess.CalledProcessError:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="ffprobe could not read the supplied media input.",
            )
        except (OSError, json.JSONDecodeError):
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="ffprobe returned an unreadable probe response.",
            )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"probe": self._sanitize_probe(probe)},
            usage_metrics={"worker": "ffprobe"},
        )

    def _normalize_asset(self, request: AdapterRequest) -> AdapterResult:
        return self._transcode_mp4_artifact(
            request,
            operation="normalize_asset",
            artifact_type="normalized_video",
            output_key="normalized_video_artifact_ref",
            filename="normalized.mp4",
            crf="23",
            filter_args=["-vf", self._even_dimensions_filter()],
            max_duration_seconds=None,
        )

    def _render_preview(self, request: AdapterRequest) -> AdapterResult:
        preview_spec = self._render_preview_spec(request)
        if preview_spec is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="render_preview received unsupported preview options.",
            )

        return self._transcode_mp4_artifact(
            request,
            operation="render_preview",
            artifact_type="preview_video",
            output_key="preview_video_artifact_ref",
            filename="preview.mp4",
            crf="28",
            filter_args=["-vf", f"scale=-2:{preview_spec['height']}"],
            max_duration_seconds=preview_spec["duration_seconds"],
        )

    def _render_final(self, request: AdapterRequest) -> AdapterResult:
        return self._transcode_mp4_artifact(
            request,
            operation="render_final",
            artifact_type="final_render",
            output_key="final_render_artifact_ref",
            filename="final-render.mp4",
            crf="20",
            filter_args=["-vf", self._even_dimensions_filter()],
            max_duration_seconds=None,
        )

    def _transcode_mp4_artifact(
        self,
        request: AdapterRequest,
        *,
        operation: str,
        artifact_type: str,
        output_key: str,
        filename: str,
        crf: str,
        filter_args: list[str],
        max_duration_seconds: float | None,
    ) -> AdapterResult:
        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    f"{operation} requires one resolved worker media input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        artifact_store = self._artifact_store(request)
        if artifact_store is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message=f"{operation} requires a configured artifact store.",
            )

        timeout_seconds = self._timeout_seconds(request)
        with tempfile.TemporaryDirectory(prefix=f"vet-ffmpeg-{operation}-") as temp_dir:
            output_path = Path(temp_dir) / filename
            try:
                transcode_profile = self._run_mp4_transcode(
                    media_path,
                    output_path,
                    timeout_seconds,
                    crf=crf,
                    filter_args=filter_args,
                    max_duration_seconds=max_duration_seconds,
                )
            except subprocess.TimeoutExpired:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.TIMEOUT_EXCEEDED,
                    error_message="ffmpeg exceeded the configured timeout.",
                )
            except subprocess.CalledProcessError:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message="ffmpeg could not render an MP4 video from the supplied media.",
                )
            except OSError:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message="ffmpeg failed while writing the rendered video artifact.",
                )

            if not output_path.is_file() or output_path.stat().st_size <= 0:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message="ffmpeg did not produce a rendered video artifact.",
                )

            artifact_ref = artifact_store.put_file(
                source_path=output_path,
                artifact_type=artifact_type,
                owner_tenant_id=request.context.tenant_id,
                created_by_run_id=request.context.run_id,
                filename=output_path.name,
                mime_type="video/mp4",
            )

        public_ref = artifact_ref.to_public_dict()
        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "artifact_ref": public_ref,
                output_key: public_ref,
                "artifact_count": 1,
                "output_artifact_type": artifact_type,
                "video_format": "mp4",
            },
            artifact_refs=(artifact_ref,),
            usage_metrics={
                "worker": "ffmpeg",
                "operation": operation,
                "output_bytes": artifact_ref.size_bytes,
                "transcode_profile": transcode_profile,
            },
        )

    def _extract_audio(self, request: AdapterRequest) -> AdapterResult:
        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "extract_audio requires one resolved worker media input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        audio_spec = self._extract_audio_spec(request)
        if audio_spec is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="extract_audio received an unsupported audio option.",
            )

        artifact_store = self._artifact_store(request)
        if artifact_store is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="extract_audio requires a configured artifact store.",
            )

        timeout_seconds = self._timeout_seconds(request)
        with tempfile.TemporaryDirectory(prefix="vet-ffmpeg-audio-") as temp_dir:
            output_path = Path(temp_dir) / f"audio.{audio_spec['container']}"
            try:
                self._run_ffmpeg(
                    [
                        "-i",
                        str(media_path),
                        "-vn",
                        "-map",
                        "0:a:0",
                        "-acodec",
                        audio_spec["codec"],
                        str(output_path),
                    ],
                    timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.TIMEOUT_EXCEEDED,
                    error_message="ffmpeg exceeded the configured timeout.",
                )
            except subprocess.CalledProcessError:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message="ffmpeg could not extract an audio stream from the supplied media.",
                )
            except OSError:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message="ffmpeg failed while writing the extracted audio artifact.",
                )

            artifact_ref = artifact_store.put_file(
                source_path=output_path,
                artifact_type="extracted_audio",
                owner_tenant_id=request.context.tenant_id,
                created_by_run_id=request.context.run_id,
                filename=output_path.name,
                mime_type=audio_spec["mime_type"],
            )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "artifact_ref": artifact_ref.to_public_dict(),
                "artifact_count": 1,
                "audio_format": audio_spec["container"],
            },
            artifact_refs=(artifact_ref,),
            usage_metrics={
                "worker": "ffmpeg",
                "operation": "extract_audio",
                "output_bytes": artifact_ref.size_bytes,
            },
        )

    def _extract_frames(self, request: AdapterRequest) -> AdapterResult:
        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "extract_frames requires one resolved worker media input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        frame_spec = self._extract_frames_spec(request)
        if frame_spec is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="extract_frames received unsupported frame extraction options.",
            )

        artifact_store = self._artifact_store(request)
        if artifact_store is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="extract_frames requires a configured artifact store.",
            )

        timeout_seconds = self._timeout_seconds(request)
        extension = frame_spec["extension"]
        with tempfile.TemporaryDirectory(prefix="vet-ffmpeg-frames-") as temp_dir:
            temp_path = Path(temp_dir)
            try:
                timestamps = frame_spec["timestamps"]
                if timestamps:
                    for index, timestamp in enumerate(timestamps, start=1):
                        self._run_ffmpeg(
                            [
                                "-ss",
                                f"{timestamp:.6f}",
                                "-i",
                                str(media_path),
                                "-frames:v",
                                "1",
                                str(temp_path / f"frame_{index:03d}.{extension}"),
                            ],
                            timeout_seconds,
                        )
                else:
                    self._run_ffmpeg(
                        [
                            "-i",
                            str(media_path),
                            "-frames:v",
                            str(frame_spec["frame_count"]),
                            str(temp_path / f"frame_%03d.{extension}"),
                        ],
                        timeout_seconds,
                    )
            except subprocess.TimeoutExpired:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.TIMEOUT_EXCEEDED,
                    error_message="ffmpeg exceeded the configured timeout.",
                )
            except subprocess.CalledProcessError:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message="ffmpeg could not extract video frames from the supplied media.",
                )
            except OSError:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    error_message="ffmpeg failed while writing extracted frame artifacts.",
                )

            output_paths = sorted(temp_path.glob(f"*.{extension}"))
            if not output_paths:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message="ffmpeg did not produce any frame artifacts.",
                )

            artifact_refs = tuple(
                artifact_store.put_file(
                    source_path=path,
                    artifact_type="extracted_frames",
                    owner_tenant_id=request.context.tenant_id,
                    created_by_run_id=request.context.run_id,
                    filename=path.name,
                    mime_type=frame_spec["mime_type"],
                )
                for path in output_paths
            )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "artifact_refs": [ref.to_public_dict() for ref in artifact_refs],
                "artifact_count": len(artifact_refs),
                "image_format": frame_spec["extension"],
            },
            artifact_refs=artifact_refs,
            usage_metrics={
                "worker": "ffmpeg",
                "operation": "extract_frames",
                "frame_count": len(artifact_refs),
                "output_bytes": sum(ref.size_bytes for ref in artifact_refs),
            },
        )

    def _run_ffprobe_json(
        self, media_path: Path, timeout_seconds: int | float
    ) -> Mapping[str, Any]:
        ffprobe = _binary_path("ffprobe")
        if ffprobe is None:
            raise FileNotFoundError("ffprobe is unavailable")
        completed = subprocess.run(
            [
                ffprobe,
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
            timeout=timeout_seconds,
        )
        return json.loads(completed.stdout)

    def _run_ffmpeg(self, arguments: list[str], timeout_seconds: int | float) -> None:
        ffmpeg = _binary_path("ffmpeg")
        if ffmpeg is None:
            raise FileNotFoundError("ffmpeg is unavailable")
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-y",
                *arguments,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout_seconds,
        )

    def _run_mp4_transcode(
        self,
        media_path: Path,
        output_path: Path,
        timeout_seconds: int | float,
        *,
        crf: str,
        filter_args: list[str],
        max_duration_seconds: float | None,
    ) -> str:
        primary_args = self._mp4_transcode_arguments(
            media_path,
            output_path,
            filter_args=filter_args,
            max_duration_seconds=max_duration_seconds,
            video_codec_args=[
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                crf,
            ],
        )
        try:
            self._run_ffmpeg(primary_args, timeout_seconds)
            return "h264_aac"
        except subprocess.CalledProcessError:
            fallback_args = self._mp4_transcode_arguments(
                media_path,
                output_path,
                filter_args=filter_args,
                max_duration_seconds=max_duration_seconds,
                video_codec_args=[
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "5",
                ],
            )
            self._run_ffmpeg(fallback_args, timeout_seconds)
            return "mpeg4_aac"

    def _mp4_transcode_arguments(
        self,
        media_path: Path,
        output_path: Path,
        *,
        filter_args: list[str],
        max_duration_seconds: float | None,
        video_codec_args: list[str],
    ) -> list[str]:
        arguments = ["-i", str(media_path)]
        if max_duration_seconds is not None:
            arguments.extend(["-t", f"{max_duration_seconds:.6f}"])
        arguments.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                *filter_args,
                *video_codec_args,
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        return arguments

    def _resolved_worker_media_path(self, request: AdapterRequest) -> Path | None:
        raw_path = request.input.get("_worker_media_path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        return Path(raw_path)

    def _artifact_store(self, request: AdapterRequest) -> LocalArtifactStore | None:
        artifact_store = request.input.get("_artifact_store")
        if isinstance(artifact_store, LocalArtifactStore):
            return artifact_store
        return None

    def _timeout_seconds(self, request: AdapterRequest) -> int | float:
        if request.resource_limits is not None:
            return request.resource_limits.timeout_seconds
        return self.default_limits.timeout_seconds

    def _render_preview_spec(self, request: AdapterRequest) -> Mapping[str, Any] | None:
        height = self._bounded_int(
            request.input.get("preview_height", request.input.get("height")),
            default=360,
            minimum=64,
            maximum=720,
        )
        duration_seconds = self._bounded_float(
            request.input.get(
                "max_duration_seconds",
                request.input.get("duration_seconds"),
            ),
            default=30.0,
            minimum=0.1,
            maximum=300.0,
        )
        if height is None or duration_seconds is None:
            return None
        if height % 2:
            height += 1
        return {"height": height, "duration_seconds": duration_seconds}

    def _bounded_int(
        self,
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int | None:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if value < minimum or value > maximum:
            return None
        return value

    def _bounded_float(
        self,
        value: Any,
        *,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float | None:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or number < minimum or number > maximum:
            return None
        return number

    def _even_dimensions_filter(self) -> str:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"

    def _extract_audio_spec(self, request: AdapterRequest) -> Mapping[str, str] | None:
        format_name = request.input.get("audio_format", request.input.get("format", "wav"))
        if format_name not in {"wav", "m4a"}:
            return None
        if format_name == "m4a":
            return {"container": "m4a", "codec": "aac", "mime_type": "audio/mp4"}
        return {"container": "wav", "codec": "pcm_s16le", "mime_type": "audio/wav"}

    def _extract_frames_spec(self, request: AdapterRequest) -> Mapping[str, Any] | None:
        format_name = request.input.get("image_format", request.input.get("format", "jpg"))
        if format_name not in {"jpg", "jpeg", "png"}:
            return None

        timestamps = self._timestamp_list(request.input.get("timestamps"))
        if timestamps is None:
            return None
        if timestamps and len(timestamps) > 10:
            return None

        if timestamps:
            frame_count = len(timestamps)
        else:
            raw_count = request.input.get("frame_count", 1)
            if not isinstance(raw_count, int) or raw_count < 1 or raw_count > 10:
                return None
            frame_count = raw_count

        extension = "jpg" if format_name == "jpeg" else format_name
        mime_type = "image/png" if extension == "png" else "image/jpeg"
        return {
            "extension": extension,
            "mime_type": mime_type,
            "frame_count": frame_count,
            "timestamps": timestamps,
        }

    def _timestamp_list(self, value: Any) -> tuple[float, ...] | None:
        if value is None:
            return ()
        if not isinstance(value, list):
            return None
        timestamps: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)) or item < 0:
                return None
            timestamps.append(float(item))
        return tuple(timestamps)

    def _missing_binaries(self, operation: FFmpegOperation) -> tuple[str, ...]:
        return tuple(
            name for name in sorted(operation.binary_requirements) if _binary_path(name) is None
        )

    def _unavailable_result(self, missing: tuple[str, ...]) -> AdapterResult:
        dependencies = ", ".join(missing)
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            error_message=(
                f"{self.adapter_name} adapter dependency unavailable: {dependencies}."
            ),
        )

    def _sanitize_probe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._sanitize_probe(child)
                for key, child in value.items()
                if key.lower() != "filename"
            }
        if isinstance(value, list):
            return [self._sanitize_probe(child) for child in value]
        return value


def _binary_path(name: str) -> str | None:
    found = shutil.which(name)
    if found is not None:
        return found
    if not _static_ffmpeg_enabled():
        return None
    try:
        import static_ffmpeg
    except ImportError:
        return None
    try:
        static_ffmpeg.add_paths()
    except Exception:
        return None
    return shutil.which(name)


def _static_ffmpeg_enabled() -> bool:
    value = os.environ.get("VIDEO_TOOLKIT_USE_STATIC_FFMPEG", "")
    return value.casefold() in {"1", "true", "yes", "on"}
