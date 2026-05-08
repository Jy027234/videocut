"""P1.1 deterministic video QC adapter contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import assert_no_public_path_or_command_leak
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
    GENERATE_QC_REPORT,
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
    assert report["severity_counts"] == {"pass": 6, "warning": 0, "blocking": 0}
    assert report["blocking_issues"] == []
    assert report["warnings"] == []
    assert {check["check_id"] for check in report["checks"]} == {
        "timeline.structure",
        "timeline.overlap",
        "subtitle.bounds",
        "media.drift",
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


def _run_qc(input_payload: dict[str, Any]):
    return QCAdapter().handle(
        AdapterRequest(
            context=AdapterContext(
                tenant_id="demo_tenant",
                project_id="demo_project",
                run_id="run_qc_contract",
                tool_call_id="tool_call_qc_contract",
                capability=GENERATE_QC_REPORT,
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
        "brand_kit": {
            "required_keywords": ["Acme"],
            "required_safe_area": {"left": 0.1, "right": 0.9, "top": 0.1, "bottom": 0.9},
        },
    }
