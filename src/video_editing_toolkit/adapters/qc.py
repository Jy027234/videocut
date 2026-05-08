"""Deterministic caller-safe QC report adapter."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


GENERATE_QC_REPORT = "video.qc.generate_report"
QC_REPORT_SCHEMA = "video_editing_toolkit.qc_report.v0"
QC_REPORT_ARTIFACT_TYPE = "qc_report_json"
_EPSILON = 0.000001
_DEFAULT_DRIFT_WARNING_SECONDS = 0.5
_SAFE_CODE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class QCAdapter(BaseAdapter):
    adapter_name = "qc"
    supported_capabilities = frozenset({GENERATE_QC_REPORT})
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == GENERATE_QC_REPORT:
            return self.generate_report(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def generate_report(self, request: AdapterRequest) -> AdapterResult:
        report = build_qc_report(request.input)
        output: dict[str, Any] = {"qc_report": report}
        artifact_refs: tuple[ArtifactRef, ...] = ()

        artifact_store = self._artifact_store(request)
        if artifact_store is not None:
            report_ref = artifact_store.put_bytes(
                content=_json_bytes(report),
                artifact_type=QC_REPORT_ARTIFACT_TYPE,
                owner_tenant_id=request.context.tenant_id,
                created_by_run_id=request.context.run_id,
                filename="qc_report.json",
                mime_type="application/json",
            )
            artifact_refs = (report_ref,)
            output["qc_report_artifact_ref"] = report_ref.to_public_dict()
            output["artifact_refs"] = [report_ref.to_public_dict()]

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output=output,
            artifact_refs=artifact_refs,
            usage_metrics={
                "operation": "generate_report",
                "check_count": report["summary"]["check_count"],
                "blocking_issue_count": report["summary"]["blocking_issue_count"],
                "warning_count": report["summary"]["warning_count"],
                "artifact_count": len(artifact_refs),
            },
        )

    def _artifact_store(self, request: AdapterRequest) -> LocalArtifactStore | None:
        artifact_store = request.input.get("_artifact_store")
        if isinstance(artifact_store, LocalArtifactStore):
            return artifact_store
        return None


def build_qc_report(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    checks = [
        _timeline_structure_check(input_payload),
        _timeline_overlap_check(input_payload),
        _subtitle_bounds_check(input_payload),
        _media_drift_check(input_payload),
        _brand_keyword_check(input_payload),
        _brand_safe_area_check(input_payload),
    ]
    severity_counts = {"pass": 0, "warning": 0, "blocking": 0}
    for check in checks:
        severity_counts[check["severity"]] += 1

    blocking_issues = [check for check in checks if check["severity"] == "blocking"]
    warnings = [check for check in checks if check["severity"] == "warning"]
    status = "blocking" if blocking_issues else "warning" if warnings else "pass"
    evidence_refs = _unique_ref(
        ref
        for check in checks
        for ref in check.get("evidence_refs", [])
        if isinstance(ref, str)
    )

    return {
        "schema": QC_REPORT_SCHEMA,
        "summary": {
            "status": status,
            "check_count": len(checks),
            "pass_count": severity_counts["pass"],
            "warning_count": severity_counts["warning"],
            "blocking_issue_count": severity_counts["blocking"],
            "evidence_ref_count": len(evidence_refs),
        },
        "severity_counts": severity_counts,
        "checks": checks,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "evidence_refs": evidence_refs,
    }


def _timeline_structure_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    evidence_refs: list[str] = []
    codes: list[str] = []

    plan = _mapping(input_payload.get("composition_plan"))
    for index, issue in enumerate(_list(plan.get("errors")) if plan else []):
        evidence_refs.append(f"composition_plan.errors[{index}]")
        if isinstance(issue, Mapping):
            codes.append(_safe_code(issue.get("code")))

    timeline = _mapping(input_payload.get("timeline"))
    if timeline is not None:
        for clip in _timeline_clips(timeline):
            if clip["start_seconds"] < -_EPSILON:
                evidence_refs.append(clip["evidence_ref"])
                codes.append("negative_start")
            if clip["duration_seconds"] < -_EPSILON:
                evidence_refs.append(clip["evidence_ref"])
                codes.append("negative_duration")
            if clip["end_seconds"] + _EPSILON < clip["start_seconds"]:
                evidence_refs.append(clip["evidence_ref"])
                codes.append("end_before_start")

    if evidence_refs:
        return _check(
            "timeline.structure",
            "blocking",
            "Timeline has blocking structure or composition errors.",
            evidence_refs=evidence_refs,
            details={"issue_count": len(evidence_refs), "issue_codes": _unique_ref(codes)},
        )
    return _check("timeline.structure", "pass", "Timeline structure checks passed.")


def _timeline_overlap_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    evidence_refs: list[str] = []

    plan = _mapping(input_payload.get("composition_plan"))
    for index, issue in enumerate(_list(plan.get("warnings")) if plan else []):
        if isinstance(issue, Mapping) and _safe_code(issue.get("code")) == "track_overlap":
            evidence_refs.append(f"composition_plan.warnings[{index}]")

    timeline = _mapping(input_payload.get("timeline"))
    if timeline is not None:
        by_track: dict[int, list[dict[str, Any]]] = {}
        for clip in _timeline_clips(timeline):
            by_track.setdefault(int(clip["track_index"]), []).append(clip)
        for clips in by_track.values():
            previous: dict[str, Any] | None = None
            for clip in sorted(clips, key=lambda item: (item["start_seconds"], item["end_seconds"])):
                if previous is not None and previous["end_seconds"] - clip["start_seconds"] > _EPSILON:
                    evidence_refs.append(clip["evidence_ref"])
                if previous is None or clip["end_seconds"] > previous["end_seconds"]:
                    previous = clip

    if evidence_refs:
        return _check(
            "timeline.overlap",
            "warning",
            "Timeline has same-track clip overlaps.",
            evidence_refs=evidence_refs,
            details={"overlap_count": len(evidence_refs)},
        )
    return _check("timeline.overlap", "pass", "No same-track clip overlaps detected.")


def _subtitle_bounds_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    subtitles = _subtitle_segments(input_payload)
    duration = _video_duration_seconds(input_payload) or _timeline_duration_seconds(
        _mapping(input_payload.get("timeline"))
    )
    evidence_refs: list[str] = []

    if subtitles and duration is not None:
        for subtitle in subtitles:
            if (
                subtitle["start_seconds"] < -_EPSILON
                or subtitle["end_seconds"] + _EPSILON < subtitle["start_seconds"]
                or subtitle["end_seconds"] - duration > _EPSILON
            ):
                evidence_refs.append(subtitle["evidence_ref"])

    if evidence_refs:
        return _check(
            "subtitle.bounds",
            "blocking",
            "Subtitle timing falls outside the video bounds.",
            evidence_refs=evidence_refs,
            details={"subtitle_issue_count": len(evidence_refs)},
        )
    return _check("subtitle.bounds", "pass", "Subtitle bounds checks passed.")


def _media_drift_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    video_duration = _video_duration_seconds(input_payload)
    audio_duration = _audio_duration_seconds(input_payload)
    threshold = _positive_seconds(
        input_payload.get("drift_warning_threshold_seconds"),
        _DEFAULT_DRIFT_WARNING_SECONDS,
    )

    if video_duration is None or audio_duration is None:
        return _check(
            "media.drift",
            "pass",
            "Audio/video drift check has insufficient duration evidence.",
        )

    drift = round(audio_duration - video_duration, 3)
    if abs(drift) > threshold:
        return _check(
            "media.drift",
            "warning",
            "Audio and video durations differ beyond the configured threshold.",
            evidence_refs=["media.duration.audio", "media.duration.video"],
            details={
                "audio_duration_seconds": round(audio_duration, 3),
                "video_duration_seconds": round(video_duration, 3),
                "drift_seconds": drift,
                "threshold_seconds": threshold,
            },
        )
    return _check("media.drift", "pass", "Audio/video drift is within threshold.")


def _brand_keyword_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    brand_kit = _mapping(input_payload.get("brand_kit")) or {}
    required_keywords = _string_list(brand_kit.get("required_keywords"))
    forbidden_keywords = _string_list(brand_kit.get("forbidden_keywords"))
    corpus = _text_corpus(input_payload)
    normalized_corpus = corpus.casefold()

    missing_required = [
        index
        for index, keyword in enumerate(required_keywords)
        if keyword.casefold() not in normalized_corpus
    ]
    present_forbidden = [
        index
        for index, keyword in enumerate(forbidden_keywords)
        if keyword.casefold() in normalized_corpus
    ]

    if present_forbidden:
        return _check(
            "brand.keywords",
            "blocking",
            "Brand keyword rules found forbidden terms.",
            evidence_refs=[f"brand_kit.forbidden_keywords[{index}]" for index in present_forbidden],
            details={"forbidden_keyword_count": len(present_forbidden)},
        )
    if missing_required:
        return _check(
            "brand.keywords",
            "warning",
            "Brand keyword rules are missing required terms.",
            evidence_refs=[f"brand_kit.required_keywords[{index}]" for index in missing_required],
            details={"missing_required_keyword_count": len(missing_required)},
        )
    return _check("brand.keywords", "pass", "Brand keyword checks passed.")


def _brand_safe_area_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    brand_kit = _mapping(input_payload.get("brand_kit")) or {}
    visual_quality = _mapping(input_payload.get("visual_quality")) or {}
    safe_area = _safe_area_box(brand_kit.get("required_safe_area"))
    visual_violations = _list(visual_quality.get("safe_area_violations"))
    evidence_refs = [
        f"visual_quality.safe_area_violations[{index}]"
        for index, _ in enumerate(visual_violations)
    ]
    missing_position_refs: list[str] = []

    if safe_area is not None:
        for overlay in _text_overlays(input_payload):
            bbox = _normalized_bbox(overlay.get("bbox"))
            if bbox is None:
                missing_position_refs.append(str(overlay["evidence_ref"]))
                continue
            if not _bbox_inside_safe_area(bbox, safe_area):
                evidence_refs.append(str(overlay["evidence_ref"]))

    if evidence_refs:
        return _check(
            "brand.safe_area",
            "blocking",
            "Brand safe-area rules have blocking violations.",
            evidence_refs=evidence_refs,
            details={"safe_area_violation_count": len(evidence_refs)},
        )
    if missing_position_refs:
        return _check(
            "brand.safe_area",
            "warning",
            "Brand safe-area rules could not verify every text overlay position.",
            evidence_refs=missing_position_refs,
            details={"missing_position_count": len(missing_position_refs)},
        )
    return _check("brand.safe_area", "pass", "Brand safe-area checks passed.")


def _check(
    check_id: str,
    severity: str,
    message: str,
    *,
    evidence_refs: list[str] | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status = "passed" if severity == "pass" else "warning" if severity == "warning" else "failed"
    check: dict[str, Any] = {
        "check_id": check_id,
        "status": status,
        "severity": severity,
        "message": message,
        "evidence_refs": _unique_ref(evidence_refs or []),
    }
    if details:
        check["details"] = dict(details)
    return check


def _timeline_clips(timeline: Mapping[str, Any]) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    raw_tracks = timeline.get("tracks", {})
    track_items: list[tuple[int, Any, Any]]
    if isinstance(raw_tracks, Mapping):
        track_items = [
            (index, track_id, raw_tracks[track_id])
            for index, track_id in enumerate(sorted(raw_tracks, key=str))
        ]
    elif isinstance(raw_tracks, list):
        track_items = [(index, index, track) for index, track in enumerate(raw_tracks)]
    else:
        return []

    for track_index, _track_id, raw_track in track_items:
        if not isinstance(raw_track, Mapping):
            continue
        track_kind = _kind(raw_track.get("kind"), "video")
        raw_clips = raw_track.get("clips", [])
        if not isinstance(raw_clips, list):
            continue
        for clip_index, raw_clip in enumerate(raw_clips):
            if not isinstance(raw_clip, Mapping):
                continue
            start = _seconds(raw_clip.get("timeline_start_seconds", raw_clip.get("start_seconds", 0.0)))
            duration = _clip_duration(raw_clip)
            clips.append(
                {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "kind": _kind(raw_clip.get("kind"), track_kind),
                    "start_seconds": start,
                    "duration_seconds": duration,
                    "end_seconds": start + duration,
                    "text": str(raw_clip.get("text") or ""),
                    "bbox": _overlay_bbox(raw_clip),
                    "evidence_ref": f"timeline.tracks[{track_index}].clips[{clip_index}]",
                }
            )
    return clips


def _subtitle_segments(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = input_payload.get("subtitles", input_payload.get("subtitle_segments"))
    if isinstance(raw, Mapping):
        raw = raw.get("segments", raw.get("subtitles", raw.get("items", [])))
    if not isinstance(raw, list):
        return []

    subtitles: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            continue
        start = _seconds(item.get("start_seconds", item.get("start", 0.0)))
        end = _seconds(item.get("end_seconds", item.get("end", start)))
        subtitles.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "text": str(item.get("text") or item.get("caption") or ""),
                "bbox": _overlay_bbox(item),
                "evidence_ref": f"subtitles[{index}]",
            }
        )
    return subtitles


def _text_overlays(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    overlays: list[dict[str, Any]] = []
    plan = _mapping(input_payload.get("composition_plan"))
    if plan is not None:
        for index, item in enumerate(_list(plan.get("text_overlays"))):
            if isinstance(item, Mapping):
                overlays.append(
                    {
                        "bbox": _overlay_bbox(item),
                        "text": str(item.get("text") or ""),
                        "evidence_ref": f"composition_plan.text_overlays[{index}]",
                    }
                )

    for clip in _timeline_clips(_mapping(input_payload.get("timeline")) or {}):
        if clip["kind"] == "text":
            overlays.append(clip)

    for subtitle in _subtitle_segments(input_payload):
        if subtitle["bbox"] is not None:
            overlays.append(subtitle)
    return overlays


def _text_corpus(input_payload: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    raw_corpus = input_payload.get("text_corpus")
    if isinstance(raw_corpus, str):
        chunks.append(raw_corpus)
    for subtitle in _subtitle_segments(input_payload):
        chunks.append(str(subtitle.get("text") or ""))
    for overlay in _text_overlays(input_payload):
        chunks.append(str(overlay.get("text") or ""))
    return "\n".join(chunks)


def _video_duration_seconds(input_payload: Mapping[str, Any]) -> float | None:
    plan = _mapping(input_payload.get("composition_plan"))
    visual_quality = _mapping(input_payload.get("visual_quality")) or {}
    summary = _mapping(plan.get("summary")) if plan else None
    return _first_seconds(
        summary.get("video_duration_seconds") if summary else None,
        summary.get("duration_seconds") if summary else None,
        _nested_value(visual_quality, ("quality_summary", "duration_seconds")),
        _nested_value(visual_quality, ("summary", "duration_seconds")),
        visual_quality.get("duration_seconds"),
        _timeline_duration_seconds(_mapping(input_payload.get("timeline"))),
    )


def _audio_duration_seconds(input_payload: Mapping[str, Any]) -> float | None:
    plan = _mapping(input_payload.get("composition_plan"))
    audio_quality = _mapping(input_payload.get("audio_quality")) or {}
    summary = _mapping(plan.get("summary")) if plan else None
    return _first_seconds(
        summary.get("audio_duration_seconds") if summary else None,
        _nested_value(audio_quality, ("quality_summary", "duration_seconds")),
        _nested_value(audio_quality, ("summary", "duration_seconds")),
        audio_quality.get("duration_seconds"),
    )


def _timeline_duration_seconds(timeline: Mapping[str, Any] | None) -> float | None:
    if timeline is None:
        return None
    clips = _timeline_clips(timeline)
    if not clips:
        return None
    return round(max(clip["end_seconds"] for clip in clips), 3)


def _clip_duration(clip: Mapping[str, Any]) -> float:
    if "duration_seconds" in clip:
        return _seconds(clip.get("duration_seconds"))
    source_in = _seconds(clip.get("source_in_seconds", 0.0))
    source_out = _seconds(clip.get("source_out_seconds", source_in))
    return source_out - source_in


def _overlay_bbox(item: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    for candidate in (
        item.get("normalized_bbox"),
        item.get("safe_area_bbox"),
        item.get("bbox"),
    ):
        bbox = _normalized_bbox(candidate)
        if bbox is not None:
            return bbox
    style = _mapping(item.get("style")) or {}
    position = _mapping(item.get("position")) or {}
    for candidate in (
        style.get("normalized_bbox"),
        style.get("safe_area_bbox"),
        style.get("bbox"),
        position.get("normalized_bbox"),
        position.get("bbox"),
        style,
        position,
    ):
        bbox = _normalized_bbox(candidate)
        if bbox is not None:
            return bbox
    return None


def _normalized_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        numbers = [_ratio(item) for item in value]
        if all(item is not None for item in numbers):
            return tuple(numbers)  # type: ignore[return-value]
    if isinstance(value, Mapping):
        x = _ratio(value.get("x", value.get("left")))
        y = _ratio(value.get("y", value.get("top")))
        width = _ratio(value.get("width", value.get("w")))
        height = _ratio(value.get("height", value.get("h")))
        if None not in {x, y, width, height}:
            return (x, y, width, height)  # type: ignore[return-value]
    return None


def _safe_area_box(value: Any) -> tuple[float, float, float, float] | None:
    safe_area = _mapping(value)
    if safe_area is None:
        return None
    left = _ratio(safe_area.get("left", safe_area.get("x_min", 0.0))) or 0.0
    top = _ratio(safe_area.get("top", safe_area.get("y_min", 0.0))) or 0.0
    raw_right = _ratio(safe_area.get("right", safe_area.get("x_max", 1.0)))
    raw_bottom = _ratio(safe_area.get("bottom", safe_area.get("y_max", 1.0)))
    if raw_right is None or raw_bottom is None:
        return None
    right = 1.0 - raw_right if raw_right <= 0.5 and left + raw_right < 1.0 else raw_right
    bottom = 1.0 - raw_bottom if raw_bottom <= 0.5 and top + raw_bottom < 1.0 else raw_bottom
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _bbox_inside_safe_area(
    bbox: tuple[float, float, float, float],
    safe_area: tuple[float, float, float, float],
) -> bool:
    x, y, width, height = bbox
    left, top, right, bottom = safe_area
    return (
        x + _EPSILON >= left
        and y + _EPSILON >= top
        and x + width <= right + _EPSILON
        and y + height <= bottom + _EPSILON
    )


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _kind(value: Any, fallback: str) -> str:
    return str(value) if value in {"video", "audio", "text"} else fallback


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _positive_seconds(value: Any, default: float) -> float:
    parsed = _seconds(value)
    return parsed if parsed > 0 else default


def _first_seconds(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        parsed = _seconds(value)
        if parsed > 0:
            return parsed
    return None


def _ratio(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    ratio = float(value)
    if ratio > 1.0:
        ratio = ratio / 100.0
    if ratio < 0.0 or ratio > 1.0:
        return None
    return ratio


def _nested_value(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _safe_code(value: Any) -> str:
    text = str(value or "issue")
    safe = _SAFE_CODE_PATTERN.sub("_", text).strip("_.-")
    return safe or "issue"


def _unique_ref(values: Any) -> list[str]:
    unique: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value not in unique:
            unique.append(value)
    return unique


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
