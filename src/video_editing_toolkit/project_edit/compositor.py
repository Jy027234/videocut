"""Deterministic stdlib-only composition planning for project timelines."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


COMPOSITION_PLAN_SCHEMA = "video_editing_toolkit.composition_plan.v0"
_DRIFT_WARNING_SECONDS = 0.5
_EPSILON = 0.000001


def build_composition_plan(
    timeline: Mapping[str, Any],
    *,
    render_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten a project timeline into a deterministic render planning contract.

    The plan is intentionally declarative: it contains no FFmpeg command line,
    filesystem path, or runtime-specific execution detail.
    """

    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    tracks = _normalize_tracks(timeline, warnings=warnings, errors=errors)
    clips = [clip for track in tracks for clip in track["clips"]]
    transitions = _normalize_transitions(timeline, tracks, warnings=warnings, errors=errors)
    effects = _flatten_effects(clips)

    video_clips = [clip for clip in clips if clip["kind"] == "video"]
    audio_clips = [clip for clip in clips if clip["kind"] == "audio"]
    text_clips = [clip for clip in clips if clip["kind"] == "text"]
    video_duration = _duration(video_clips)
    audio_duration = _duration(audio_clips)
    timeline_duration = _duration(clips)

    _check_text_bounds(text_clips, video_duration, warnings)
    _check_audio_video_drift(audio_duration, video_duration, warnings)

    render_duration = timeline_duration
    rendered_config = _render_config(render_config)
    max_duration = rendered_config.get("max_duration_seconds")
    if isinstance(max_duration, (int, float)):
        render_duration = min(render_duration, float(max_duration))

    summary = {
        "duration_seconds": _round_seconds(timeline_duration),
        "render_duration_seconds": _round_seconds(render_duration),
        "track_count": len(tracks),
        "clip_count": len(clips),
        "video_clip_count": len(video_clips),
        "audio_clip_count": len(audio_clips),
        "text_clip_count": len(text_clips),
        "transition_count": len(transitions),
        "effect_count": len(effects),
        "video_duration_seconds": _round_seconds(video_duration),
        "audio_duration_seconds": _round_seconds(audio_duration),
        "warning_count": len(warnings),
        "error_count": len(errors),
    }

    return {
        "schema": COMPOSITION_PLAN_SCHEMA,
        "summary": summary,
        "render_config": rendered_config,
        "tracks": tracks,
        "video_layers": _video_layers(tracks),
        "audio_mix": _audio_mix(tracks, audio_duration),
        "text_overlays": text_clips,
        "transitions": transitions,
        "effects": effects,
        "render_steps": _render_steps(video_clips, audio_clips, text_clips, transitions, effects),
        "warnings": warnings,
        "errors": errors,
    }


def composition_warning_messages(plan: Mapping[str, Any]) -> list[str]:
    """Return stable human-readable messages suitable for legacy warnings."""

    warnings = plan.get("warnings", [])
    if not isinstance(warnings, list):
        return []
    messages: list[str] = []
    for warning in warnings:
        if not isinstance(warning, Mapping):
            continue
        code = str(warning.get("code") or "composition_warning")
        clip_id = warning.get("clip_id") or warning.get("current_clip_id")
        track_id = warning.get("track_id")
        if clip_id is not None and track_id is not None:
            messages.append(f"{code} on track {track_id} clip {clip_id}.")
        elif track_id is not None:
            messages.append(f"{code} on track {track_id}.")
        else:
            messages.append(f"{code}.")
    return messages


