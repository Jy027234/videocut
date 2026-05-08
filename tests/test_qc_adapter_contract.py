"""P1.1 deterministic video QC adapter contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import MANIFESTS_DIR, assert_no_public_path_or_command_leak, load_json
from video_editing_toolkit.adapters import (
    AdapterContext,
    AdapterRequest,
    AdapterStatus,
    QCAdapter,
    build_p1_experimental_adapter,
    resolve_p1_experimental_route,
    resolve_route,
)
from video_editing_toolkit.adapters.qc import (
    BUILD_QC_EVIDENCE_PACKET,
    QC_EVIDENCE_PACKET_ARTIFACT_TYPE,
    QC_EVIDENCE_PACKET_SCHEMA,
    GENERATE_QC_REPORT,
    PLAN_MEDIA_INSPECTION,
    QC_MEDIA_INSPECTION_PLAN_SCHEMA,
    QC_REPORT_ARTIFACT_TYPE,
    QC_REPORT_SCHEMA,
)
from video_editing_toolkit.adapters.routing import CAPABILITY_ROUTES, P1_CAPABILITY_ROUTES
from video_editing_toolkit.storage import LocalArtifactStore


def test_qc_report_passes_clean_timeline_subtitles_and_brand_rules() -> None:
    result = _run_qc(_passing_payload())

    assert result.status == AdapterStatus.SUCCEEDED
    report = result.output["qc_report"]
    assert report["schema"] == QC_REPORT_SCHEMA
    assert report["summary"]["status"] == "pass"
    assert report["severity_counts"] == {"pass": 10, "warning": 0, "blocking": 0}
    assert report["blocking_issues"] == []
    assert report["warnings"] == []
    assert {check["check_id"] for check in report["checks"]} == {
        "timeline.structure",
        "timeline.overlap",
        "subtitle.bounds",
        "media.drift",
        "media.integrity",
        "media.delivery_profile",
        "audio.loudness",
        "visual.sampling",
        "brand.keywords",
        "brand.safe_area",
    }
    assert_no_public_path_or_command_leak(result.output)


def test_qc_report_warns_for_overlap_drift_and_missing_brand_keyword() -> None:
    payload = {
        "timeline": {
            "tracks": {
                "v1": {
                    "kind": "video",
                    "clips": [
                        {"clip_id": "clip_1", "timeline_start_seconds": 0, "duration_seconds": 4},
                        {"clip_id": "clip_2", "timeline_start_seconds": 3, "duration_seconds": 2},
                    ],
                }
            }
        },
        "composition_plan": {
            "summary": {
                "video_duration_seconds": 5.0,
                "audio_duration_seconds": 6.2,
                "duration_seconds": 6.2,
            },
            "warnings": [],
            "errors": [],
        },
        "subtitles": [{"start_seconds": 0.0, "end_seconds": 1.4, "text": "Launch today"}],
        "brand_kit": {"required_keywords": ["Acme"]},
    }

    result = _run_qc(payload)

    assert result.status == AdapterStatus.SUCCEEDED
    report = result.output["qc_report"]
    assert report["summary"]["status"] == "warning"
    assert report["severity_counts"]["blocking"] == 0
    warning_ids = {check["check_id"] for check in report["warnings"]}
    assert {"timeline.overlap", "media.drift", "brand.keywords"}.issubset(warning_ids)
    assert report["summary"]["warning_count"] == 3
    assert_no_public_path_or_command_leak(result.output)


def test_qc_report_blocks_for_timeline_subtitle_keyword_and_safe_area_errors() -> None:
    payload = {
        "timeline": {
            "tracks": {
                "v1": {
                    "kind": "video",
                    "clips": [
                        {
                            "clip_id": "clip_bad",
                            "timeline_start_seconds": 0.0,
                            "duration_seconds": -1.0,
                        }
                    ],
                }
            }
        },
        "composition_plan": {
            "summary": {
                "video_duration_seconds": 5.0,
                "audio_duration_seconds": 5.0,
                "duration_seconds": 5.0,
            },
            "errors": [{"code": "negative_duration"}],
            "warnings": [],
            "text_overlays": [
                {
                    "clip_id": "title_bad",
                    "text": "Banned launch",
                    "style": {"normalized_bbox": [0.02, 0.2, 0.3, 0.2]},
                }
            ],
        },
        "subtitles": [{"start_seconds": 4.5, "end_seconds": 6.0, "text": "Banned launch"}],
        "brand_kit": {
            "forbidden_keywords": ["banned"],
            "required_safe_area": {"left": 0.1, "right": 0.9, "top": 0.1, "bottom": 0.9},
        },
    }

    result = _run_qc(payload)

    assert result.status == AdapterStatus.SUCCEEDED
    report = result.output["qc_report"]
    assert report["summary"]["status"] == "blocking"
    blocking_ids = {check["check_id"] for check in report["blocking_issues"]}
    assert {
        "timeline.structure",
        "subtitle.bounds",
        "brand.keywords",
        "brand.safe_area",
    }.issubset(blocking_ids)
    assert report["severity_counts"]["blocking"] == 4
    assert_no_public_path_or_command_leak(result.output)


def test_qc_report_writes_artifact_when_store_is_available(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
    )
    payload = _passing_payload() | {
        "_artifact_store": artifact_store,
        "_worker_media_path": str(tmp_path / "private-input.mp4"),
    }

    result = _run_qc(payload)

    assert result.status == AdapterStatus.SUCCEEDED
    assert len(result.artifact_refs) == 1
    artifact_ref = result.artifact_refs[0]
    assert artifact_ref.artifact_type == QC_REPORT_ARTIFACT_TYPE
    assert result.output["qc_report_artifact_ref"]["artifact_id"] == artifact_ref.artifact_id
    assert "storage_uri" not in result.output["qc_report_artifact_ref"]

    report_path = artifact_store.open_local_path(artifact_ref.artifact_id)
    assert report_path is not None
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["schema"] == QC_REPORT_SCHEMA
    assert report_payload["summary"]["status"] == "pass"
    assert_no_public_path_or_command_leak(result.output)
    assert str(tmp_path) not in json.dumps(result.output, sort_keys=True)


def test_qc_report_warns_from_production_quality_evidence_without_path_leaks() -> None:
    payload = _passing_payload() | {
        "_worker_media_path": r"C:\private\customer\raw\launch.mp4",
        "media_probe": {
            "duration_seconds": 10.1,
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1080, "avg_frame_rate": "24/1"},
                {"codec_type": "audio"},
            ],
        },
        "delivery_targets": {
            "platform_profile": {
                "aspect_ratio": "9:16",
                "min_width": 1080,
                "min_height": 1920,
                "min_fps": 29.97,
                "max_duration_seconds": 60,
                "min_lufs": -20,
                "max_lufs": -14,
                "max_true_peak_dbtp": -1,
                "max_silence_ratio": 0.1,
            }
        },
        "audio_quality": {
            "quality_summary": {"duration_seconds": 10.1, "integrated_lufs": -25.0, "true_peak_dbtp": -2.0},
            "silence_ratio": 0.15,
        },
        "visual_quality": {
            "quality_summary": {"duration_seconds": 10.0},
            "black_frames": [{"start_seconds": 2.0, "duration_seconds": 0.2}],
            "low_light_ratio": 0.25,
        },
    }

    result = _run_qc(payload)

    assert result.status == AdapterStatus.SUCCEEDED
    report = result.output["qc_report"]
    assert report["summary"]["status"] == "warning"
    warning_ids = {check["check_id"] for check in report["warnings"]}
    assert {
        "media.delivery_profile",
        "audio.loudness",
        "visual.sampling",
    }.issubset(warning_ids)
    assert "media.integrity" not in warning_ids
    assert report["severity_counts"]["blocking"] == 0
    assert_no_public_path_or_command_leak(result.output)
    assert "private" not in json.dumps(result.output, sort_keys=True).casefold()


def test_qc_report_blocks_from_probe_loudness_and_visual_sampling_evidence() -> None:
    payload = _passing_payload() | {
        "_worker_media_path": "/mnt/private/customer/raw/launch.mp4",
        "media_probe": {
            "duration_seconds": 0,
            "errors": [{"code": "decode_failure", "path": "/mnt/private/customer/raw/launch.mp4"}],
            "streams": [{"codec_type": "audio"}],
        },
        "audio_quality": {
            "quality_summary": {
                "duration_seconds": 10.1,
                "integrated_lufs": -16.0,
                "true_peak_dbtp": 0.4,
            },
            "silence_ratio": 0.65,
        },
        "visual_quality": {
            "quality_summary": {"duration_seconds": 10.0},
            "black_frame_seconds": 3.0,
            "freeze_frame_seconds": 3.5,
        },
    }

    result = _run_qc(payload)

    assert result.status == AdapterStatus.SUCCEEDED
    report = result.output["qc_report"]
    assert report["summary"]["status"] == "blocking"
    blocking_ids = {check["check_id"] for check in report["blocking_issues"]}
    assert {"media.integrity", "audio.loudness", "visual.sampling"}.issubset(blocking_ids)
    assert_no_public_path_or_command_leak(result.output)
    output_json = json.dumps(result.output, sort_keys=True)
    assert "/mnt/private" not in output_json
    assert "launch.mp4" not in output_json


def test_qc_evidence_packet_summarizes_caller_safe_sources() -> None:
    result = _run_qc(_passing_payload(), capability=BUILD_QC_EVIDENCE_PACKET)

    assert result.status == AdapterStatus.SUCCEEDED
    packet = result.output["qc_evidence_packet"]
    assert packet["schema"] == QC_EVIDENCE_PACKET_SCHEMA
    assert packet["summary"]["status"] == "ready"
    assert packet["summary"]["section_count"] == 7
    assert packet["summary"]["present_source_count"] == 7
    assert packet["summary"]["missing_source_count"] == 0
    assert packet["summary"]["duration_seconds"] == 10.1
    assert packet["summary"]["profile"] == "1080x1920"
    assert packet["duration_summary"]["probe_duration_seconds"] == 10.1
    assert packet["duration_summary"]["video_duration_seconds"] == 10.0
    assert packet["profile_summary"]["width"] == 1080.0
    assert packet["profile_summary"]["height"] == 1920.0
    assert packet["source_coverage"]["coverage_ratio"] == 1.0
    assert set(packet["source_coverage"]["present_sources"]) == {
        "media_probe",
        "audio_quality",
        "visual_quality",
        "timeline",
        "subtitles",
        "brand_kit",
        "delivery_targets",
    }
    assert "media_probe.duration_seconds" in packet["evidence_refs"]
    assert "delivery_targets.platform_profile" in packet["evidence_refs"]
    assert_no_public_path_or_command_leak(result.output)


def test_qc_evidence_packet_writes_artifact_when_store_is_available(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
        signing_secret="signed-packet-secret",
    )
    payload = _passing_payload() | {"_artifact_store": artifact_store}

    result = _run_qc(payload, capability=BUILD_QC_EVIDENCE_PACKET)

    assert result.status == AdapterStatus.SUCCEEDED
    assert len(result.artifact_refs) == 1
    artifact_ref = result.artifact_refs[0]
    assert artifact_ref.artifact_type == QC_EVIDENCE_PACKET_ARTIFACT_TYPE
    assert result.output["qc_evidence_packet_artifact_ref"]["artifact_id"] == artifact_ref.artifact_id
    assert "storage_uri" not in result.output["qc_evidence_packet_artifact_ref"]
    assert "download_url" not in result.output["qc_evidence_packet_artifact_ref"]

    packet_path = artifact_store.open_local_path(artifact_ref.artifact_id)
    assert packet_path is not None
    packet_payload = json.loads(packet_path.read_text(encoding="utf-8"))
    assert packet_payload["schema"] == QC_EVIDENCE_PACKET_SCHEMA
    assert packet_payload["summary"]["status"] == "ready"
    assert_no_public_path_or_command_leak(packet_payload)
    assert_no_public_path_or_command_leak(result.output)
    assert str(tmp_path) not in json.dumps(result.output, sort_keys=True)


def test_qc_evidence_packet_omits_path_storage_and_download_token_inputs(tmp_path: Path) -> None:
    payload = _passing_payload() | {
        "_worker_media_path": str(tmp_path / "private" / "launch.mp4"),
        "media_probe": {
            "duration_seconds": 10.1,
            "storage_uri": "s3://internal-bucket/private/launch.mp4",
            "download_url": "https://download.example/private/launch.mp4?sat=secret-token",
            "errors": [
                {
                    "code": "decode_failure",
                    "path": str(tmp_path / "private" / "launch.mp4"),
                }
            ],
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
        },
        "delivery_targets": {
            "platform_profile": {
                "name": str(tmp_path / "profiles" / "internal.json"),
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
            }
        },
    }

    result = _run_qc(payload, capability=BUILD_QC_EVIDENCE_PACKET)

    assert result.status == AdapterStatus.SUCCEEDED
    rendered = json.dumps(result.output, sort_keys=True)
    assert_no_public_path_or_command_leak(result.output)
    assert "_worker_media_path" not in rendered
    assert "storage_uri" not in rendered
    assert "download.example" not in rendered
    assert "secret-token" not in rendered
    assert "launch.mp4" not in rendered
    assert str(tmp_path) not in rendered
    assert result.output["qc_evidence_packet"]["summary"]["profile"] == "1080x1920"


def test_qc_media_inspection_plan_is_plan_only_and_caller_safe(tmp_path: Path) -> None:
    artifact_ref = {
        "artifact_id": "artifact_qc_plan_source",
        "artifact_type": "source_video",
        "mime_type": "video/mp4",
        "size_bytes": 1234,
        "checksum": "sha256:" + "a" * 64,
        "data_class": "sensitive",
        "retention_policy": "short_lived",
        "storage_uri": "s3://internal/private/source.mp4",
        "download_url": "https://download.example/source.mp4?sat=secret-token",
    }
    payload = _passing_payload() | {
        "_worker_media_path": str(tmp_path / "private" / "source.mp4"),
        "artifact_ref": artifact_ref,
        "media_probe": {
            "duration_seconds": 10.1,
            "storage_uri": "s3://internal/private/probe.json",
            "download_url": "https://download.example/probe.json?sat=secret-token",
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
        },
        "audio_quality": {"quality_summary": {"integrated_lufs": -16.0, "true_peak_dbtp": -1.2}},
        "visual_quality": {"summary": {"black_frame_seconds": 0.0, "freeze_frame_seconds": 0.0}},
    }

    result = _run_qc(payload, capability=PLAN_MEDIA_INSPECTION)
    rendered = json.dumps(result.output, sort_keys=True)

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.artifact_refs == ()
    plan = result.output["media_inspection_plan"]
    assert plan["schema"] == QC_MEDIA_INSPECTION_PLAN_SCHEMA
    assert plan["summary"]["plan_only"] is True
    assert plan["summary"]["execution_enabled"] is False
    assert plan["execution_policy"]["runtime_mode"] == "plan_only"
    assert plan["execution_policy"]["media_fetch_enabled"] is False
    assert plan["execution_policy"]["binary_probe_enabled"] is False
    assert plan["execution_policy"]["frame_sampling_enabled"] is False
    assert all(value == 0 for value in plan["runtime_invocation_counts"].values())
    assert plan["source_artifact_refs"] == [
        {
            "artifact_id": "artifact_qc_plan_source",
            "artifact_type": "source_video",
            "mime_type": "video/mp4",
            "size_bytes": 1234,
            "checksum": "sha256:" + "a" * 64,
            "data_class": "sensitive",
            "retention_policy": "short_lived",
        }
    ]
    assert "ffmpeg" not in rendered.casefold()
    assert "opencv" not in rendered.casefold()
    assert "download_url" not in rendered
    assert "download.example" not in rendered
    assert "secret-token" not in rendered
    assert "storage_uri" not in rendered
    assert "source.mp4" not in rendered
    assert str(tmp_path) not in rendered
    assert_no_public_path_or_command_leak(result.output)


def test_qc_media_inspection_plan_matches_manifest_no_download_policy() -> None:
    manifest = load_json(MANIFESTS_DIR / "video-editing-toolkit.p1.manifest.json")
    entry = next(
        capability
        for capability in manifest["capabilities"]
        if capability["capability"] == PLAN_MEDIA_INSPECTION
    )

    assert entry["status"] == "disabled"
    assert entry["sandbox_policy"]["p1_5_runtime_mode"] == "plan_only"
    assert entry["sandbox_policy"]["download_media"] is False
    assert entry["sandbox_policy"]["run_ffmpeg"] is False
    assert entry["sandbox_policy"]["run_opencv"] is False

    result = _run_qc(_passing_payload(), capability=PLAN_MEDIA_INSPECTION)
    plan = result.output["media_inspection_plan"]
    assert result.artifact_refs == ()
    assert plan["execution_policy"]["media_fetch_enabled"] is False
    assert plan["execution_policy"]["materialize_artifacts"] is False
    assert plan["execution_policy"]["binary_probe_enabled"] is False
    assert plan["execution_policy"]["frame_sampling_enabled"] is False
    assert all(value == 0 for value in plan["runtime_invocation_counts"].values())
    assert_no_public_path_or_command_leak(result.output)


def test_qc_build_evidence_packet_resolves_through_p1_route() -> None:
    route = resolve_p1_experimental_route(BUILD_QC_EVIDENCE_PACKET)
    adapter = build_p1_experimental_adapter(BUILD_QC_EVIDENCE_PACKET)

    assert BUILD_QC_EVIDENCE_PACKET not in CAPABILITY_ROUTES
    assert BUILD_QC_EVIDENCE_PACKET in P1_CAPABILITY_ROUTES
    assert route.adapter_name == QCAdapter.adapter_name
    assert route.adapter_class is QCAdapter
    assert route.queue_topic == "video.qc.evidence"
    assert adapter.adapter_name == "qc"
    assert adapter.supports(BUILD_QC_EVIDENCE_PACKET)

    try:
        resolve_route(BUILD_QC_EVIDENCE_PACKET)
    except ValueError as exc:
        assert "No adapter route registered" in str(exc)
    else:
        raise AssertionError("P1 QC should not resolve through the default P0 route table")


def test_qc_generate_report_resolves_through_p1_route() -> None:
    route = resolve_p1_experimental_route(GENERATE_QC_REPORT)
    adapter = build_p1_experimental_adapter(GENERATE_QC_REPORT)

    assert GENERATE_QC_REPORT not in CAPABILITY_ROUTES
    assert GENERATE_QC_REPORT in P1_CAPABILITY_ROUTES
    assert route.adapter_name == QCAdapter.adapter_name
    assert route.adapter_class is QCAdapter
    assert route.queue_topic == "video.qc.report"
    assert adapter.adapter_name == "qc"
    assert adapter.supports(GENERATE_QC_REPORT)

    try:
        resolve_route(GENERATE_QC_REPORT)
    except ValueError as exc:
        assert "No adapter route registered" in str(exc)
    else:
        raise AssertionError("P1 QC should not resolve through the default P0 route table")


def test_qc_media_inspection_plan_resolves_through_p1_route() -> None:
    route = resolve_p1_experimental_route(PLAN_MEDIA_INSPECTION)
    adapter = build_p1_experimental_adapter(PLAN_MEDIA_INSPECTION)

    assert PLAN_MEDIA_INSPECTION not in CAPABILITY_ROUTES
    assert PLAN_MEDIA_INSPECTION in P1_CAPABILITY_ROUTES
    assert route.adapter_name == QCAdapter.adapter_name
    assert route.adapter_class is QCAdapter
    assert route.queue_topic == "video.qc.inspection_plan"
    assert adapter.adapter_name == "qc"
    assert adapter.supports(PLAN_MEDIA_INSPECTION)

    try:
        resolve_route(PLAN_MEDIA_INSPECTION)
    except ValueError as exc:
        assert "No adapter route registered" in str(exc)
    else:
        raise AssertionError("P1 QC plan should not resolve through the default P0 route table")


def _run_qc(input_payload: dict[str, Any], *, capability: str = GENERATE_QC_REPORT):
    return QCAdapter().handle(
        AdapterRequest(
            context=AdapterContext(
                tenant_id="demo_tenant",
                project_id="demo_project",
                run_id="run_qc_contract",
                tool_call_id="tool_call_qc_contract",
                capability=capability,
            ),
            input=input_payload,
        )
    )


def _passing_payload() -> dict[str, Any]:
    return {
        "composition_plan": {
            "summary": {
                "video_duration_seconds": 10.0,
                "audio_duration_seconds": 10.1,
                "duration_seconds": 10.1,
            },
            "errors": [],
            "warnings": [],
            "text_overlays": [
                {
                    "clip_id": "title_1",
                    "text": "Acme launch",
                    "style": {"normalized_bbox": [0.2, 0.2, 0.5, 0.1]},
                }
            ],
        },
        "subtitles": [{"start_seconds": 0.2, "end_seconds": 2.0, "text": "Welcome to Acme"}],
        "audio_quality": {"quality_summary": {"duration_seconds": 10.1}},
        "visual_quality": {"quality_summary": {"duration_seconds": 10.0}},
        "media_probe": {
            "duration_seconds": 10.1,
            "streams": [
                {"codec_type": "video", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
        },
        "delivery_targets": {
            "platform_profile": {
                "aspect_ratio": "9:16",
                "width": 1080,
                "height": 1920,
                "min_fps": 29.97,
                "max_fps": 30.0,
                "max_duration_seconds": 60.0,
                "min_lufs": -24.0,
                "max_lufs": -12.0,
                "max_true_peak_dbtp": -1.0,
                "max_silence_ratio": 0.2,
            }
        },
        "brand_kit": {
            "required_keywords": ["Acme"],
            "required_safe_area": {"left": 0.1, "right": 0.9, "top": 0.1, "bottom": 0.9},
        },
    }
