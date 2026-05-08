"""P1.1 MOSS-TTS-Nano voiceover adapter contract checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_editing_toolkit.adapters import AdapterContext, AdapterRequest, AdapterStatus
from video_editing_toolkit.adapters.routing import (
    P1_CAPABILITY_ROUTES,
    build_p1_experimental_adapter,
    resolve_p1_experimental_route,
    resolve_route,
)
from video_editing_toolkit.adapters.tts import (
    GENERATE_VOICEOVER,
    TTSAdapter,
    VOICEOVER_MANIFEST_ARTIFACT_TYPE,
)
from video_editing_toolkit.resource_guard import ErrorCode
from video_editing_toolkit.storage import LocalArtifactStore

from conftest import assert_no_public_path_or_command_leak


def test_tts_plan_only_returns_caller_safe_voiceover_plan(
    monkeypatch,
) -> None:
    monkeypatch.delenv("MOSS_TTS_NANO_MODEL_PATH", raising=False)
    adapter = TTSAdapter()
    raw_path = r"D:\private\models\moss-tts-nano.onnx"
    secret = "provider-secret-value"

    result = adapter.handle(
        _request(
            {
                "text": f"Read this intro. model={raw_path} api_key={secret}",
                "synthesis_mode": "plan_only",
                "model_path": raw_path,
                "voice_preset": "warm_host",
                "language": "en-US",
                "output_format": "wav",
                "sample_rate_hz": 24000,
            }
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.error_code is None
    assert result.output["synthesis_mode"] == "plan_only"
    assert result.output["model_runtime"]["provider"] == "MOSS-TTS-Nano"
    assert result.output["model_runtime"]["backend"] == "onnx_cpu"
    assert result.output["model_runtime"]["model_configured"] is True
    plan = result.output["voiceover_plan"]
    assert plan["capability"] == GENERATE_VOICEOVER
    assert plan["voice_profile"]["voice_mode"] == "preset"
    assert plan["segment_count"] == 1
    assert plan["segments"][0]["text_preview"]

    rendered = json.dumps(result.output, sort_keys=True)
    assert raw_path not in rendered
    assert secret not in rendered
    assert_no_public_path_or_command_leak(result.output)


def test_tts_without_model_path_returns_stable_unavailable(
    monkeypatch,
) -> None:
    _clear_model_env(monkeypatch)
    adapter = TTSAdapter()

    result = adapter.handle(
        _request(
            {
                "text": "Narrate the five second highlight cut.",
                "language": "en-US",
            }
        )
    )

    assert result.status == AdapterStatus.FAILED
    assert result.error_code == ErrorCode.ADAPTER_UNAVAILABLE
    assert result.output["reason_code"] == "tts.model_unconfigured"
    assert result.output["model_runtime"]["model_configured"] is False
    assert result.output["plan_available"] is True
    assert_no_public_path_or_command_leak(result.output)


def test_tts_voice_clone_is_deferred_even_with_consent(
    monkeypatch,
) -> None:
    _clear_model_env(monkeypatch)
    adapter = TTSAdapter()

    rejected = adapter.handle(
        _request(
            {
                "text": "Narrate with a cloned reference voice.",
                "dry_run": True,
                "voice_clone": True,
                "voiceprint": {"artifact_id": "voiceprint_fixture"},
            }
        )
    )

    assert rejected.status == AdapterStatus.FAILED
    assert rejected.error_code == ErrorCode.INVALID_REQUEST
    assert rejected.output["reason_code"] == "tts.voice_clone_deferred"
    assert rejected.output["requires_consent"] is True
    assert_no_public_path_or_command_leak(rejected.output)

    still_deferred = adapter.handle(
        _request(
            {
                "text": "Narrate with an approved cloned reference voice.",
                "dry_run": True,
                "voice_clone": True,
                "voiceprint": {"artifact_id": "voiceprint_fixture"},
                "consent_policy": {
                    "voice_clone_approved": True,
                    "subject_consent": True,
                },
            }
        )
    )

    assert still_deferred.status == AdapterStatus.FAILED
    assert still_deferred.error_code == ErrorCode.INVALID_REQUEST
    assert still_deferred.output["reason_code"] == "tts.voice_clone_deferred"
    assert still_deferred.output["deferred_capability"] == "audio.tts.clone_voice"
    assert "voiceprint_fixture" not in json.dumps(still_deferred.output, sort_keys=True)
    assert_no_public_path_or_command_leak(still_deferred.output)


def test_tts_plan_only_can_emit_manifest_artifact(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    adapter = TTSAdapter()

    result = adapter.handle(
        _request(
            {
                "text": "Create a short launch voiceover.",
                "synthesis_mode": "plan_only",
                "emit_manifest_artifact": True,
                "_artifact_store": artifact_store,
            }
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert len(result.artifact_refs) == 1
    manifest_ref = result.artifact_refs[0]
    assert manifest_ref.artifact_type == VOICEOVER_MANIFEST_ARTIFACT_TYPE
    assert result.output["voiceover_manifest_artifact_ref"]["artifact_id"] == manifest_ref.artifact_id
    assert_no_public_path_or_command_leak(result.output)

    manifest_path = artifact_store.open_local_path(manifest_ref.artifact_id)
    assert manifest_path is not None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "video_editing_toolkit.voiceover_manifest.v0"
    assert manifest["voiceover_plan"]["segment_count"] == 1


def test_tts_routing_resolves_p1_voiceover_adapter() -> None:
    route = resolve_p1_experimental_route(GENERATE_VOICEOVER)
    adapter = build_p1_experimental_adapter(GENERATE_VOICEOVER)

    assert P1_CAPABILITY_ROUTES[GENERATE_VOICEOVER] == route
    assert route.adapter_name == TTSAdapter.adapter_name
    assert route.queue_topic == "audio.tts.voiceover"
    assert isinstance(adapter, TTSAdapter)

    try:
        resolve_route(GENERATE_VOICEOVER)
    except ValueError as exc:
        assert "No adapter route registered" in str(exc)
    else:
        raise AssertionError("P1 voiceover should not resolve through the default P0 route table")


def _request(
    input_payload: dict[str, Any],
    *,
    policy_context: dict[str, Any] | None = None,
) -> AdapterRequest:
    return AdapterRequest(
        context=AdapterContext(
            tenant_id="demo_tenant",
            project_id="proj_tts_contract",
            run_id="run_tts_contract",
            tool_call_id="tool_tts_contract",
            capability=GENERATE_VOICEOVER,
            policy_context=policy_context or {},
        ),
        input=input_payload,
    )


def _clear_model_env(monkeypatch) -> None:
    for env_var in (
        "VET_MOSS_TTS_NANO_MODEL_PATH",
        "VIDEO_TOOLKIT_MOSS_TTS_NANO_MODEL_PATH",
        "MOSS_TTS_NANO_MODEL_PATH",
    ):
        monkeypatch.delenv(env_var, raising=False)
