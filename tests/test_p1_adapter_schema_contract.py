"""P1.1 adapter outputs validate against the draft manifest schema refs."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Mapping

import pytest

from conftest import MANIFESTS_DIR, SCHEMAS_DIR, assert_no_public_path_or_command_leak, load_json
import video_editing_toolkit.adapters.tts as tts_adapter
from video_editing_toolkit.adapters import AdapterContext, AdapterRequest, AdapterResult, AdapterStatus
from video_editing_toolkit.adapters.audio_quality import AudioQualityAdapter
from video_editing_toolkit.adapters.ffmpeg import FFmpegAdapter
from video_editing_toolkit.adapters.opencv import OpenCVAdapter
from video_editing_toolkit.adapters.project_export import EXPORT_PROJECT_FORMAT, ProjectExportAdapter
from video_editing_toolkit.adapters.qc import (
    BUILD_QC_EVIDENCE_PACKET,
    GENERATE_MEDIA_INSPECTION_EVIDENCE,
    GENERATE_QC_REPORT,
    PLAN_MEDIA_INSPECTION,
    QCAdapter,
)
from video_editing_toolkit.adapters.remotion import (
    CREATE_REMOTION_RENDER_JOB,
    VALIDATE_REMOTION_TEMPLATE,
    RemotionAdapter,
)
from video_editing_toolkit.adapters.tts import GENERATE_VOICEOVER, TTSAdapter
from video_editing_toolkit.storage import LocalArtifactStore


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
            BUILD_QC_EVIDENCE_PACKET,
            QCAdapter().handle(_request(BUILD_QC_EVIDENCE_PACKET, _passing_qc_payload())),
        ),
        (
            PLAN_MEDIA_INSPECTION,
            QCAdapter().handle(_request(PLAN_MEDIA_INSPECTION, _qc_inspection_plan_payload())),
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
        (
            EXPORT_PROJECT_FORMAT,
            ProjectExportAdapter().handle(
                _request(EXPORT_PROJECT_FORMAT, _valid_project_export_payload())
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


def test_p1_qc_media_inspection_evidence_schema_accepts_caller_safe_artifacts() -> None:
    artifact_ref = _caller_safe_artifact_ref("qc_media_inspection_evidence_schema")
    output = {
        "media_inspection_evidence": {
            "schema": "video_editing_toolkit.qc_media_inspection_evidence.v0",
            "summary": {
                "status": "ready",
                "execution_enabled": True,
                "source_artifact_count": 1,
                "inspection_result_count": 1,
                "evidence_item_count": 1,
                "warning_count": 0,
            },
            "execution_policy": {
                "runtime_mode": "controlled_worker_execution",
                "execution_enabled": True,
                "artifact_ref_only": True,
                "network_access": "disabled_by_default",
                "return_local_paths": False,
                "allow_raw_command": False,
            },
            "source_artifact_refs": [_caller_safe_artifact_ref("source_video_schema")],
            "inspection_results": [
                {
                    "check_id": "media_integrity",
                    "status": "passed",
                    "severity": "pass",
                    "message": "Caller-safe media inspection evidence is present.",
                    "evidence_refs": [artifact_ref["artifact_id"]],
                    "details": {"duration_seconds": 5.0},
                }
            ],
            "evidence_items": [
                {
                    "evidence_id": "media_probe",
                    "evidence_type": "probe_summary",
                    "artifact_ref": artifact_ref,
                    "summary": {"stream_count": 2},
                }
            ],
            "warnings": [],
        },
        "qc_media_inspection_evidence_artifact_ref": artifact_ref,
        "artifact_refs": [artifact_ref],
    }

    assert_no_public_path_or_command_leak(output)
    _validate_output_against_p1_manifest_schema(GENERATE_MEDIA_INSPECTION_EVIDENCE, output)

    unsafe_output = output | {
        "qc_media_inspection_evidence_artifact_ref": artifact_ref | {
            "storage_uri": "s3://internal-bucket/qc.json"
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        _validate_output_against_p1_manifest_schema(GENERATE_MEDIA_INSPECTION_EVIDENCE, unsafe_output)


def test_p1_qc_media_inspection_evidence_adapter_output_validates_against_manifest_schema_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FFmpegAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"probe": {"duration_seconds": 1.0, "streams": [{"codec_type": "video"}]}},
        ),
    )
    monkeypatch.setattr(
        AudioQualityAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"quality_summary": {"duration_seconds": 1.0, "has_audio_stream": True}},
        ),
    )
    monkeypatch.setattr(
        OpenCVAdapter,
        "invoke",
        lambda self, request: AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={"quality_summary": {"mean_brightness": 100.0}},
        ),
    )

    result = QCAdapter().handle(
        AdapterRequest(
            context=AdapterContext(
                tenant_id="tenant_p1_schema",
                project_id="project_p1_schema",
                run_id="run_p1_schema",
                tool_call_id="tool_p1_schema",
                capability=GENERATE_MEDIA_INSPECTION_EVIDENCE,
                policy_context={"allow_p1_qc_media_inspection_execution": True},
            ),
            input={
                "_artifact_store": LocalArtifactStore(tmp_path / "artifacts"),
                "_worker_media_path": str(tmp_path / "private" / "source.mp4"),
                "artifact_ref": _caller_safe_artifact_ref("source_video_schema"),
            },
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert_no_public_path_or_command_leak(result.output)
    _validate_output_against_p1_manifest_schema(
        GENERATE_MEDIA_INSPECTION_EVIDENCE,
        result.output,
    )


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


def _qc_inspection_plan_payload() -> dict[str, Any]:
    return _passing_qc_payload() | {
        "artifact_ref": {
            "artifact_id": "artifact_qc_plan_schema",
            "artifact_type": "source_video",
            "mime_type": "video/mp4",
            "size_bytes": 1234,
            "checksum": "sha256:" + "a" * 64,
            "data_class": "sensitive",
            "retention_policy": "short_lived",
        },
        "media_probe": {
            "duration_seconds": 5.0,
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920},
                {"codec_type": "audio"},
            ],
        },
        "audio_quality": {"quality_summary": {"integrated_lufs": -16.0}},
        "visual_quality": {"summary": {"black_frame_seconds": 0}},
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
        "dispatcher_preflight_attestation": {
            "schema": "video_editing_toolkit.remotion_dispatcher_preflight_attestation.v0",
            "runtime": {
                "nodejs": "ready",
                "chromium": "ready",
                "remotion": "ready",
            },
            "sandbox": {
                "execution": "dispatcher_managed",
                "filesystem": "artifact_ref_only",
            },
            "network": {
                "egress": "deny_by_default",
            },
            "license": {
                "confirmed": True,
                "license_id": "remotion_team_license",
            },
            "execution": {
                "mode": "dispatcher_only",
                "execution_enabled": False,
            },
        },
    }


def _valid_project_export_payload() -> dict[str, Any]:
    return {
        "project_id": "proj_p1_schema_export",
        "format": "fcpxml",
        "timeline": {
            "tracks": {
                "v1": {
                    "kind": "video",
                    "clips": [
                        {
                            "clip_id": "clip_schema_video",
                            "kind": "video",
                            "start_seconds": 0,
                            "duration_seconds": 5,
                        }
                    ],
                }
            }
        },
    }


def _caller_safe_artifact_ref(artifact_id: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": "qc_media_inspection_evidence",
        "mime_type": "application/json",
        "size_bytes": 256,
        "checksum": "sha256:" + "b" * 64,
        "data_class": "medium",
        "retention_policy": "short_lived",
        "access_policy": "tenant_and_explicit_grants",
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
