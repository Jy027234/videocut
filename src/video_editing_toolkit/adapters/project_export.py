"""Caller-safe project format export adapter.

The FCPXML exporter is intentionally declarative and stdlib-only. It builds a
portable project interchange document without launching Final Cut Pro, DaVinci,
shell commands, or any local application automation.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter, TOOLKIT_ID


EXPORT_PROJECT_FORMAT = "video.render.export_project_format"
PROJECT_EXPORT_SCHEMA = "video_editing_toolkit.project_export.v0"
FCPXML_SCHEMA = "fcpxml-1.10"
PROJECT_EXPORT_FCPXML_ARTIFACT_TYPE = "project_export_fcpxml"

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_LOCAL_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)[^\s\"']+"),
    re.compile(r"\\\\[^\\/\s\"']+[\\/][^\s\"']+"),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"local-artifact://", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])/(Users|home|var|tmp|private|mnt)/[^\s\"']+"),
)
_RAW_COMMAND_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])(?:ffmpeg|ffprobe|osascript)(?:\.exe)?\s+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])(?:cmd|powershell)(?:\.exe)?\s+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])(?:python|node|npm|npx)\s+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])(?:davinci|resolve|fcp|final\s+cut)\s+", re.IGNORECASE),
)
_FORBIDDEN_KEYS = {
    "app_automation",
    "authorization",
    "client_secret",
    "command",
    "davinci_api",
    "davinci_api_call",
    "davinci_script",
    "fcpx_automation",
    "ffmpeg_command",
    "file_path",
    "filesystem_path",
    "final_cut_automation",
    "internal_path",
    "local_path",
    "password",
    "private_key",
    "raw_command",
    "raw_shell",
    "resolve_api_call",
    "secret",
    "storage_uri",
    "token",
    "worker_path",
}


class ProjectExportError(ValueError):
    """Stable validation failure for project export requests."""

    def __init__(self, stable_code: str, message: str) -> None:
        self.stable_code = stable_code
        super().__init__(message)


class ProjectExportAdapter(BaseAdapter):
    adapter_name = "project_export"
    supported_capabilities = frozenset({EXPORT_PROJECT_FORMAT})
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability != EXPORT_PROJECT_FORMAT:
            return AdapterResult.unsupported(request.context.capability, self.adapter_name)

        try:
            descriptor = build_project_export_descriptor(request)
        except ProjectExportError as exc:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                output={
                    "schema": PROJECT_EXPORT_SCHEMA,
                    "format": "unknown",
                    "valid": False,
                    "stable_error_code": exc.stable_code,
                },
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=str(exc),
            )

        artifact_refs = self._materialize_fcpxml(request, descriptor["fcpxml"])
        if artifact_refs:
            descriptor.pop("fcpxml", None)
            public_refs = [_artifact_public_dict_without_download_token(ref) for ref in artifact_refs]
            descriptor["project_export_artifact_ref"] = public_refs[0]
            descriptor["artifact_refs"] = public_refs

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output=descriptor,
            artifact_refs=artifact_refs,
            usage_metrics={
                "operation": "export_project_format",
                "format": descriptor["format"],
                "clip_count": descriptor["timeline_summary"]["clip_count"],
                "artifact_count": len(artifact_refs),
                "app_automation_invocations": 0,
                "davinci_api_invocations": 0,
                "shell_invocations": 0,
            },
        )

    def _materialize_fcpxml(
        self,
        request: AdapterRequest,
        fcpxml: str,
    ) -> tuple[ArtifactRef, ...]:
        artifact_store = request.input.get("_artifact_store")
        if not isinstance(artifact_store, LocalArtifactStore):
            return ()

        ref = artifact_store.put_bytes(
            content=fcpxml.encode("utf-8"),
            artifact_type=PROJECT_EXPORT_FCPXML_ARTIFACT_TYPE,
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="project.fcpxml",
            mime_type="application/xml",
        )
        return (ref,)


def _artifact_public_dict_without_download_token(ref: ArtifactRef) -> dict[str, Any]:
    public_ref = ref.to_public_dict()
    download_url = public_ref.get("download_url")
    if isinstance(download_url, str) and ("?" in download_url or "token" in download_url.casefold()):
        public_ref.pop("download_url", None)
    return public_ref


def build_project_export_descriptor(request: AdapterRequest) -> dict[str, Any]:
    _assert_caller_safe(request.input, path="$")
    export_format = _export_format(request.input)
    if export_format != "fcpxml":
        raise ProjectExportError(
            "project_export.unsupported_format",
            f"Only fcpxml project export is supported, got {export_format!r}.",
        )

    project_id = _safe_id(
        str(request.input.get("project_id") or request.context.project_id),
        "$.project_id",
    )
    timeline = _timeline_payload(request.input)
    normalized = _normalize_timeline(timeline)
    timeline_summary = _timeline_summary(normalized)
    warnings = _warnings(request.input, normalized)
    fcpxml = build_fcpxml(project_id=project_id, timeline=normalized)

    return {
        "schema": PROJECT_EXPORT_SCHEMA,
        "format": "fcpxml",
        "project_id": project_id,
        "timeline_summary": timeline_summary,
        "warnings": warnings,
        "fcpxml_schema": FCPXML_SCHEMA,
        "fcpxml": fcpxml,
        "runtime_execution": "not_started",
        "toolkit_id": TOOLKIT_ID,
    }


def build_fcpxml(*, project_id: str, timeline: Mapping[str, Any]) -> str:
    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": "FFVideoFormat1080p30",
            "frameDuration": "1/30s",
            "width": "1920",
            "height": "1080",
            "colorSpace": "1-1-1 (Rec. 709)",
        },
    )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": _xml_name(project_id)})
    project = ET.SubElement(event, "project", {"name": _xml_name(project_id)})
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "format": "r1",
            "duration": _fcpx_duration(timeline["duration_seconds"]),
            "tcStart": "0s",
            "tcFormat": "NDF",
        },
    )
    spine = ET.SubElement(sequence, "spine")
    for clip in timeline["clips"]:
        clip_attrs = {
            "name": _xml_name(clip["clip_id"]),
            "offset": _fcpx_duration(clip["start_seconds"]),
            "duration": _fcpx_duration(clip["duration_seconds"]),
            "start": "0s",
        }
        if clip["kind"] == "audio":
            clip_attrs["audioRole"] = "dialogue"
        element_name = "title" if clip["kind"] == "text" else "asset-clip"
        clip_element = ET.SubElement(spine, element_name, clip_attrs)
        if clip["kind"] == "text":
            text = ET.SubElement(clip_element, "text")
            ET.SubElement(text, "text-style", {"ref": "ts1"}).text = clip.get("text", "")
    return ET.tostring(root, encoding="unicode", xml_declaration=True, short_empty_elements=True)


def _export_format(input_payload: Mapping[str, Any]) -> str:
    value = input_payload.get("format", input_payload.get("export_format", "fcpxml"))
    return str(value).casefold()


def _timeline_payload(input_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    timeline = input_payload.get("timeline")
    if isinstance(timeline, Mapping):
        return timeline
    plan = input_payload.get("composition_plan")
    if isinstance(plan, Mapping):
        return plan
    raise ProjectExportError(
        "project_export.timeline_required",
        "Project export requires a timeline or composition_plan object.",
    )


def _normalize_timeline(timeline: Mapping[str, Any]) -> dict[str, Any]:
    clips: list[dict[str, Any]] = []
    raw_tracks = timeline.get("tracks", {})
    if isinstance(raw_tracks, Mapping):
        track_items = [(str(track_id), track) for track_id, track in sorted(raw_tracks.items(), key=lambda item: str(item[0]))]
    elif isinstance(raw_tracks, list):
        track_items = [
            (str(track.get("track_id") or index), track)
            for index, track in enumerate(raw_tracks)
            if isinstance(track, Mapping)
        ]
    else:
        track_items = []

    for track_index, (track_id, track) in enumerate(track_items):
        if not isinstance(track, Mapping):
            continue
        track_kind = _kind(track.get("kind"), "video")
        raw_clips = track.get("clips", [])
        if not isinstance(raw_clips, list):
            continue
        for clip_index, raw_clip in enumerate(raw_clips):
            if not isinstance(raw_clip, Mapping):
                continue
            kind = _kind(raw_clip.get("kind"), track_kind)
            clip_id = _safe_id(
                str(raw_clip.get("clip_id") or f"{track_id}_clip_{clip_index:04d}"),
                f"$.timeline.tracks[{track_index}].clips[{clip_index}].clip_id",
            )
            start = _seconds(raw_clip.get("start_seconds", raw_clip.get("timeline_start_seconds", 0.0)))
            duration = _duration(raw_clip)
            clips.append(
                {
                    "track_id": _safe_id(track_id, f"$.timeline.tracks[{track_index}].track_id"),
                    "clip_id": clip_id,
                    "kind": kind,
                    "start_seconds": round(start, 3),
                    "duration_seconds": round(max(0.0, duration), 3),
                    "end_seconds": round(max(start, start + duration), 3),
                    "text": str(raw_clip.get("text") or "") if kind == "text" else "",
                }
            )

    clips.sort(key=lambda item: (item["start_seconds"], item["track_id"], item["clip_id"]))
    duration_seconds = round(max((clip["end_seconds"] for clip in clips), default=0.0), 3)
    return {"clips": clips, "duration_seconds": duration_seconds, "track_count": len(track_items)}


def _timeline_summary(timeline: Mapping[str, Any]) -> dict[str, Any]:
    clips = list(timeline["clips"])
    return {
        "duration_seconds": timeline["duration_seconds"],
        "track_count": timeline["track_count"],
        "clip_count": len(clips),
        "video_clip_count": sum(1 for clip in clips if clip["kind"] == "video"),
        "audio_clip_count": sum(1 for clip in clips if clip["kind"] == "audio"),
        "text_clip_count": sum(1 for clip in clips if clip["kind"] == "text"),
    }


def _warnings(input_payload: Mapping[str, Any], timeline: Mapping[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if input_payload.get("composition_plan") is not None and input_payload.get("timeline") is None:
        warnings.append(
            {
                "code": "composition_plan_used",
                "message": "Export was generated from composition_plan tracks.",
            }
        )
    if not timeline["clips"]:
        warnings.append({"code": "empty_timeline", "message": "Export timeline has no clips."})
    return warnings


def _assert_caller_safe(value: Any, *, path: str) -> None:
    if path == "$._artifact_store":
        return
    if isinstance(value, Mapping):
        leaked_keys = {str(key) for key in value}.intersection(_FORBIDDEN_KEYS)
        if leaked_keys:
            raise ProjectExportError(
                "project_export.unsafe_payload",
                f"{path} includes caller-unsafe keys: {', '.join(sorted(leaked_keys))}.",
            )
        for key, child in value.items():
            _assert_caller_safe(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_caller_safe(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in _LOCAL_PATH_PATTERNS:
            if pattern.search(value):
                raise ProjectExportError(
                    "project_export.unsafe_payload",
                    f"{path} includes a local path-like value.",
                )
        for pattern in _RAW_COMMAND_PATTERNS:
            if pattern.search(value):
                raise ProjectExportError(
                    "project_export.unsafe_payload",
                    f"{path} includes a raw command-like value.",
                )


def _safe_id(value: str, path: str) -> str:
    if not _SAFE_ID_PATTERN.fullmatch(value):
        raise ProjectExportError(
            "project_export.invalid_identifier",
            f"{path} must be a safe identifier without local paths or shell fragments.",
        )
    return value


def _kind(value: Any, fallback: str) -> str:
    return str(value) if value in {"video", "audio", "text"} else fallback


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _duration(clip: Mapping[str, Any]) -> float:
    if "duration_seconds" in clip:
        return _seconds(clip.get("duration_seconds"))
    source_in = _seconds(clip.get("source_in_seconds", 0.0))
    source_out = _seconds(clip.get("source_out_seconds", source_in))
    return source_out - source_in


def _fcpx_duration(seconds: Any) -> str:
    frames = max(0, round(_seconds(seconds) * 30))
    return f"{frames}/30s" if frames else "0s"


def _xml_name(value: str) -> str:
    return deepcopy(value)
