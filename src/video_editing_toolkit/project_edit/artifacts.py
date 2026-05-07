"""Project-edit artifact payload builders."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Mapping

from .core import summarize_timeline
from .models import ProjectVersion


TIMELINE_SCHEMA = "video_editing_toolkit.project_timeline.v0"
RENDER_CONFIG_SCHEMA = "video_editing_toolkit.render_config.v0"
TIMELINE_ARTIFACT_TYPE = "timeline_json"
RENDER_CONFIG_ARTIFACT_TYPE = "render_config_json"


def timeline_artifact_payload(
    *,
    version: ProjectVersion,
    run_id: str,
) -> dict[str, Any]:
    """Return the persisted timeline.json contract for a project version."""

    return {
        "schema": TIMELINE_SCHEMA,
        "project_id": version.project_id,
        "version_id": version.version_id,
        "parent_version_id": version.parent_version_id,
        "change_reason": version.change_reason,
        "created_at": version.created_at,
        "created_by_run_id": run_id,
        "timeline_summary": summarize_timeline(version.timeline),
        "timeline": deepcopy(version.timeline),
    }


def render_config_artifact_payload(
    *,
    project_id: str,
    version_id: str,
    run_id: str,
    input_payload: Mapping[str, Any],
    timeline_summary: Mapping[str, Any],
    source_timeline_artifact_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the render_config.json contract for preview planning."""

    return {
        "schema": RENDER_CONFIG_SCHEMA,
        "project_id": project_id,
        "version_id": version_id,
        "created_by_run_id": run_id,
        "render_target": "preview",
        "timeline_summary": dict(timeline_summary),
        "source_timeline_artifact_ref": (
            dict(source_timeline_artifact_ref)
            if source_timeline_artifact_ref is not None
            else None
        ),
        "render_config": _preview_render_config(input_payload),
    }


def json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _preview_render_config(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    profile = _string_value(
        input_payload.get("preview_profile", input_payload.get("profile", input_payload.get("target"))),
        "review",
    )
    config: dict[str, Any] = {
        "mode": "preview",
        "profile": profile,
        "container": _string_value(input_payload.get("container", input_payload.get("format")), "mp4"),
        "video_codec": _string_value(input_payload.get("video_codec"), "h264"),
        "audio_codec": _string_value(input_payload.get("audio_codec"), "aac"),
        "resolution": _string_value(input_payload.get("resolution"), "720p"),
        "include_audio": _bool_value(input_payload.get("include_audio"), True),
    }

    max_duration = _optional_seconds(
        input_payload.get("max_duration_seconds", input_payload.get("duration_seconds"))
    )
    if max_duration is not None:
        config["max_duration_seconds"] = max_duration
    return config


def _string_value(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _optional_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)) and value >= 0:
        return round(float(value), 3)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed >= 0:
            return round(parsed, 3)
    return None
