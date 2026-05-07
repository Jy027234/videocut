"""P0.4 speech/Whisper QA skeleton.

These checks keep host/default Docker graceful while Whisper source and the
speech worker profile land in parallel. When the adapter implementation arrives,
the xfail paths become real structured-output assertions.
"""

from __future__ import annotations

import os
import struct
import wave
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

from conftest import FIXTURES_DIR, assert_no_public_path_or_command_leak, load_json


TRANSCRIBE = "audio.speech.transcribe"
ALIGN_SUBTITLES = "audio.speech.align_subtitles"
SPEECH_CAPABILITIES = (TRANSCRIBE, ALIGN_SUBTITLES)
MODEL_ENV_VARS = (
    "VET_ALLOW_WHISPER",
    "VET_ALLOW_WHISPER_DOWNLOAD",
    "VET_WHISPER_MODEL",
    "VET_WHISPER_MODEL_DIR",
    "WHISPER_CACHE_DIR",
    "VIDEO_TOOLKIT_WHISPER_MODEL",
    "VIDEO_TOOLKIT_WHISPER_MODEL_PATH",
    "WHISPER_MODEL",
    "WHISPER_MODEL_PATH",
)
EXPLICIT_MODEL_ENV_VARS = (
    "VET_WHISPER_MODEL",
    "VIDEO_TOOLKIT_WHISPER_MODEL",
    "VIDEO_TOOLKIT_WHISPER_MODEL_PATH",
    "WHISPER_MODEL",
    "WHISPER_MODEL_PATH",
)


@pytest.fixture()
def service(tmp_path: Path) -> LocalRunService:
    runtime = LocalRunService(artifact_store=LocalArtifactStore(tmp_path / "artifacts"))
    register_p0_adapter_handlers(runtime)
    return runtime


@pytest.fixture()
def tiny_speech_audio_artifact(service: LocalRunService, tmp_path: Path):
    wav_path = tmp_path / "tiny-speech-input.wav"
    _generate_tiny_wav(wav_path)
    return service.artifact_store.put_file(
        source_path=wav_path,
        artifact_type="input_audio",
        owner_tenant_id="demo_tenant",
        created_by_run_id="fixture_setup",
        mime_type="audio/wav",
    )


