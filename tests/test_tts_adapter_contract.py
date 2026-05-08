"""P1.1 MOSS-TTS-Nano voiceover adapter contract checks."""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import video_editing_toolkit.adapters.tts as tts_adapter
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


def test_tts_preflight_blocks_when_runtime_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_model_env(monkeypatch)
    bundle_root = _complete_tts_fixture_bundle(tmp_path)

    def missing_runtime(name: str):
        if name == "onnxruntime":
            raise ImportError("fixture missing runtime")
        return __import__(name)

    monkeypatch.setattr(tts_adapter.importlib, "import_module", missing_runtime)
    adapter = TTSAdapter()

    result = adapter.handle(
        _request(
            {
                "synthesis_mode": "preflight_only",
                "model_root": str(bundle_root),
            }
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    preflight = result.output["runtime_preflight"]
    assert preflight["status"] == "blocked"
    assert preflight["reason_code"] == "tts.onnxruntime_missing"
    assert result.output["model_runtime"]["execution_enabled"] is False
    assert result.output["audio_artifact_ref"] is None
    assert_no_public_path_or_command_leak(result.output)
    assert str(bundle_root) not in json.dumps(result.output, sort_keys=True)


def test_tts_preflight_blocks_when_bundles_missing(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    _install_fake_onnxruntime(monkeypatch)
    adapter = TTSAdapter()

    result = adapter.handle(_request({"preflight_only": True}))

    assert result.status == AdapterStatus.SUCCEEDED
    preflight = result.output["runtime_preflight"]
    assert preflight["status"] == "blocked"
    assert preflight["reason_code"] == "tts.tts_bundle_unconfigured"
    assert preflight["bundle_summary"]["configured"] is False
    assert preflight["bundle_summary"]["tts_bundle"]["configured"] is False
    assert preflight["bundle_summary"]["codec_bundle"]["configured"] is False
    assert_no_public_path_or_command_leak(result.output)


def test_tts_preflight_blocks_when_fixture_bundle_incomplete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_model_env(monkeypatch)
    _install_fake_onnxruntime(monkeypatch)
    bundle_root = tmp_path / "moss-tts-nano"
    tts_bundle = bundle_root / tts_adapter._TTS_BUNDLE_DIRNAME
    codec_bundle = bundle_root / tts_adapter._CODEC_BUNDLE_DIRNAME
    tts_bundle.mkdir(parents=True)
    codec_bundle.mkdir(parents=True)
    (tts_bundle / tts_adapter._TTS_BUNDLE_REQUIRED_FILES[0]).touch()
    (codec_bundle / tts_adapter._CODEC_BUNDLE_REQUIRED_FILES[0]).touch()
    adapter = TTSAdapter()

    result = adapter.handle(
        _request(
            {
                "synthesis_mode": "preflight_only",
                "model_root": str(bundle_root),
            }
        )
    )

    preflight = result.output["runtime_preflight"]
    assert preflight["status"] == "blocked"
    assert preflight["reason_code"] == "tts.tts_bundle_incomplete"
    assert preflight["bundle_summary"]["tts_bundle"]["present_file_count"] == 1
    assert preflight["bundle_summary"]["codec_bundle"]["present_file_count"] == 1
    assert "tokenizer.model" in preflight["bundle_summary"]["tts_bundle"]["missing_required_files"]
    assert_no_public_path_or_command_leak(result.output)
    assert str(bundle_root) not in json.dumps(result.output, sort_keys=True)


def test_tts_preflight_passes_with_complete_fixture_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_model_env(monkeypatch)
    _install_fake_onnxruntime(monkeypatch)
    bundle_root = _complete_tts_fixture_bundle(tmp_path)
    adapter = TTSAdapter()

    result = adapter.handle(
        _request(
            {
                "synthesis_mode": "preflight_only",
                "model_root": str(bundle_root),
            }
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    preflight = result.output["runtime_preflight"]
    assert preflight["status"] == "passed"
    assert preflight["reason_code"] == "tts.preflight_passed"
    assert preflight["execution_enabled"] is False
    assert result.output["model_runtime"]["execution_enabled"] is False
    assert preflight["bundle_summary"]["configured"] is True
    assert preflight["bundle_summary"]["tts_bundle"]["complete"] is True
    assert preflight["bundle_summary"]["codec_bundle"]["complete"] is True
    assert all(check["status"] == "passed" for check in preflight["checks"])
    assert_no_public_path_or_command_leak(result.output)
    assert str(bundle_root) not in json.dumps(result.output, sort_keys=True)


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
        "VET_MOSS_TTS_NANO_MODEL_ROOT",
        "VIDEO_TOOLKIT_MOSS_TTS_NANO_MODEL_ROOT",
        "MOSS_TTS_NANO_MODEL_ROOT",
        "VET_MOSS_TTS_NANO_TTS_BUNDLE",
        "VIDEO_TOOLKIT_MOSS_TTS_NANO_TTS_BUNDLE",
        "MOSS_TTS_NANO_TTS_BUNDLE",
        "VET_MOSS_TTS_NANO_CODEC_BUNDLE",
        "VIDEO_TOOLKIT_MOSS_TTS_NANO_CODEC_BUNDLE",
        "MOSS_TTS_NANO_CODEC_BUNDLE",
    ):
        monkeypatch.delenv(env_var, raising=False)


def _install_fake_onnxruntime(monkeypatch) -> None:
    fake_runtime = types.SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"])

    def import_module(name: str):
        if name == "onnxruntime":
            return fake_runtime
        return __import__(name)

    monkeypatch.setattr(tts_adapter.importlib, "import_module", import_module)


def _complete_tts_fixture_bundle(tmp_path: Path) -> Path:
    bundle_root = tmp_path / "moss-tts-nano"
    required_files = {
        tts_adapter._TTS_BUNDLE_DIRNAME: tts_adapter._TTS_BUNDLE_REQUIRED_FILES,
        tts_adapter._CODEC_BUNDLE_DIRNAME: tts_adapter._CODEC_BUNDLE_REQUIRED_FILES,
    }
    for folder, filenames in required_files.items():
        bundle_dir = bundle_root / folder
        bundle_dir.mkdir(parents=True)
        for filename in filenames:
            (bundle_dir / filename).touch()
    return bundle_root
