"""P1 project export adapter contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.adapters import (
    AdapterContext,
    AdapterRequest,
    AdapterStatus,
    ProjectExportAdapter,
    build_p1_experimental_adapter,
    resolve_p1_experimental_route,
    resolve_route,
)
from video_editing_toolkit.adapters.project_export import (
    EXPORT_PROJECT_FORMAT,
    FCPXML_SCHEMA,
    PROJECT_EXPORT_FCPXML_ARTIFACT_TYPE,
    PROJECT_EXPORT_SCHEMA,
)
from video_editing_toolkit.adapters.routing import CAPABILITY_ROUTES, P1_CAPABILITY_ROUTES
from video_editing_toolkit.storage import LocalArtifactStore


def test_project_export_generates_caller_safe_fcpxml_string() -> None:
    result = ProjectExportAdapter().handle(_request(_timeline_payload(export_format="fcpxml")))

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.output["schema"] == PROJECT_EXPORT_SCHEMA
    assert result.output["format"] == "fcpxml"
    assert result.output["fcpxml_schema"] == FCPXML_SCHEMA
    assert result.output["project_id"] == "proj_project_export"
    assert result.output["timeline_summary"] == {
        "duration_seconds": 5.0,
        "track_count": 3,
        "clip_count": 3,
        "video_clip_count": 1,
        "audio_clip_count": 1,
        "text_clip_count": 1,
    }
    root = ET.fromstring(result.output["fcpxml"])
    assert root.tag == "fcpxml"
    assert root.attrib["version"] == "1.10"
    assert root.find("./library/event/project/sequence/spine") is not None
    assert result.usage_metrics["shell_invocations"] == 0
    assert result.usage_metrics["davinci_api_invocations"] == 0
    assert_no_public_path_or_command_leak(result.output)


def test_project_export_writes_fcpxml_artifact_when_store_is_available(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
        signing_secret="signed-project-export-secret",
    )
    payload = _timeline_payload(format="fcpxml") | {"_artifact_store": artifact_store}

    result = ProjectExportAdapter().handle(_request(payload))

    assert result.status == AdapterStatus.SUCCEEDED
    assert "fcpxml" not in result.output
    assert len(result.artifact_refs) == 1
    artifact_ref = result.artifact_refs[0]
    assert artifact_ref.artifact_type == PROJECT_EXPORT_FCPXML_ARTIFACT_TYPE
    assert result.output["project_export_artifact_ref"]["artifact_id"] == artifact_ref.artifact_id
    assert "storage_uri" not in result.output["project_export_artifact_ref"]
    assert "download_url" not in result.output["project_export_artifact_ref"]

    artifact_path = artifact_store.open_local_path(artifact_ref.artifact_id)
    assert artifact_path is not None
    assert artifact_path.name == "project.fcpxml"
    root = ET.fromstring(artifact_path.read_text(encoding="utf-8"))
    assert root.tag == "fcpxml"
    assert_no_public_path_or_command_leak(result.output)
    assert str(tmp_path) not in json.dumps(result.output, sort_keys=True)


def test_project_export_rejects_unsupported_format() -> None:
    result = ProjectExportAdapter().handle(_request(_timeline_payload(format="drp")))

    assert result.status == AdapterStatus.FAILED
    assert result.error_code == "request.invalid"
    assert result.output["stable_error_code"] == "project_export.unsupported_format"
    assert_no_public_path_or_command_leak(result.output)


def test_project_export_rejects_path_command_and_app_automation_inputs() -> None:
    unsafe_cases = [
        {"timeline": {"tracks": {"v1": {"clips": [{"clip_id": "clip_1", "local_path": "/mnt/private/a.mov"}]}}}},
        {"raw_command": "ffmpeg -i input.mov out.fcpxml"},
        {"davinci_api_call": {"method": "ExportProject", "args": []}},
        {"final_cut_automation": "osascript tell application Final Cut Pro"},
        {"timeline": {"tracks": {"v1": {"clips": [{"clip_id": "clip_1", "asset_ref": "C:\\private\\clip.mov"}]}}}},
    ]

    for unsafe_payload in unsafe_cases:
        payload = _timeline_payload() | unsafe_payload
        result = ProjectExportAdapter().handle(_request(payload))

        assert result.status == AdapterStatus.FAILED
        assert result.error_code == "request.invalid"
        assert result.output["stable_error_code"] == "project_export.unsafe_payload"
        assert_no_public_path_or_command_leak(result.output)


def test_project_export_can_export_from_composition_plan() -> None:
    payload = {
        "project_id": "proj_from_plan",
        "export_format": "fcpxml",
        "composition_plan": {
            "tracks": [
                {
                    "track_id": "video_main",
                    "kind": "video",
                    "clips": [{"clip_id": "clip_plan", "kind": "video", "start_seconds": 0, "duration_seconds": 2}],
                }
            ]
        },
    }

    result = ProjectExportAdapter().handle(_request(payload))

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.output["project_id"] == "proj_from_plan"
    assert result.output["timeline_summary"]["clip_count"] == 1
    assert result.output["warnings"] == [
        {
            "code": "composition_plan_used",
            "message": "Export was generated from composition_plan tracks.",
        }
    ]
    assert ET.fromstring(result.output["fcpxml"]).tag == "fcpxml"
    assert_no_public_path_or_command_leak(result.output)


def test_project_export_resolves_through_p1_experimental_route_only() -> None:
    route = resolve_p1_experimental_route(EXPORT_PROJECT_FORMAT)
    adapter = build_p1_experimental_adapter(EXPORT_PROJECT_FORMAT)

    assert EXPORT_PROJECT_FORMAT not in CAPABILITY_ROUTES
    assert EXPORT_PROJECT_FORMAT in P1_CAPABILITY_ROUTES
    assert route.adapter_name == ProjectExportAdapter.adapter_name
    assert route.adapter_class is ProjectExportAdapter
    assert route.queue_topic == "video.render.project_export"
    assert isinstance(adapter, ProjectExportAdapter)
    assert adapter.supports(EXPORT_PROJECT_FORMAT)

    try:
        resolve_route(EXPORT_PROJECT_FORMAT)
    except ValueError as exc:
        assert "No adapter route registered" in str(exc)
    else:
        raise AssertionError("P1 project export should not resolve through the default P0 route table")


def _request(input_payload: dict[str, object]) -> AdapterRequest:
    return AdapterRequest(
        context=AdapterContext(
            tenant_id="tenant_project_export",
            project_id="proj_project_export",
            run_id="run_project_export_0001",
            tool_call_id="tool_call_project_export_0001",
            capability=EXPORT_PROJECT_FORMAT,
        ),
        input=input_payload,
    )


def _timeline_payload(**extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": "proj_project_export",
        "timeline": {
            "tracks": {
                "a1": {
                    "kind": "audio",
                    "clips": [
                        {"clip_id": "audio_1", "kind": "audio", "timeline_start_seconds": 0, "duration_seconds": 5}
                    ],
                },
                "t1": {
                    "kind": "text",
                    "clips": [
                        {"clip_id": "title_1", "kind": "text", "start_seconds": 1, "duration_seconds": 2, "text": "Launch"}
                    ],
                },
                "v1": {
                    "kind": "video",
                    "clips": [
                        {"clip_id": "video_1", "kind": "video", "start_seconds": 0, "duration_seconds": 5}
                    ],
                },
            }
        },
    }
    payload.update(extra)
    return payload