def test_transcribe_without_model_is_stable_unavailable_or_pending(
    service: LocalRunService,
    tiny_speech_audio_artifact,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_env(monkeypatch)

    response = _run_speech(
        service,
        TRANSCRIBE,
        input_payload={
            "artifact_ref": {"artifact_id": tiny_speech_audio_artifact.artifact_id},
            "language": "en",
        },
        artifact_refs=[tiny_speech_audio_artifact],
    )

    assert response.status == RunStatus.FAILED
    _assert_whisper_boundary(response)
    if response.error_code == "adapter.not_implemented":
        pytest.xfail("audio.speech.transcribe is still a registered Whisper placeholder")
    assert response.error_code == "adapter.unavailable"


@pytest.mark.parametrize("capability", SPEECH_CAPABILITIES)
def test_speech_profile_boundary_is_caller_safe(
    service: LocalRunService,
    tiny_speech_audio_artifact,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    if os.environ.get("VIDEO_TOOLKIT_WORKER_PROFILE") != "speech":
        pytest.skip("speech profile boundary check runs in the speech Docker profile")
    _clear_model_env(monkeypatch)

    input_payload: dict[str, Any] = {
        "artifact_ref": {"artifact_id": tiny_speech_audio_artifact.artifact_id},
        "language": "en",
        "storage_uri": "local-artifact://should-not-be-returned",
        "raw_command": "whisper --model should-not-be-returned",
    }
    if capability == ALIGN_SUBTITLES:
        input_payload.update(_align_fixture_payload())

    response = _run_speech(
        service,
        capability,
        input_payload=input_payload,
        artifact_refs=[tiny_speech_audio_artifact],
    )

    assert response.usage_metrics["resource_class"] == "gpu_optional"
    _assert_whisper_boundary(response)
    if response.error_code == "adapter.not_implemented":
        pytest.xfail("P0.4 speech profile source implementation is pending")
    if capability == TRANSCRIBE:
        assert response.status == RunStatus.FAILED
        assert response.error_code == "adapter.unavailable"
    else:
        _assert_align_subtitles_result(response)


def test_align_subtitles_returns_structured_caller_safe_output_when_implemented(
    service: LocalRunService,
) -> None:
    response = _run_speech(
        service,
        ALIGN_SUBTITLES,
        input_payload=_align_fixture_payload(),
        artifact_refs=[],
    )

    _assert_whisper_boundary(response)
    if response.error_code == "adapter.not_implemented":
        pytest.xfail("pure structured align_subtitles implementation is pending")
    if response.error_code == "adapter.unavailable":
        pytest.xfail("align_subtitles still depends on unavailable speech worker setup")

    _assert_align_subtitles_result(response)


def _assert_align_subtitles_result(response: RunResponse) -> None:
    if response.error_code == "adapter.unavailable":
        pytest.xfail("align_subtitles still depends on unavailable speech worker setup")

    assert response.status == RunStatus.SUCCEEDED
    assert response.error_code is None
    aligned = _first_list(response.output, ("aligned_subtitles", "subtitles", "segments", "alignment"))
    assert aligned, "align_subtitles should return structured subtitle alignment"
    assert all(isinstance(item, dict) for item in aligned)
    assert any(
        {"text", "start_seconds", "end_seconds"}.issubset(item)
        or {"text", "start", "end"}.issubset(item)
        for item in aligned
    )


def test_transcribe_with_explicit_model_returns_structured_output_only_when_model_is_available(
    service: LocalRunService,
    tiny_speech_audio_artifact,
) -> None:
    model_hint = _explicit_model_hint()
    if not model_hint:
        pytest.skip("explicit Whisper model is not configured for this environment")

    response = _run_speech(
        service,
        TRANSCRIBE,
        input_payload={
            "artifact_ref": {"artifact_id": tiny_speech_audio_artifact.artifact_id},
            "language": "en",
            "model": "explicit",
        },
        artifact_refs=[tiny_speech_audio_artifact],
    )

    _assert_whisper_boundary(response)
    if response.error_code == "adapter.not_implemented":
        pytest.xfail("Whisper transcribe source implementation is pending")
    if response.error_code == "adapter.unavailable":
        pytest.xfail("explicit model hint is present but the model is not available to the worker")

    assert response.status == RunStatus.SUCCEEDED
    assert response.error_code is None
    assert _has_any_key(response.output, {"text", "segments", "transcript", "language"})
    segments = _first_list(response.output, ("segments", "transcript_segments", "words"))
    if segments:
        assert all(isinstance(segment, dict) for segment in segments)


def _generate_tiny_wav(wav_path: Path) -> None:
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


def _run_speech(
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


def _assert_whisper_boundary(response: RunResponse) -> None:
    assert response.output["adapter_name"] == "whisper"
    assert response.output["queue_topic"] == "audio.speech.whisper"
    assert response.output["artifact_policy"] == "artifact_ref_only"
    assert_no_public_path_or_command_leak(response.output)
    assert_no_public_path_or_command_leak(response.to_public_dict())


def _align_fixture_payload() -> dict[str, Any]:
    payload = load_json(
        FIXTURES_DIR / "speech" / "align_subtitles" / "basic_alignment_request.json"
    )
    return dict(payload["request"])


def _clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in MODEL_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)


def _explicit_model_hint() -> str | None:
    return next(
        (
            os.environ.get(env_var)
            for env_var in EXPLICIT_MODEL_ENV_VARS
            if os.environ.get(env_var)
        ),
        None,
    )


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
