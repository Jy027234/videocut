"""Validation for structured timeline_patch payloads.

The P0 contract intentionally allows only declarative edit operations. Raw
scripts, shell snippets, command keys, or command-like escape hatches are
rejected before any project state is touched.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ALLOWED_OPERATIONS = frozenset(
    {
        "add_clip",
        "remove_clip",
        "split_clip",
        "move_clip",
        "set_in_out",
        "add_text",
        "add_audio",
        "set_transition",
        "set_effect",
    }
)

FORBIDDEN_PATCH_KEYS = frozenset(
    {
        "script",
        "command",
        "shell",
        "expression",
        "eval",
        "exec",
        "raw_command",
        "ffmpeg_command",
    }
)

REGISTERED_EFFECTS = frozenset(
    {
        "registered.blur",
        "registered.brightness",
        "registered.contrast",
        "registered.crop",
        "registered.fade",
        "registered.volume",
    }
)

REGISTERED_TRANSITIONS = frozenset(
    {
        "registered.cut",
        "registered.crossfade",
        "registered.fade",
        "cut",
        "crossfade",
        "fade",
    }
)


class TimelinePatchValidationError(ValueError):
    """Stable validation failure raised by the P0 project edit core."""

    def __init__(self, stable_code: str, message: str) -> None:
        self.stable_code = stable_code
        super().__init__(message)


def validate_timeline_patch(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate a project edit request and return copied patch operations."""

    if not _non_empty_string(request.get("project_id")):
        raise TimelinePatchValidationError("invalid_schema", "project_id is required.")
    if not _non_empty_string(request.get("base_version_id")):
        raise TimelinePatchValidationError("invalid_schema", "base_version_id is required.")
    if not _non_empty_string(request.get("change_reason")):
        raise TimelinePatchValidationError("invalid_schema", "change_reason is required.")

    patch = request.get("timeline_patch")
    if not isinstance(patch, Mapping):
        raise TimelinePatchValidationError("invalid_schema", "timeline_patch must be an object.")
    forbidden_key = _find_forbidden_key(patch)
    if forbidden_key is not None:
        raise TimelinePatchValidationError(
            "invalid_schema",
            f"timeline_patch contains forbidden key {forbidden_key!r}.",
        )

    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        raise TimelinePatchValidationError(
            "invalid_schema",
            "timeline_patch.operations must be a non-empty list.",
        )

    normalized: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            raise TimelinePatchValidationError(
                "invalid_schema",
                f"operation {index} must be an object.",
            )
        op = operation.get("op")
        if op not in ALLOWED_OPERATIONS:
            raise TimelinePatchValidationError(
                "invalid_schema",
                f"operation {index} uses unsupported op {op!r}.",
            )

        copied = dict(operation)
        _validate_operation_shape(index, copied)
        normalized.append(copied)

    return normalized


def _validate_operation_shape(index: int, operation: Mapping[str, Any]) -> None:
    op = operation["op"]
    if op in {"add_clip", "add_audio", "add_text", "move_clip"}:
        _require_string(index, operation, "track_id")
    if op in {"remove_clip", "split_clip", "move_clip", "set_in_out", "set_transition", "set_effect"}:
        _require_string(index, operation, "clip_id")
    if op == "add_clip":
        _require_string(index, operation, "clip_id")
        if not isinstance(operation.get("asset_ref"), Mapping):
            raise TimelinePatchValidationError("invalid_schema", "add_clip requires asset_ref.")
    if op == "add_audio":
        if not (_non_empty_string(operation.get("clip_id")) or _non_empty_string(operation.get("audio_id"))):
            raise TimelinePatchValidationError("invalid_schema", "add_audio requires clip_id or audio_id.")
    if op == "add_text":
        _require_string(index, operation, "text_id")
        _require_string(index, operation, "text")
    if op == "set_effect":
        effect_id = operation.get("effect_id")
        if effect_id not in REGISTERED_EFFECTS:
            raise TimelinePatchValidationError(
                "unregistered_effect",
                f"effect_id {effect_id!r} is not registered.",
            )
    if op == "set_transition":
        transition_id = operation.get("transition_id") or operation.get("transition")
        if transition_id is not None and transition_id not in REGISTERED_TRANSITIONS:
            raise TimelinePatchValidationError(
                "invalid_schema",
                f"transition {transition_id!r} is not registered.",
            )


def _require_string(index: int, operation: Mapping[str, Any], key: str) -> None:
    if not _non_empty_string(operation.get(key)):
        raise TimelinePatchValidationError(
            "invalid_schema",
            f"operation {index} requires non-empty {key}.",
        )


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _find_forbidden_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in FORBIDDEN_PATCH_KEYS:
                return str(key)
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_forbidden_key(item)
            if found is not None:
                return found
    return None
