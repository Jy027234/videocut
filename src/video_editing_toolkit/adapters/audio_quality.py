"""Structured audio quality adapter."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


CHECK_AUDIO_QUALITY = "audio.speech.check_audio_quality"


class AudioQualityAdapter(BaseAdapter):
    adapter_name = "audio_quality"
    supported_capabilities = frozenset({CHECK_AUDIO_QUALITY})
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == CHECK_AUDIO_QUALITY:
            return self._check_audio_quality(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def check_audio_quality(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def describe(self) -> Mapping[str, Any]:
        description = dict(super().describe())
        description["dependency_status"] = {
            "wave": "available",
            "ffprobe": "available" if shutil.which("ffprobe") else "missing",
        }
        return description

    def _check_audio_quality(self, request: AdapterRequest) -> AdapterResult:
        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "check_audio_quality requires one resolved audio or video artifact input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        frame_limit = self._sample_frame_limit(request)
        if frame_limit is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="check_audio_quality received unsupported audio quality options.",
            )

        wav_result = self._try_wave_quality(media_path, frame_limit)
        if wav_result is not None:
            return wav_result

        if shutil.which("ffprobe") is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.ADAPTER_UNAVAILABLE,
                error_message=(
                    "audio quality adapter dependency unavailable for non-WAV media: ffprobe."
                ),
            )

        return self._probe_audio_quality(request, media_path)

    def _try_wave_quality(self, media_path: Path, frame_limit: int) -> AdapterResult | None:
        try:
            with wave.open(str(media_path), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()
                total_frames = wav.getnframes()
                frames_to_read = min(total_frames, frame_limit)
                raw_frames = wav.readframes(frames_to_read)
        except (wave.Error, EOFError, OSError):
            return None

        if channels < 1 or sample_width not in {1, 2, 3, 4} or sample_rate < 1:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="wave could not read a supported PCM audio stream.",
            )

        samples = self._pcm_samples(raw_frames, sample_width)
        if not samples:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="wave could not read audio samples from the supplied input.",
            )

        peak = max(abs(sample) for sample in samples)
        square_mean = sum(sample * sample for sample in samples) / len(samples)
        rms = math.sqrt(square_mean)
        clipping_threshold = 0.99
        silence_threshold = 0.01
        clipping_ratio = sum(1 for sample in samples if abs(sample) >= clipping_threshold) / len(samples)
        silence_ratio = sum(1 for sample in samples if abs(sample) <= silence_threshold) / len(samples)

        duration = total_frames / sample_rate
        analyzed_duration = frames_to_read / sample_rate
        summary = {
            "duration_seconds": round(duration, 6),
            "analyzed_duration_seconds": round(analyzed_duration, 6),
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "peak_amplitude": round(peak, 6),
            "rms_amplitude": round(rms, 6),
            "rms_dbfs": self._dbfs(rms),
            "clipping_sample_ratio": round(clipping_ratio, 6),
            "silence_sample_ratio": round(silence_ratio, 6),
        }

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "media_kind": "audio",
                "analysis_level": "pcm_sample",
                "quality_summary": summary,
            },
            usage_metrics={
                "worker": "wave",
                "operation": "check_audio_quality",
                "sample_count": len(samples),
            },
        )

    def _probe_audio_quality(self, request: AdapterRequest, media_path: Path) -> AdapterResult:
        try:
            probe = self._run_ffprobe_json(media_path, self._timeout_seconds(request))
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
                error_message="ffprobe could not read audio metadata from the supplied media input.",
            )
        except (OSError, json.JSONDecodeError):
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="ffprobe returned an unreadable audio quality response.",
            )

        audio_streams = [
            self._sanitize_audio_stream(stream)
            for stream in probe.get("streams", [])
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ]
        if not audio_streams:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="ffprobe did not find an audio stream in the supplied media input.",
            )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "media_kind": "audio_or_video",
                "analysis_level": "probe_metadata",
                "audio_stream_count": len(audio_streams),
                "audio_streams": audio_streams,
                "quality_summary": self._metadata_summary(audio_streams),
            },
            usage_metrics={
                "worker": "ffprobe",
                "operation": "check_audio_quality",
                "audio_stream_count": len(audio_streams),
            },
        )

    def _run_ffprobe_json(
        self, media_path: Path, timeout_seconds: int | float
    ) -> Mapping[str, Any]:
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None:
            raise FileNotFoundError("ffprobe is unavailable")
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                str(media_path),
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout_seconds,
        )
        return json.loads(completed.stdout)

    def _sanitize_audio_stream(self, stream: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "index": self._optional_int(stream.get("index")),
            "codec_name": self._optional_str(stream.get("codec_name")),
            "sample_rate_hz": self._optional_int(stream.get("sample_rate")),
            "channels": self._optional_int(stream.get("channels")),
            "channel_layout": self._optional_str(stream.get("channel_layout")),
            "duration_seconds": self._optional_float(stream.get("duration")),
            "bit_rate_bps": self._optional_int(stream.get("bit_rate")),
        }

    def _metadata_summary(self, streams: list[dict[str, Any]]) -> dict[str, Any]:
        primary = streams[0]
        return {
            "duration_seconds": primary.get("duration_seconds"),
            "sample_rate_hz": primary.get("sample_rate_hz"),
            "channels": primary.get("channels"),
            "bit_rate_bps": primary.get("bit_rate_bps"),
            "has_audio_stream": True,
        }

    def _pcm_samples(self, raw_frames: bytes, sample_width: int) -> list[float]:
        if sample_width == 1:
            return [(byte - 128) / 128.0 for byte in raw_frames]

        max_value = float(2 ** (8 * sample_width - 1))
        samples: list[float] = []
        for offset in range(0, len(raw_frames) - sample_width + 1, sample_width):
            chunk = raw_frames[offset : offset + sample_width]
            value = int.from_bytes(chunk, byteorder="little", signed=True)
            samples.append(max(-1.0, min(1.0, value / max_value)))
        return samples

    def _dbfs(self, amplitude: float) -> float | None:
        if amplitude <= 0:
            return None
        return round(20 * math.log10(amplitude), 6)

    def _sample_frame_limit(self, request: AdapterRequest) -> int | None:
        value = request.input.get("sample_frame_limit", request.input.get("max_frames", 480_000))
        if not isinstance(value, int) or value < 1 or value > 4_800_000:
            return None
        return value

    def _timeout_seconds(self, request: AdapterRequest) -> int | float:
        if request.resource_limits is not None:
            return request.resource_limits.timeout_seconds
        return self.default_limits.timeout_seconds

    def _resolved_worker_media_path(self, request: AdapterRequest) -> Path | None:
        raw_path = request.input.get("_worker_media_path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        return Path(raw_path)

    def _optional_str(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _optional_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _optional_float(self, value: Any) -> float | None:
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            return None