def _normalize_tracks(
    timeline: Mapping[str, Any],
    *,
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_tracks = timeline.get("tracks", {})
    if not isinstance(raw_tracks, Mapping):
        errors.append({"code": "invalid_tracks", "message": "timeline.tracks must be an object."})
        return []

    tracks: list[dict[str, Any]] = []
    track_items = sorted(raw_tracks.items(), key=lambda item: str(item[0]))
    for layer_index, (raw_track_id, raw_track) in enumerate(track_items):
        track_id = str(raw_track_id)
        if not isinstance(raw_track, Mapping):
            errors.append({"code": "invalid_track", "track_id": track_id})
            continue
        kind = _track_kind(raw_track)
        clips = _normalize_clips(
            track_id,
            raw_track.get("clips", []),
            fallback_kind=kind,
            layer_index=layer_index,
            warnings=warnings,
            errors=errors,
        )
        tracks.append(
            {
                "track_id": track_id,
                "kind": kind,
                "layer_index": layer_index,
                "duration_seconds": _round_seconds(_duration(clips)),
                "clips": clips,
            }
        )
    return tracks


def _normalize_clips(
    track_id: str,
    raw_clips: Any,
    *,
    fallback_kind: str,
    layer_index: int,
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_clips, list):
        errors.append({"code": "invalid_clips", "track_id": track_id})
        return []

    clips: list[dict[str, Any]] = []
    for index, raw_clip in enumerate(raw_clips):
        if not isinstance(raw_clip, Mapping):
            errors.append({"code": "invalid_clip", "track_id": track_id, "clip_index": index})
            continue
        clip_id = str(raw_clip.get("clip_id") or f"{track_id}_clip_{index:04d}")
        kind = _clip_kind(raw_clip, fallback_kind)
        start = _seconds(raw_clip.get("timeline_start_seconds", raw_clip.get("start_seconds", 0.0)))
        duration = _seconds(raw_clip.get("duration_seconds", 0.0))
        end = start + duration
        if start < -_EPSILON:
            errors.append(
                {
                    "code": "negative_start",
                    "track_id": track_id,
                    "clip_id": clip_id,
                    "start_seconds": _round_seconds(start),
                }
            )
        if duration < -_EPSILON:
            errors.append(
                {
                    "code": "negative_duration",
                    "track_id": track_id,
                    "clip_id": clip_id,
                    "duration_seconds": _round_seconds(duration),
                }
            )

        clip: dict[str, Any] = {
            "track_id": track_id,
            "clip_id": clip_id,
            "kind": kind,
            "layer_index": layer_index,
            "start_seconds": _round_seconds(start),
            "end_seconds": _round_seconds(end),
            "duration_seconds": _round_seconds(duration),
        }
        if kind in {"video", "audio"}:
            clip["source_in_seconds"] = _round_seconds(_seconds(raw_clip.get("source_in_seconds", 0.0)))
            clip["source_out_seconds"] = _round_seconds(
                _seconds(raw_clip.get("source_out_seconds", clip["source_in_seconds"] + duration))
            )
        if kind == "text":
            clip["text"] = str(raw_clip.get("text") or "")
            if raw_clip.get("style") is not None:
                clip["style"] = deepcopy(raw_clip.get("style"))
        if isinstance(raw_clip.get("asset_ref"), Mapping):
            clip["asset_ref"] = deepcopy(raw_clip["asset_ref"])
        if isinstance(raw_clip.get("effects"), list):
            clip["effects"] = [
                {
                    "effect_id": str(effect.get("effect_id") or ""),
                    "parameters": deepcopy(effect.get("parameters", {})),
                }
                for effect in raw_clip["effects"]
                if isinstance(effect, Mapping)
            ]
        clips.append(clip)

    clips.sort(key=lambda item: (item["start_seconds"], item["end_seconds"], item["clip_id"]))
    _check_track_overlap(track_id, clips, warnings)
    return clips


def _normalize_transitions(
    timeline: Mapping[str, Any],
    tracks: list[dict[str, Any]],
    *,
    warnings: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_transitions = timeline.get("transitions", [])
    if not isinstance(raw_transitions, list):
        errors.append({"code": "invalid_transitions", "message": "timeline.transitions must be a list."})
        return []

    by_clip_id = {
        clip["clip_id"]: (track, clip)
        for track in tracks
        for clip in track["clips"]
    }
    transitions: list[dict[str, Any]] = []
    for index, raw_transition in enumerate(raw_transitions):
        if not isinstance(raw_transition, Mapping):
            errors.append({"code": "invalid_transition", "transition_index": index})
            continue
        clip_id = str(raw_transition.get("clip_id") or "")
        transition_id = str(
            raw_transition.get("transition_id")
            or raw_transition.get("transition")
            or "cut"
        )
        duration = _seconds(raw_transition.get("duration_seconds", 0.0))
        if duration < -_EPSILON:
            errors.append(
                {
                    "code": "negative_transition_duration",
                    "clip_id": clip_id,
                    "transition_id": transition_id,
                    "duration_seconds": _round_seconds(duration),
                }
            )
        found = by_clip_id.get(clip_id)
        if found is None:
            errors.append(
                {
                    "code": "transition_clip_missing",
                    "clip_id": clip_id,
                    "transition_id": transition_id,
                }
            )
            continue
        track, clip = found
        previous_clip = _previous_clip(track["clips"], clip)
        if previous_clip is None and transition_id not in {"cut", "registered.cut"}:
            warnings.append(
                {
                    "code": "transition_without_previous_clip",
                    "track_id": track["track_id"],
                    "clip_id": clip_id,
                    "transition_id": transition_id,
                }
            )
        if duration - float(clip["duration_seconds"]) > _EPSILON:
            warnings.append(
                {
                    "code": "transition_exceeds_clip_duration",
                    "track_id": track["track_id"],
                    "clip_id": clip_id,
                    "transition_id": transition_id,
                    "duration_seconds": _round_seconds(duration),
                    "clip_duration_seconds": clip["duration_seconds"],
                }
            )
        start = float(clip["start_seconds"])
        end = min(float(clip["end_seconds"]), start + max(0.0, duration))
        transitions.append(
            {
                "transition_id": transition_id,
                "track_id": track["track_id"],
                "from_clip_id": previous_clip["clip_id"] if previous_clip is not None else None,
                "to_clip_id": clip_id,
                "clip_id": clip_id,
                "placement": "incoming",
                "start_seconds": _round_seconds(start),
                "end_seconds": _round_seconds(end),
                "duration_seconds": _round_seconds(max(0.0, duration)),
            }
        )
    transitions.sort(key=lambda item: (item["start_seconds"], item["track_id"], item["clip_id"], item["transition_id"]))
    return transitions


def _flatten_effects(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for clip in sorted(clips, key=lambda item: (item["start_seconds"], item["track_id"], item["clip_id"])):
        for effect in clip.get("effects", []):
            if not isinstance(effect, Mapping):
                continue
            effects.append(
                {
                    "track_id": clip["track_id"],
                    "clip_id": clip["clip_id"],
                    "effect_id": str(effect.get("effect_id") or ""),
                    "parameters": deepcopy(effect.get("parameters", {})),
                }
            )
    return effects


def _check_track_overlap(track_id: str, clips: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    previous: dict[str, Any] | None = None
    for clip in clips:
        if previous is not None and float(previous["end_seconds"]) - float(clip["start_seconds"]) > _EPSILON:
            warnings.append(
                {
                    "code": "track_overlap",
                    "track_id": track_id,
                    "previous_clip_id": previous["clip_id"],
                    "current_clip_id": clip["clip_id"],
                    "overlap_seconds": _round_seconds(float(previous["end_seconds"]) - float(clip["start_seconds"])),
                }
            )
        if previous is None or float(clip["end_seconds"]) > float(previous["end_seconds"]):
            previous = clip


def _check_text_bounds(
    text_clips: list[dict[str, Any]],
    video_duration: float,
    warnings: list[dict[str, Any]],
) -> None:
    if video_duration <= _EPSILON:
        return
    for clip in text_clips:
        if float(clip["end_seconds"]) - video_duration > _EPSILON:
            warnings.append(
                {
                    "code": "text_out_of_video_bounds",
                    "track_id": clip["track_id"],
                    "clip_id": clip["clip_id"],
                    "end_seconds": clip["end_seconds"],
                    "video_duration_seconds": _round_seconds(video_duration),
                }
            )


def _check_audio_video_drift(
    audio_duration: float,
    video_duration: float,
    warnings: list[dict[str, Any]],
) -> None:
    if audio_duration <= _EPSILON or video_duration <= _EPSILON:
        return
    drift = audio_duration - video_duration
    if abs(drift) > _DRIFT_WARNING_SECONDS:
        warnings.append(
            {
                "code": "audio_video_duration_mismatch",
                "audio_duration_seconds": _round_seconds(audio_duration),
                "video_duration_seconds": _round_seconds(video_duration),
                "drift_seconds": _round_seconds(drift),
            }
        )


def _video_layers(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for layer_index, track in enumerate(track for track in tracks if track["kind"] == "video"):
        layers.append(
            {
                "track_id": track["track_id"],
                "layer_index": layer_index,
                "clips": deepcopy(track["clips"]),
            }
        )
    return layers


def _audio_mix(tracks: list[dict[str, Any]], audio_duration: float) -> dict[str, Any]:
    audio_tracks = [track for track in tracks if track["kind"] == "audio"]
    return {
        "strategy": "sum_tracks_then_limit",
        "duration_seconds": _round_seconds(audio_duration),
        "track_count": len(audio_tracks),
        "tracks": [
            {
                "track_id": track["track_id"],
                "clips": deepcopy(track["clips"]),
            }
            for track in audio_tracks
        ],
    }


def _render_steps(
    video_clips: list[dict[str, Any]],
    audio_clips: list[dict[str, Any]],
    text_clips: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    effects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"step": "compose_video_layers", "clip_count": len(video_clips)},
        {"step": "apply_transitions", "transition_count": len(transitions)},
        {"step": "apply_effects", "effect_count": len(effects)},
        {"step": "mix_audio_tracks", "clip_count": len(audio_clips)},
        {"step": "place_text_overlays", "clip_count": len(text_clips)},
    ]


def _previous_clip(clips: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        clip
        for clip in clips
        if clip["clip_id"] != current["clip_id"]
        and float(clip["start_seconds"]) <= float(current["start_seconds"])
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["end_seconds"], item["start_seconds"], item["clip_id"]))
    return candidates[-1]


def _track_kind(track: Mapping[str, Any]) -> str:
    kind = track.get("kind")
    if kind in {"video", "audio", "text"}:
        return str(kind)
    clips = track.get("clips", [])
    if isinstance(clips, list):
        for clip in clips:
            if isinstance(clip, Mapping):
                clip_kind = clip.get("kind")
                if clip_kind in {"video", "audio", "text"}:
                    return str(clip_kind)
    return "video"


def _clip_kind(clip: Mapping[str, Any], fallback_kind: str) -> str:
    kind = clip.get("kind")
    if kind in {"video", "audio", "text"}:
        return str(kind)
    return fallback_kind if fallback_kind in {"video", "audio", "text"} else "video"


def _duration(clips: list[Mapping[str, Any]]) -> float:
    duration = 0.0
    for clip in clips:
        end = _seconds(clip.get("end_seconds", 0.0))
        duration = max(duration, end)
    return duration


def _render_config(render_config: Mapping[str, Any] | None) -> dict[str, Any]:
    if render_config is None:
        return {}
    allowed = {
        "mode",
        "profile",
        "container",
        "video_codec",
        "audio_codec",
        "resolution",
        "include_audio",
        "max_duration_seconds",
    }
    return {
        key: deepcopy(render_config[key])
        for key in sorted(render_config)
        if key in allowed
    }


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _round_seconds(value: float) -> float:
    return round(float(value), 3)
