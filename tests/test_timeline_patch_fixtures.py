"""P0 timeline_patch fixture checks."""

from __future__ import annotations

from conftest import FIXTURES_DIR, assert_no_public_path_or_command_leak, load_json, require_json_files


ALLOWED_OPERATIONS = {
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

FORBIDDEN_PATCH_KEYS = {
    "script",
    "command",
    "shell",
    "expression",
    "eval",
    "exec",
    "raw_command",
    "ffmpeg_command",
}


def test_valid_timeline_patch_fixtures_cover_required_contract_fields() -> None:
    fixture_paths = require_json_files(
        FIXTURES_DIR / "timeline_patch" / "valid",
        "No valid timeline_patch fixtures exist yet.",
    )

    for path in fixture_paths:
        payload = load_json(path)
        request = payload["request"]
        assert request["project_id"]
        assert request["base_version_id"]
        assert request["change_reason"]
        operations = request["timeline_patch"]["operations"]
        assert isinstance(operations, list) and operations, f"{path} must include patch operations"

        for operation in operations:
            assert operation["op"] in ALLOWED_OPERATIONS, f"{path} uses unregistered op {operation['op']!r}"
            assert not (FORBIDDEN_PATCH_KEYS & set(operation)), (
                f"{path} operation {operation.get('op')} contains script/command-like keys"
            )

        if request.get("requested_preview"):
            output = payload["expected_output"]
            assert "preview_artifact_ref" in output, f"{path} must return preview_artifact_ref"
            assert_no_public_path_or_command_leak(output)


def test_invalid_timeline_patch_fixtures_are_rejected_by_contract_rules() -> None:
    fixture_paths = require_json_files(
        FIXTURES_DIR / "timeline_patch" / "invalid",
        "No invalid timeline_patch fixtures exist yet.",
    )

    for path in fixture_paths:
        payload = load_json(path)
        request = payload["request"]
        reasons = _contract_rejection_reasons(request)
        assert reasons, f"{path} must violate at least one P0 timeline_patch contract rule"
        assert payload.get("expected_error_code") in {"invalid_schema", "conflict", "unregistered_effect"}, (
            f"{path} must declare a stable expected_error_code"
        )


def _contract_rejection_reasons(request: dict[str, object]) -> list[str]:
    reasons: list[str] = []
    if not request.get("project_id"):
        reasons.append("missing_project_id")
    if not request.get("base_version_id"):
        reasons.append("missing_base_version_id")
    if not request.get("change_reason"):
        reasons.append("missing_change_reason")

    patch = request.get("timeline_patch")
    operations = patch.get("operations") if isinstance(patch, dict) else None
    if not isinstance(operations, list) or not operations:
        reasons.append("missing_operations")
        return reasons

    for operation in operations:
        if not isinstance(operation, dict):
            reasons.append("invalid_operation")
            continue
        op = operation.get("op")
        if op not in ALLOWED_OPERATIONS:
            reasons.append("unregistered_operation")
        if FORBIDDEN_PATCH_KEYS & set(operation):
            reasons.append("script_or_command_injection")
        if op == "set_effect" and operation.get("effect_id") == "unregistered.effect":
            reasons.append("unregistered_effect")
    return reasons
