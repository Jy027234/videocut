"""P0 manifest and JSON Schema acceptance checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

from conftest import (
    MANIFESTS_DIR,
    SCHEMAS_DIR,
    assert_no_public_path_or_command_leak,
    load_json,
    require_json_files,
)
from video_editing_toolkit.adapters import CAPABILITY_ROUTES
from video_editing_toolkit.agentctl import NO_UPLOAD_CAPABILITIES
from video_editing_toolkit.runtime import adapter_run_handler, register_p0_adapter_handlers

jsonschema = pytest.importorskip("jsonschema")


REQUIRED_MANIFEST_FIELDS = {
    "toolkit_id",
    "display_name",
    "category",
    "version",
    "capabilities",
    "error_codes",
    "status",
}

REQUIRED_CAPABILITY_FIELDS = {
    "capability",
    "input_schema",
    "output_schema",
    "required_permissions",
    "required_scopes",
    "quota_metrics",
    "pricing_metrics",
    "data_sensitivity",
    "approval_policy",
    "sandbox_policy",
    "artifact_policy",
}

REQUIRED_ERROR_CODES = {
    "unauthorized",
    "invalid_schema",
    "artifact_forbidden",
    "quota_exceeded",
    "timeout",
    "worker_failed",
}

HIGH_SENSITIVITY = {"high", "restricted", "biometric", "voice"}


def test_manifest_files_parse_and_keep_required_p0_fields() -> None:
    manifest_paths = require_json_files(
        MANIFESTS_DIR,
        "No manifest JSON files exist yet; enable this gate when toolkit-manifest-agent lands manifests.",
    )

    for path in manifest_paths:
        manifest = load_json(path)
        missing = REQUIRED_MANIFEST_FIELDS - set(manifest)
        assert not missing, f"{path} missing manifest fields: {sorted(missing)}"
        assert isinstance(manifest["capabilities"], list) and manifest["capabilities"], (
            f"{path} must declare at least one capability"
        )

        error_codes = _names(manifest["error_codes"])
        assert REQUIRED_ERROR_CODES.issubset(error_codes), (
            f"{path} must include stable error codes: {sorted(REQUIRED_ERROR_CODES - error_codes)}"
        )

        for capability in manifest["capabilities"]:
            missing_capability_fields = REQUIRED_CAPABILITY_FIELDS - set(capability)
            assert not missing_capability_fields, (
                f"{path} capability {capability.get('capability', '<unknown>')} missing fields: "
                f"{sorted(missing_capability_fields)}"
            )
            if capability.get("data_sensitivity") in HIGH_SENSITIVITY:
                approval = capability.get("approval_policy")
                assert approval and approval != "none", (
                    f"{path} high-sensitivity capability {capability.get('capability')} needs approval_policy"
                )


def test_manifest_public_contract_does_not_leak_local_runtime_details() -> None:
    for path in require_json_files(MANIFESTS_DIR, "No manifests to scan for public-contract leakage yet."):
        assert_no_public_path_or_command_leak(load_json(path))


def test_schema_files_are_valid_json_schema_documents() -> None:
    schema_paths = require_json_files(
        SCHEMAS_DIR,
        "No schema JSON files exist yet; enable this gate when toolkit-manifest-agent lands schemas.",
    )

    for path in schema_paths:
        schema = load_json(path)
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)


def test_manifest_schema_references_are_resolvable() -> None:
    manifest_paths = require_json_files(MANIFESTS_DIR, "No manifests to check schema references yet.")

    for path in manifest_paths:
        manifest = load_json(path)
        for location, ref in _manifest_schema_refs(manifest):
            target_path, fragment = _resolve_schema_ref(path, ref)
            assert target_path.is_file(), f"{path} {location} references missing schema {ref!r}"
            target = load_json(target_path)
            _resolve_json_pointer(target, fragment, source=f"{path} {location} -> {ref!r}")


def test_enabled_manifest_capabilities_match_runtime_and_local_entrypoints() -> None:
    manifest_paths = require_json_files(MANIFESTS_DIR, "No manifests to compare against runtime routes yet.")
    enabled_capabilities: set[str] = set()

    for path in manifest_paths:
        manifest = load_json(path)
        for capability in manifest.get("capabilities", []):
            if capability.get("status") == "enabled":
                name = capability.get("capability")
                assert isinstance(name, str) and name, f"{path} contains an enabled capability without a name"
                enabled_capabilities.add(name)

    route_capabilities = set(CAPABILITY_ROUTES)
    assert enabled_capabilities == route_capabilities, _set_delta_message(
        "enabled manifest capabilities",
        enabled_capabilities,
        "CAPABILITY_ROUTES",
        route_capabilities,
    )

    recorder = _HandlerRegistrationRecorder()
    register_p0_adapter_handlers(recorder)
    registered_capabilities = {capability for toolkit_id, capability, _handler in recorder.handlers}
    assert registered_capabilities == route_capabilities, _set_delta_message(
        "register_p0_adapter_handlers",
        registered_capabilities,
        "CAPABILITY_ROUTES",
        route_capabilities,
    )
    assert {
        toolkit_id for toolkit_id, _capability, _handler in recorder.handlers
    } == {"video-editing-toolkit"}
    assert all(handler is adapter_run_handler for _toolkit_id, _capability, handler in recorder.handlers)
    assert set(NO_UPLOAD_CAPABILITIES).issubset(route_capabilities), _set_delta_message(
        "agentctl no-upload capability allowlist",
        set(NO_UPLOAD_CAPABILITIES),
        "CAPABILITY_ROUTES",
        route_capabilities,
    )


def _names(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value)
    if isinstance(value, list):
        names: set[str] = set()
        for item in value:
            if isinstance(item, str):
                names.add(item.lower())
            elif isinstance(item, dict) and isinstance(item.get("code"), str):
                names.add(item["code"].lower())
        return names
    return set()


def _manifest_schema_refs(manifest: Mapping[str, Any]) -> Iterable[tuple[str, str]]:
    for field in ("input_schema", "output_schema"):
        ref = _schema_ref_string(manifest.get(field))
        assert ref, f"manifest top-level {field} must provide a schema ref"
        yield f"top-level {field}", ref

    for capability in manifest.get("capabilities", []):
        assert isinstance(capability, Mapping), f"manifest capability entries must be objects: {capability!r}"
        capability_name = capability.get("capability", "<unknown>")
        for field in ("input_schema", "output_schema"):
            ref = _schema_ref_string(capability.get(field))
            assert ref, f"capability {capability_name} must provide {field}"
            yield f"capability {capability_name} {field}", ref


def _schema_ref_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        ref = value.get("$ref") or value.get("ref")
        if isinstance(ref, str):
            return ref
    return None


def _resolve_schema_ref(source_path: Path, ref: str) -> tuple[Path, str]:
    document_ref, separator, fragment = ref.partition("#")
    if document_ref:
        target_path = (source_path.parent / document_ref).resolve()
    else:
        target_path = source_path.resolve()
    if not separator:
        fragment = ""
    return target_path, fragment


def _resolve_json_pointer(document: Any, fragment: str, *, source: str) -> Any:
    if fragment in {"", "/"}:
        return document
    assert fragment.startswith("/"), f"{source} uses a non-JSON-pointer fragment: {fragment!r}"

    current = document
    for raw_part in fragment.removeprefix("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            assert part in current, f"{source} cannot resolve fragment segment {part!r}"
            current = current[part]
        elif isinstance(current, list):
            assert part.isdigit(), f"{source} uses non-numeric array segment {part!r}"
            index = int(part)
            assert index < len(current), f"{source} array segment {part!r} is out of range"
            current = current[index]
        else:
            raise AssertionError(f"{source} cannot descend into {type(current).__name__}")
    return current


def _set_delta_message(left_name: str, left: set[str], right_name: str, right: set[str]) -> str:
    return (
        f"{left_name} and {right_name} differ; "
        f"missing_from_{left_name}={sorted(right - left)}, "
        f"missing_from_{right_name}={sorted(left - right)}"
    )


class _HandlerRegistrationRecorder:
    def __init__(self) -> None:
        self.handlers: list[tuple[str, str, Any]] = []

    def register_handler(self, toolkit_id: str, capability: str, handler: Any) -> None:
        self.handlers.append((toolkit_id, capability, handler))
