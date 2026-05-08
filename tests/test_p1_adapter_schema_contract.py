"""P1.1 adapter outputs validate against the draft manifest schema refs."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Mapping

import pytest

from conftest import MANIFESTS_DIR, SCHEMAS_DIR, assert_no_public_path_or_command_leak, load_json
import video_editing_toolkit.adapters.tts as tts_adapter
from video_editing_toolkit.adapters import AdapterContext, AdapterRequest, AdapterStatus
from video_editing_toolkit.adapters.qc import GENERATE_QC_REPORT, QCAdapter
from video_editing_toolkit.adapters.remotion import (
    CREATE_REMOTION_RENDER_JOB,
    VALIDATE_REMOTION_TEMPLATE,
    RemotionAdapter,
)
from video_editing_toolkit.adapters.tts import GENERATE_VOICEOVER, TTSAdapter


jsonschema = pytest.importorskip("jsonschema")


def test_p1_adapter_outputs_validate_against_manifest_schema_refs() -> None:
    cases = [
        (
            GENERATE_VOICEOVER,
            TTSAdapter().handle(
                _request(
                    GENERATE_VOICEOVER,
                    {
                        "text": "Narrate a short five second highlight cut.",
                        "synthesis_mode": "plan_only",
                        "voice_preset": "default_narrator",
                    },
                )
            ),
        ),
        (
            GENERATE_QC_REPORT,
            QCAdapter().handle(_request(GENERATE_QC_REPORT, _passing_qc_payload())),
        ),
        (
            VALIDATE_REMOTION_TEMPLATE,
            RemotionAdapter().handle(
                _request(VALIDATE_REMOTION_TEMPLATE, _valid_remotion_payload())
            ),
        ),
        (
            CREATE_REMOTION_RENDER_JOB,
            RemotionAdapter().handle(
                _request(CREATE_REMOTION_RENDER_JOB, _valid_remotion_payload())
            ),
        ),
    ]

    for capability, result in cases:
        assert result.status == AdapterStatus.SUCCEEDED, capability
        assert_no_public_path_or_command_leak(result.output)
        _validate_output_against_p1_manifest_schema(capability, result.output)


def test_p1_voice_clone_output_validates_as_deferred_failure() -> None:
    result = TTSAdapter().handle(
        _request(
            GENERATE_VOICEOVER,
            {
                "text": "Try to clone a reference voice.",
                "dry_run": True,
                "voice_clone": True,
                "consent_policy": {"voice_clone_approved": True},
            },
        )
    )

    assert result.status == AdapterStatus.FAILED
    assert result.output["reason_code"] == "tts.voice_clone_deferred"
    assert_no_public_path_or_command_leak(result.output)
    _validate_output_against_p1_manifest_schema(GENERATE_VOICEOVER, result.output)


def test_p1_tts_preflight_output_validates_against_manifest_schema_refs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_fake_onnxruntime(monkeypatch)
    bundle_root = _complete_tts_fixture_bundle(tmp_path)
    result = TTSAdapter().handle(
        _request(
            GENERATE_VOICEOVER,
            {
                "synthesis_mode": "preflight_only",
                "model_root": str(bundle_root),
            },
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.output["runtime_preflight"]["status"] == "passed"
    assert_no_public_path_or_command_leak(result.output)
    assert str(bundle_root) not in str(result.output)
    _validate_output_against_p1_manifest_schema(GENERATE_VOICEOVER, result.output)


def _validate_output_against_p1_manifest_schema(
    capability: str,
    output: Mapping[str, Any],
) -> None:
    manifest = load_json(MANIFESTS_DIR / "video-editing-toolkit.p1.manifest.json")
    capability_entry = next(
        item for item in manifest["capabilities"] if item["capability"] == capability
    )
    ref = capability_entry["output_schema"]["$ref"]
    document_ref, _separator, fragment = ref.partition("#")
    schema_path = (MANIFESTS_DIR / document_ref).resolve()
    assert schema_path == (SCHEMAS_DIR / "capability-io.schema.json").resolve()

    schema = load_json(schema_path)
    contract_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#{fragment}",
    }
    validator_cls = jsonschema.validators.validator_for(contract_schema)
    validator_cls.check_schema(contract_schema)
    validator_cls(contract_schema).validate(output)


def _request(capability: str, input_payload: dict[str, Any]) -> AdapterRequest:
    return AdapterRequest(
        context=AdapterContext(
            tenant_id="tenant_p1_schema",
            project_id="project_p1_schema",
            run_id="run_p1_schema",
            tool_call_id="tool_p1_schema",
            capability=capability,
        ),
        input=input_payload,
    )


def _passing_qc_payload() -> dict[str, Any]:
    return {
        "composition_plan": {
            "summary": {
                "video_duration_seconds": 5.0,
                "audio_duration_seconds": 5.0,
                "duration_seconds": 5.0,
            },
            "errors": [],
            "warnings": [],
            "text_overlays": [
                {
                    "text": "Acme launch",
                    "style": {"normalized_bbox": [0.2, 0.2, 0.5, 0.1]},
                }
            ],
        },
        "subtitles": [{"start_seconds": 0.2, "end_seconds": 2.0, "text": "Welcome to Acme"}],
        "brand_kit": {
            "required_keywords": ["Acme"],
            "required_safe_area": {"left": 0.1, "right": 0.9, "top": 0.1, "bottom": 0.9},
        },
    }


def _valid_remotion_payload() -> dict[str, Any]:
    return {
        "template_manifest": {
            "template_id": "brand-fastflash",
            "version": "1.0.0",
            "compositions": [
                {
                    "composition_id": "Main",
                    "duration_frames": 150,
                    "fps": 30,
                    "width": 1080,
                    "height": 1920,
                    "default_props": {"caption": "Launch"},
                    "props_schema": {
                        "type": "object",
                        "required": ["caption", "brand_color"],
                        "additionalProperties": False,
                        "properties": {
                            "caption": {"type": "string"},
                            "brand_color": {"type": "string"},
                        },
                    },
                }
            ],
        },
        "composition_id": "Main",
        "props": {"brand_color": "#31A8FF"},
    }


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
