"""P0 project edit operations implemented without external tools."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .models import InMemoryProjectStore, ProjectVersion, empty_timeline, get_default_store
from .validator import TimelinePatchValidationError, validate_timeline_patch


class ProjectEditError(RuntimeError):
    """Stable project-edit failure returned through adapters."""

    def __init__(self, stable_code: str, message: str) -> None:
        self.stable_code = stable_code
        super().__init__(message)


def create_project(
    request: Mapping[str, Any],
    *,
    store: InMemoryProjectStore | None = None,
) -> dict[str, Any]:
    project_id = _project_id(request)
    version = (store or get_default_store()).create_project(
        project_id,
        initial_timeline=request.get("timeline") if isinstance(request.get("timeline"), dict) else None,
    )
    return {
        "project_id": project_id,
        "version_id": version.version_id,
        "timeline_summary": summarize_timeline(version.timeline),
    }


def inspect_assets(request: Mapping[str, Any]) -> dict[str, Any]:
    assets = request.get("assets", [])
    if not isinstance(assets, list):
        raise ProjectEditError("invalid_schema", "assets must be a list when provided.")
    return {
        "asset_count": len(assets),
        "assets": [deepcopy(asset) for asset in assets if isinstance(asset, Mapping)],
        "warnings": [],
    }


def generate_edit_plan(request: Mapping[str, Any]) -> dict[str, Any]:
    goal = request.get("goal") or request.get("change_reason") or "Apply structured timeline edits."
    return {
        "edit_plan": {
            "steps": [
                {
                    "kind": "timeline_patch",
                    "description": str(goal),
                }
            ],
            "requires_external_tools": False,
        },
        "warnings": [],
    }


def apply_timeline_patch(
    request: Mapping[str, Any],
    *,
    store: InMemoryProjectStore | None = None,
) -> dict[str, Any]:
    operations = _validate(request)
    active_store = store or get_default_store()
    project_id = str(request["project_id"])
    base_version_id = str(request["base_version_id"])

    active_store.ensure_project(project_id)
    base_version = active_store.get_version(project_id, base_version_id)
    if base_version is None:
        raise ProjectEditError("conflict", f"base_version_id {base_version_id!r} does not exist.")

    timeline = deepcopy(base_version.timeline)
    warnings: list[str] = []
    for operation in operations:
        _apply_operation(timeline, operation, warnings)

    new_version = active_store.add_version(
        project_id,
        parent_version_id=base_version.version_id,
        timeline=timeline,
        change_reason=str(request["change_reason"]),
    )
    output = {
        "project_id": project_id,
        "base_version_id": base_version.version_id,
        "new_version_id": new_version.version_id,
        "timeline_summary": summarize_timeline(timeline),
        "warnings": warnings,
        "artifact_refs": [],
    }
    if request.get("requested_preview"):
        output["preview_artifact_ref"] = _preview_ref(project_id, new_version.version_id)
    return output


def render_preview(request: Mapping[str, Any]) -> dict[str, Any]:
    project_id = _project_id(request)
    version_id = str(request.get("version_id") or request.get("base_version_id") or "ver_0001")
    return {
        "project_id": project_id,
        "version_id": version_id,
        "preview_artifact_ref": _preview_ref(project_id, version_id),
        "warnings": [],
    }


def compare_versions(
    request: Mapping[str, Any],
    *,
    store: InMemoryProjectStore | None = None,
) -> dict[str, Any]:
    active_store = store or get_default_store()
    project_id = _project_id(request)
    left_id = str(request.get("left_version_id") or request.get("base_version_id") or "")
    right_id = str(request.get("right_version_id") or request.get("target_version_id") or "")
    if not left_id or not right_id:
        raise ProjectEditError("invalid_schema", "left_version_id and right_version_id are required.")
    left = active_store.get_version(project_id, left_id)
    right = active_store.get_version(project_id, right_id)
    if left is None or right is None:
        raise ProjectEditError("conflict", "Both versions must exist before comparison.")
    return {
        "project_id": project_id,
        "left_version_id": left_id,
        "right_version_id": right_id,
        "diff": _timeline_diff(left.timeline, right.timeline),
        "summaries": {
            left_id: summarize_timeline(left.timeline),
            right_id: summarize_timeline(right.timeline),
        },
    }


def rollback_version(
    request: Mapping[str, Any],
    *,
    store: InMemoryProjectStore | None = None,
) -> dict[str, Any]:
    active_store = store or get_default_store()
    project_id = _project_id(request)
    target_version_id = str(request.get("target_version_id") or "")
    if not target_version_id:
        raise ProjectEditError("invalid_schema", "target_version_id is required.")
    target = active_store.get_version(project_id, target_version_id)
    if target is None:
        raise ProjectEditError("conflict", f"target_version_id {target_version_id!r} does not exist.")
    latest = active_store.latest_version(project_id) or active_store.ensure_project(project_id)
    new_version = active_store.add_version(
        project_id,
        parent_version_id=latest.version_id,
        timeline=target.timeline,
        change_reason=str(request.get("change_reason") or f"Rollback to {target_version_id}."),
    )
    return {
        "project_id": project_id,
        "rolled_back_to_version_id": target_version_id,
        "new_version_id": new_version.version_id,
        "timeline_summary": summarize_timeline(new_version.timeline),
        "warnings": [],
    }


def summarize_timeline(timeline: Mapping[str, Any]) -> dict[str, Any]:
    tracks = timeline.get("tracks", {})
    video_tracks = 0
    audio_tracks = 0
    text_tracks = 0
    duration = 0.0
    if isinstance(tracks, Mapping):
        for track in tracks.values():
            if not isinstance(track, Mapping):
                continue
            kind = track.get("kind")
            if kind == "audio":
                audio_tracks += 1
            elif kind == "text":
                text_tracks += 1
            else:
                video_tracks += 1
            clips = track.get("clips", [])
            if isinstance(clips, list):
                for clip in clips:
                    if isinstance(clip, Mapping):
                        duration = max(duration, _clip_end(clip))
    return {
        "duration_seconds": round(duration, 3),
        "video_tracks": video_tracks,
        "audio_tracks": audio_tracks,
        "text_tracks": text_tracks,
    }


def _validate(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        return validate_timeline_patch(request)
    except TimelinePatchValidationError as exc:
        raise ProjectEditError(exc.stable_code, str(exc)) from exc


def _apply_operation(timeline: dict[str, Any], operation: Mapping[str, Any], warnings: list[str]) -> None:
    op = operation["op"]
    if op == "add_clip":
        _add_clip(timeline, operation, kind="video")
    elif op == "add_audio":
        _add_clip(timeline, operation, kind="audio")
    elif op == "add_text":
        _add_text(timeline, operation)
    elif op == "remove_clip":
        if not _remove_clip(timeline, str(operation["clip_id"])):
            warnings.append(f"clip {operation['clip_id']} was not present.")
    elif op == "move_clip":
        _move_clip(timeline, operation)
    elif op == "set_in_out":
        clip = _require_clip(timeline, str(operation["clip_id"]))
        if "source_in_seconds" in operation:
            clip["source_in_seconds"] = _seconds(operation["source_in_seconds"])
        if "source_out_seconds" in operation:
            clip["source_out_seconds"] = _seconds(operation["source_out_seconds"])
        _refresh_duration(clip)
    elif op == "split_clip":
        _split_clip(timeline, operation)
    elif op == "set_transition":
        _set_transition(timeline, operation)
    elif op == "set_effect":
        clip = _require_clip(timeline, str(operation["clip_id"]))
        clip.setdefault("effects", []).append(
            {
                "effect_id": operation["effect_id"],
                "parameters": deepcopy(operation.get("parameters", {})),
            }
        )


def _add_clip(timeline: dict[str, Any], operation: Mapping[str, Any], *, kind: str) -> None:
    track_id = str(operation["track_id"])
    clip_id = str(operation.get("clip_id") or operation.get("audio_id"))
    if _find_clip(timeline, clip_id) is not None:
        raise ProjectEditError("conflict", f"clip_id {clip_id!r} already exists.")
    start = _seconds(operation.get("timeline_start_seconds", operation.get("start_seconds", 0.0)))
    source_in = _seconds(operation.get("source_in_seconds", 0.0))
    source_out = operation.get("source_out_seconds", operation.get("end_seconds"))
    duration = max(0.0, _seconds(source_out) - source_in) if source_out is not None else 0.0
    clip = {
        "clip_id": clip_id,
        "kind": kind,
        "timeline_start_seconds": start,
        "source_in_seconds": source_in,
        "source_out_seconds": source_in + duration,
        "duration_seconds": duration,
    }
    if "asset_ref" in operation:
        clip["asset_ref"] = deepcopy(operation["asset_ref"])
    _track(timeline, track_id, kind)["clips"].append(clip)


def _add_text(timeline: dict[str, Any], operation: Mapping[str, Any]) -> None:
    start = _seconds(operation.get("start_seconds", operation.get("timeline_start_seconds", 0.0)))
    end = _seconds(operation.get("end_seconds", start))
    _track(timeline, str(operation["track_id"]), "text")["clips"].append(
        {
            "clip_id": str(operation["text_id"]),
            "kind": "text",
            "text": str(operation["text"]),
            "timeline_start_seconds": start,
            "duration_seconds": max(0.0, end - start),
            "style": operation.get("style"),
        }
    )


def _move_clip(timeline: dict[str, Any], operation: Mapping[str, Any]) -> None:
    clip_id = str(operation["clip_id"])
    found = _pop_clip(timeline, clip_id)
    if found is None:
        raise ProjectEditError("conflict", f"clip_id {clip_id!r} does not exist.")
    clip = found[1]
    clip["timeline_start_seconds"] = _seconds(operation.get("timeline_start_seconds", clip["timeline_start_seconds"]))
    _track(timeline, str(operation["track_id"]), str(clip.get("kind") or "video"))["clips"].append(clip)


def _split_clip(timeline: dict[str, Any], operation: Mapping[str, Any]) -> None:
    clip_id = str(operation["clip_id"])
    found = _pop_clip(timeline, clip_id)
    if found is None:
        raise ProjectEditError("conflict", f"clip_id {clip_id!r} does not exist.")
    track_id, clip = found
    split_at = _seconds(operation.get("split_seconds", operation.get("timeline_split_seconds", 0.0)))
    start = _seconds(clip.get("timeline_start_seconds", 0.0))
    end = _clip_end(clip)
    if not start < split_at < end:
        raise ProjectEditError("conflict", "split point must be inside the clip duration.")
    first = deepcopy(clip)
    second = deepcopy(clip)
    first["clip_id"] = str(operation.get("first_clip_id") or f"{clip_id}_a")
    second["clip_id"] = str(operation.get("second_clip_id") or f"{clip_id}_b")
    first["duration_seconds"] = split_at - start
    second["timeline_start_seconds"] = split_at
    second["duration_seconds"] = end - split_at
    timeline["tracks"][track_id]["clips"].extend([first, second])


def _set_transition(timeline: dict[str, Any], operation: Mapping[str, Any]) -> None:
    _require_clip(timeline, str(operation["clip_id"]))
    timeline.setdefault("transitions", []).append(
        {
            "clip_id": operation["clip_id"],
            "transition_id": operation.get("transition_id") or operation.get("transition") or "cut",
            "duration_seconds": _seconds(operation.get("duration_seconds", 0.0)),
        }
    )


def _timeline_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_ids = set(_clip_ids(left))
    right_ids = set(_clip_ids(right))
    return {
        "added_clip_ids": sorted(right_ids - left_ids),
        "removed_clip_ids": sorted(left_ids - right_ids),
        "changed": deepcopy(left) != deepcopy(right),
    }


def _clip_ids(timeline: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    tracks = timeline.get("tracks", {})
    if isinstance(tracks, Mapping):
        for track in tracks.values():
            clips = track.get("clips", []) if isinstance(track, Mapping) else []
            for clip in clips:
                if isinstance(clip, Mapping) and clip.get("clip_id") is not None:
                    ids.append(str(clip["clip_id"]))
    return ids


def _track(timeline: dict[str, Any], track_id: str, kind: str) -> dict[str, Any]:
    timeline.setdefault("tracks", {})
    return timeline["tracks"].setdefault(track_id, {"track_id": track_id, "kind": kind, "clips": []})


def _find_clip(timeline: Mapping[str, Any], clip_id: str) -> dict[str, Any] | None:
    found = _find_clip_with_track(timeline, clip_id)
    return found[1] if found is not None else None


def _find_clip_with_track(timeline: Mapping[str, Any], clip_id: str) -> tuple[str, dict[str, Any]] | None:
    tracks = timeline.get("tracks", {})
    if isinstance(tracks, Mapping):
        for track_id, track in tracks.items():
            clips = track.get("clips", []) if isinstance(track, Mapping) else []
            for clip in clips:
                if isinstance(clip, dict) and clip.get("clip_id") == clip_id:
                    return str(track_id), clip
    return None


def _require_clip(timeline: Mapping[str, Any], clip_id: str) -> dict[str, Any]:
    clip = _find_clip(timeline, clip_id)
    if clip is None:
        raise ProjectEditError("conflict", f"clip_id {clip_id!r} does not exist.")
    return clip


def _remove_clip(timeline: dict[str, Any], clip_id: str) -> bool:
    return _pop_clip(timeline, clip_id) is not None


def _pop_clip(timeline: dict[str, Any], clip_id: str) -> tuple[str, dict[str, Any]] | None:
    tracks = timeline.get("tracks", {})
    if not isinstance(tracks, dict):
        return None
    for track_id, track in tracks.items():
        clips = track.get("clips", []) if isinstance(track, dict) else []
        for index, clip in enumerate(clips):
            if isinstance(clip, dict) and clip.get("clip_id") == clip_id:
                return str(track_id), clips.pop(index)
    return None


def _refresh_duration(clip: dict[str, Any]) -> None:
    clip["duration_seconds"] = max(
        0.0,
        _seconds(clip.get("source_out_seconds", 0.0)) - _seconds(clip.get("source_in_seconds", 0.0)),
    )


def _clip_end(clip: Mapping[str, Any]) -> float:
    return _seconds(clip.get("timeline_start_seconds", 0.0)) + _seconds(clip.get("duration_seconds", 0.0))


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ProjectEditError("invalid_schema", f"{value!r} is not a valid seconds value.") from exc
    return 0.0


def _project_id(request: Mapping[str, Any]) -> str:
    project_id = request.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ProjectEditError("invalid_schema", "project_id is required.")
    return project_id


def _preview_ref(project_id: str, version_id: str) -> dict[str, Any]:
    artifact_id = f"art_preview_{project_id}_{version_id}".replace(" ", "_")
    return {
        "artifact_id": artifact_id,
        "artifact_type": "preview_video",
        "mime_type": "video/mp4",
        "size_bytes": 0,
        "checksum": "sha256:pending-preview-render",
        "data_class": "sensitive",
        "retention_policy": "preview_7d",
        "expires_at": "2026-05-14T00:00:00Z",
        "access_policy": "tenant_and_share_scoped",
        "download_url": f"/local/artifacts/{artifact_id}",
    }
