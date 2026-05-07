"""Structured Whisper speech adapter."""

from __future__ import annotations

import os
import shutil
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import ErrorCode, GPU_OPTIONAL_LIMITS

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


TRANSCRIBE = "audio.speech.transcribe"
ALIGN_SUBTITLES = "audio.speech.align_subtitles"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_DEFAULT_MODEL_NAME = "base"
_MODEL_ENV_VARS = (
    "VET_WHISPER_MODEL",
    "VIDEO_TOOLKIT_WHISPER_MODEL",
    "WHISPER_MODEL",
    "VET_WHISPER_MODEL_PATH",
    "VIDEO_TOOLKIT_WHISPER_MODEL_PATH",
    "WHISPER_MODEL_PATH",
)
_MODEL_DIR_ENV_VARS = (
    "VET_WHISPER_MODEL_DIR",
    "WHISPER_CACHE_DIR",
)


class WhisperAdapter(BaseAdapter):
    adapter_name = "whisper"
    supported_capabilities = frozenset({TRANSCRIBE, ALIGN_SUBTITLES})
    default_limits = GPU_OPTIONAL_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == TRANSCRIBE:
            return self._transcribe(request)
        if request.context.capability == ALIGN_SUBTITLES:
            return self._align_subtitles(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def transcribe(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def align_subtitles(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def describe(self) -> Mapping[str, Any]:
        description = dict(super().describe())
        description["dependency_status"] = {
            "openai_whisper": "available" if self._whisper_available() else "missing",
            "ffmpeg": "available" if shutil.which("ffmpeg") else "missing",
        }
        description["model_runtime"] = {
            "requires_explicit_allow": True,
            "downloads_disabled_by_default": True,
        }
        return description

    def _transcribe(self, request: AdapterRequest) -> AdapterResult:
        try:
            import whisper
        except ImportError:
            return self._unavailable_result(
                "whisper adapter dependency unavailable: install optional package openai-whisper."
            )

        if shutil.which("ffmpeg") is None:
            return self._unavailable_result(
                "whisper adapter dependency unavailable: ffmpeg."
            )

        if not self._model_run_allowed(request):
            return self._unavailable_result(
                "whisper model execution is disabled until explicitly allowed."
            )

        media_path = self._resolved_worker_media_path(request)
        if media_path is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "transcribe requires one resolved audio or video artifact input. "
                    "Artifact resolution is not exposed by this adapter."
                ),
            )

        model_name = self._model_name(request)
        download_root = self._download_root(request)
        if not self._model_available(whisper, model_name, download_root):
            if not self._model_download_allowed(request):
                return self._unavailable_result(
                    "whisper model is not present locally and runtime model downloads are disabled."
                )

        options = self._transcribe_options(request)
        if options is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="transcribe received unsupported speech recognition options.",
            )

        try:
            model = whisper.load_model(model_name, download_root=download_root)
            raw_result = model.transcribe(str(media_path), **options)
        except Exception:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="whisper could not transcribe the supplied media input.",
            )

        segments = self._sanitize_segments(raw_result.get("segments"))
        text = raw_result.get("text")
        language = raw_result.get("language")
        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "text": text.strip() if isinstance(text, str) else "",
                "language": language if isinstance(language, str) else None,
                "segments": segments,
                "segment_count": len(segments),
                "model": self._public_model_name(model_name),
            },
            usage_metrics={
                "worker": "openai-whisper",
                "operation": "transcribe",
                "segment_count": len(segments),
            },
        )

    def _align_subtitles(self, request: AdapterRequest) -> AdapterResult:
        segments = self._input_segments(request.input.get("segments"))
        if segments is None:
            text = request.input.get("text", request.input.get("transcript"))
            if not isinstance(text, str) or not text.strip():
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error_code=ErrorCode.INVALID_REQUEST,
                    error_message=(
                        "align_subtitles requires transcript text or transcript segments."
                    ),
                )
            segments = [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": self._text_duration_hint(text),
                    "text": text.strip(),
                }
            ]

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "format": "srt",
                "subtitle_count": len(segments),
                "subtitles": self._segments_to_srt(segments),
                "segments": segments,
            },
            usage_metrics={
                "worker": "local",
                "operation": "align_subtitles",
                "subtitle_count": len(segments),
            },
        )

    def _transcribe_options(self, request: AdapterRequest) -> dict[str, Any] | None:
        options: dict[str, Any] = {}
        language = request.input.get("language")
        if language is not None:
            if not isinstance(language, str) or not language:
                return None
            options["language"] = language

        task = request.input.get("task")
        if task is not None:
            if task not in {"transcribe", "translate"}:
                return None
            options["task"] = task

        temperature = request.input.get("temperature")
        if temperature is not None:
            if not isinstance(temperature, (int, float)) or temperature < 0:
                return None
            options["temperature"] = float(temperature)

        return options

    def _model_name(self, request: AdapterRequest) -> str:
        value = request.input.get("model", request.input.get("model_name"))
        if isinstance(value, str) and value:
            return value
        for env_var in _MODEL_ENV_VARS:
            value = os.environ.get(env_var)
            if value:
                return value
        return _DEFAULT_MODEL_NAME

    def _download_root(self, request: AdapterRequest) -> str | None:
        value = request.input.get("model_cache_dir")
        if isinstance(value, str) and value:
            return value
        for env_var in _MODEL_DIR_ENV_VARS:
            value = os.environ.get(env_var)
            if value:
                return value
        return None

    def _public_model_name(self, model_name: str) -> str:
        model_path = Path(model_name)
        if model_path.is_absolute() or model_path.parent != Path("."):
            return model_path.name or "local_model"
        return model_name

    def _model_available(self, whisper: Any, model_name: str, download_root: str | None) -> bool:
        if Path(model_name).exists():
            return True

        models = getattr(whisper, "_MODELS", {})
        model_url = models.get(model_name) if isinstance(models, dict) else None
        if not isinstance(model_url, str):
            return True

        root = Path(download_root) if download_root else Path.home() / ".cache" / "whisper"
        filename = Path(urllib.parse.urlparse(model_url).path).name
        return bool(filename and (root / filename).is_file())

    def _model_run_allowed(self, request: AdapterRequest) -> bool:
        value = request.input.get("allow_model_run")
        if isinstance(value, bool):
            return value
        return os.environ.get("VET_ALLOW_WHISPER", "").lower() in _TRUE_VALUES

    def _model_download_allowed(self, request: AdapterRequest) -> bool:
        value = request.input.get("allow_model_download")
        if isinstance(value, bool):
            return value
        return os.environ.get("VET_ALLOW_WHISPER_DOWNLOAD", "").lower() in _TRUE_VALUES

    def _sanitize_segments(self, raw_segments: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_segments, list):
            return []

        segments: list[dict[str, Any]] = []
        for index, segment in enumerate(raw_segments, start=1):
            if not isinstance(segment, dict):
                continue
            start = self._seconds(segment.get("start"))
            end = self._seconds(segment.get("end"))
            text = segment.get("text")
            if start is None or end is None or not isinstance(text, str):
                continue
            segments.append(
                {
                    "id": int(segment.get("id", index)),
                    "start": start,
                    "end": end,
                    "text": text.strip(),
                }
            )
        return segments

    def _input_segments(self, raw_segments: Any) -> list[dict[str, Any]] | None:
        if not isinstance(raw_segments, list):
            return None

        segments: list[dict[str, Any]] = []
        for index, segment in enumerate(raw_segments, start=1):
            if not isinstance(segment, dict):
                return None
            start = self._seconds(segment.get("start"))
            end = self._seconds(segment.get("end"))
            text = segment.get("text")
            if start is None or end is None or end < start or not isinstance(text, str):
                return None
            segments.append(
                {
                    "id": int(segment.get("id", index)),
                    "start": start,
                    "end": end,
                    "text": text.strip(),
                }
            )
        return segments

    def _segments_to_srt(self, segments: list[dict[str, Any]]) -> str:
        blocks = []
        for index, segment in enumerate(segments, start=1):
            blocks.append(
                "\n".join(
                    [
                        str(index),
                        f"{self._srt_timestamp(segment['start'])} --> {self._srt_timestamp(segment['end'])}",
                        segment["text"],
                    ]
                )
            )
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    def _srt_timestamp(self, seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _text_duration_hint(self, text: str) -> float:
        word_count = max(1, len(text.split()))
        return round(max(1.0, word_count / 2.5), 3)

    def _seconds(self, value: Any) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        return round(max(0.0, float(value)), 6)

    def _resolved_worker_media_path(self, request: AdapterRequest) -> Path | None:
        raw_path = request.input.get("_worker_media_path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        return Path(raw_path)

    def _unavailable_result(self, message: str) -> AdapterResult:
        return AdapterResult(
            status=AdapterStatus.FAILED,
            error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            error_message=message,
        )

    def _whisper_available(self) -> bool:
        try:
            import whisper  # noqa: F401
        except ImportError:
            return False
        return True
