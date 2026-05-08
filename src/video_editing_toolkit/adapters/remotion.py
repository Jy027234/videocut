"""Caller-safe Remotion template rendering contract adapter.

The adapter validates Remotion template metadata and emits a dispatcher-owned
render job specification. It never launches Node, Chromium, or Remotion itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter, TOOLKIT_ID


VALIDATE_REMOTION_TEMPLATE = "video.template.validate_remotion_template"
CREATE_REMOTION_RENDER_JOB = "video.template.create_remotion_render_job"
REMOTION_RENDER_JOB_ARTIFACT_TYPE = "remotion_render_job_json"
REMOTION_RENDER_JOB_SCHEMA = "video_editing_toolkit.remotion_render_job.v0"
REMOTION_VALIDATION_SCHEMA = "video_editing_toolkit.remotion_template_validation.v0"

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_LOCAL_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)[^\s\"']+"),
    re.compile(r"\\\\[^\\/\s\"']+[\\/][^\s\"']+"),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"local-artifact://", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])/(Users|home|var|tmp|private|mnt)/[^\s\"']+"),
)
_RAW_COMMAND_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])(?:npx|node|npm|pnpm|yarn)\s+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])remotion\s+render", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])(?:cmd|powershell)(?:\.exe)?\s+", re.IGNORECASE),
)
_FORBIDDEN_PUBLIC_KEYS = {
    "endpoint",
    "dispatcher_endpoint",
    "storage_uri",
    "local_path",
    "file_path",
    "filesystem_path",
    "worker_path",
    "internal_path",
    "raw_command",
    "raw_shell",
    "node_command",
    "chromium_path",
    "worker_url",
    "internal_worker_url",
    "token",
    "secret",
    "password",
    "api_key",
    "private_key",
    "client_secret",
    "authorization",
}


class RemotionTemplateError(ValueError):
    """Stable validation failure for the Remotion template contract."""

    def __init__(self, stable_code: str, message: str) -> None:
        self.stable_code = stable_code
        super().__init__(message)


class RemotionAdapter(BaseAdapter):
    adapter_name = "remotion"
    supported_capabilities = frozenset(
        {
            VALIDATE_REMOTION_TEMPLATE,
            CREATE_REMOTION_RENDER_JOB,
        }
    )
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        try:
            validation = validate_remotion_template_request(request.input)
            if request.context.capability == VALIDATE_REMOTION_TEMPLATE:
                return AdapterResult(
                    status=AdapterStatus.SUCCEEDED,
                    output=validation,
                    usage_metrics=_usage_metrics(request.context.capability),
                )

            render_job = build_remotion_render_job(request, validation)
            dispatcher_readiness = build_dispatcher_readiness(request.input)
            render_job["dispatcher_readiness"] = dispatcher_readiness
            output: dict[str, Any] = {
                "schema": REMOTION_RENDER_JOB_SCHEMA,
                "dispatcher_required": True,
                "status": "dispatcher_required",
                "render_job": render_job,
                "dispatcher_readiness": dispatcher_readiness,
                "render_job_id": render_job["render_job_id"],
                "composition_id": validation["composition"]["composition_id"],
                "chromium_required": True,
                "license_confirmation_required": True,
            }
            artifact_refs = self._materialize_render_job_artifact(request, output)
            if artifact_refs:
                output["render_job_artifact_ref"] = artifact_refs[0].to_public_dict()
                output["artifact_refs"] = [ref.to_public_dict() for ref in artifact_refs]
            return AdapterResult(
                status=AdapterStatus.SUCCEEDED,
                output=output,
                artifact_refs=artifact_refs,
                usage_metrics=_usage_metrics(request.context.capability, artifact_refs),
            )
        except RemotionTemplateError as exc:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                output={
                    "schema": REMOTION_VALIDATION_SCHEMA,
                    "valid": False,
                    "stable_error_code": exc.stable_code,
                },
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=str(exc),
            )

        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def _materialize_render_job_artifact(
        self,
        request: AdapterRequest,
        output: Mapping[str, Any],
    ) -> tuple[ArtifactRef, ...]:
        artifact_store = request.input.get("_artifact_store")
        if not isinstance(artifact_store, LocalArtifactStore):
            return ()

        ref = artifact_store.put_bytes(
            content=_json_bytes(output),
            artifact_type=REMOTION_RENDER_JOB_ARTIFACT_TYPE,
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="remotion_render_job.json",
            mime_type="application/json",
        )
        return (ref,)


def validate_remotion_template_request(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    _assert_caller_safe(input_payload, path="$")
    manifest = _mapping(input_payload.get("template_manifest") or input_payload.get("manifest"), "$.template_manifest")
    props = _mapping(input_payload.get("props", {}), "$.props")
    render_settings = _mapping(input_payload.get("render_settings", {}), "$.render_settings")

    template_id = _safe_id(str(manifest.get("template_id") or manifest.get("id") or ""), "$.template_manifest.template_id")
    template_version = str(manifest.get("version") or "unversioned")
    composition_id = _safe_id(str(input_payload.get("composition_id") or ""), "$.composition_id")
    compositions = _sequence(manifest.get("compositions"), "$.template_manifest.compositions")
    selected = _select_composition(compositions, composition_id)

    duration_frames = _positive_int(
        _first_present(
            render_settings,
            input_payload,
            selected,
            keys=("duration_frames", "duration_in_frames", "durationInFrames"),
        ),
        "$.composition.duration_frames",
        minimum=1,
        maximum=60 * 60 * 120,
    )
    fps = _positive_int(
        _first_present(render_settings, input_payload, selected, keys=("fps",)),
        "$.composition.fps",
        minimum=1,
        maximum=120,
    )
    width = _positive_int(
        _first_present(render_settings, input_payload, selected, keys=("width",)),
        "$.composition.width",
        minimum=16,
        maximum=8192,
    )
    height = _positive_int(
        _first_present(render_settings, input_payload, selected, keys=("height",)),
        "$.composition.height",
        minimum=16,
        maximum=8192,
    )

    props_schema = _mapping(
        selected.get("props_schema") or manifest.get("props_schema") or {},
        "$.template_manifest.props_schema",
    )
    default_props = dict(
        _mapping(
            selected.get("default_props") or manifest.get("default_props") or {},
            "$.template_manifest.default_props",
        )
    )
    merged_props = default_props | dict(props)
    _validate_props(merged_props, props_schema)

    composition_summary = {
        "composition_id": composition_id,
        "duration_frames": duration_frames,
        "fps": fps,
        "duration_seconds": round(duration_frames / fps, 6),
        "width": width,
        "height": height,
    }
    return {
        "schema": REMOTION_VALIDATION_SCHEMA,
        "valid": True,
        "template_id": template_id,
        "template_version": template_version,
        "composition": composition_summary,
        "props_summary": {
            "provided_keys": sorted(str(key) for key in props),
            "defaulted_keys": sorted(str(key) for key in default_props.keys() - props.keys()),
            "required_keys": sorted(
                str(key) for key in props_schema.get("required", []) if isinstance(key, str)
            ),
        },
        "manifest_summary": {
            "composition_count": len(compositions),
            "manifest_digest": _digest_json(_public_manifest_summary(manifest)),
        },
        "chromium_required": False,
        "dispatcher_required": False,
        "runtime_execution": "not_started",
        "props": _caller_safe_mapping(merged_props),
        "template_artifact_ref": _public_artifact_ref(input_payload.get("template_artifact_ref")),
    }


def build_remotion_render_job(
    request: AdapterRequest,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    composition = dict(_mapping(validation.get("composition"), "$.validation.composition"))
    render_format = _render_format(request.input)
    job_seed = {
        "run_id": request.context.run_id,
        "template_id": validation["template_id"],
        "template_version": validation["template_version"],
        "composition": composition,
        "props": validation.get("props", {}),
        "format": render_format,
    }
    render_job_id = f"remotion_job_{_digest_json(job_seed)[:24]}"
    template_artifact_ref = validation.get("template_artifact_ref")

    return {
        "schema": REMOTION_RENDER_JOB_SCHEMA,
        "render_job_id": render_job_id,
        "toolkit_id": TOOLKIT_ID,
        "capability": CREATE_REMOTION_RENDER_JOB,
        "status": "dispatcher_required",
        "dispatcher_required": True,
        "adapter_name": RemotionAdapter.adapter_name,
        "tenant_id": request.context.tenant_id,
        "project_id": request.context.project_id,
        "run_id": request.context.run_id,
        "tool_call_id": request.context.tool_call_id,
        "template": {
            "template_id": validation["template_id"],
            "template_version": validation["template_version"],
            "composition_id": composition["composition_id"],
            "template_artifact_ref": template_artifact_ref,
        },
        "props": validation.get("props", {}),
        "render_settings": {
            "duration_frames": composition["duration_frames"],
            "fps": composition["fps"],
            "duration_seconds": composition["duration_seconds"],
            "width": composition["width"],
            "height": composition["height"],
            "format": render_format,
        },
        "required_runtime": {
            "engine": "remotion",
            "nodejs": "required_by_dispatcher",
            "chromium": "required_by_dispatcher",
            "renderer": "external_dispatcher",
        },
        "sandbox": {
            "execution": "dispatcher_managed",
            "filesystem": "artifact_ref_only",
            "network": "deny_by_default",
            "egress": "deny_by_default",
            "secrets": "not_exposed_to_template_contract",
            "max_duration_seconds": composition["duration_seconds"],
        },
        "license_confirmation_required": True,
        "chromium_required": True,
        "command_materialization": "dispatcher_only",
    }


def build_dispatcher_readiness(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    attestation = _optional_mapping(
        input_payload.get("dispatcher_preflight_attestation"),
        "$.dispatcher_preflight_attestation",
    )
    if attestation is not None:
        return _dispatcher_readiness_from_attestation(attestation)

    capabilities = _optional_mapping(input_payload.get("dispatcher_capabilities"), "$.dispatcher_capabilities")
    policy = _optional_mapping(input_payload.get("dispatcher_policy"), "$.dispatcher_policy")
    has_preflight_input = (
        capabilities is not None
        or policy is not None
        or "license_confirmation" in input_payload
    )

    checks = [
        _runtime_check("nodejs", capabilities, "nodejs"),
        _runtime_check("chromium", capabilities, "chromium"),
        _runtime_check("remotion", capabilities, "remotion"),
        _license_check(input_payload.get("license_confirmation"), has_preflight_input),
        _sandbox_check(policy),
        _network_check(policy),
    ]
    blocked = any(check["status"] == "blocked" for check in checks)
    ready = all(check["status"] == "ready" for check in checks)
    status = "blocked" if blocked else "ready" if ready else "unknown"
    return {
        "status": status,
        "runtime_execution": "not_started",
        "preflight_source": "caller_provided" if has_preflight_input else "not_provided",
        "checks": checks,
    }


def _dispatcher_readiness_from_attestation(attestation: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _optional_mapping(
        attestation.get("runtime"),
        "$.dispatcher_preflight_attestation.runtime",
    ) or {}
    sandbox = _optional_mapping(
        attestation.get("sandbox"),
        "$.dispatcher_preflight_attestation.sandbox",
    ) or {}
    network = _optional_mapping(
        attestation.get("network"),
        "$.dispatcher_preflight_attestation.network",
    ) or {}
    license_info = _optional_mapping(
        attestation.get("license"),
        "$.dispatcher_preflight_attestation.license",
    ) or {}
    execution = _optional_mapping(
        attestation.get("execution"),
        "$.dispatcher_preflight_attestation.execution",
    ) or {}

    checks = [
        _attestation_runtime_check("nodejs", runtime.get("nodejs")),
        _attestation_runtime_check("chromium", runtime.get("chromium")),
        _attestation_runtime_check("remotion", runtime.get("remotion")),
        _attestation_license_check(license_info),
        _attestation_sandbox_check(sandbox),
        _attestation_network_check(network),
        _attestation_execution_check(execution),
    ]
    blocked = any(check["status"] == "blocked" for check in checks)
    ready = all(check["status"] == "ready" for check in checks)
    status = "blocked" if blocked else "ready" if ready else "unknown"
    return {
        "status": status,
        "runtime_execution": "not_started",
        "preflight_source": "dispatcher_attestation",
        "checks": checks,
    }


def _attestation_runtime_check(name: str, value: Any) -> dict[str, str]:
    normalized = str(value or "unknown").lower()
    if normalized == "ready":
        return _readiness_check(name, "ready", "attested_runtime_ready")
    if normalized == "unavailable":
        return _readiness_check(name, "blocked", "attested_runtime_unavailable")
    return _readiness_check(name, "unknown", "attested_runtime_unknown")


def _attestation_license_check(value: Mapping[str, Any]) -> dict[str, str]:
    if value.get("confirmed") is True:
        return _readiness_check("license", "ready", "attested_license_confirmed")
    return _readiness_check("license", "blocked", "attested_license_confirmation_required")


def _attestation_sandbox_check(value: Mapping[str, Any]) -> dict[str, str]:
    execution = str(value.get("execution") or "").lower()
    filesystem = str(value.get("filesystem") or "").lower()
    if execution == "dispatcher_managed" and filesystem == "artifact_ref_only":
        return _readiness_check("sandbox", "ready", "attested_dispatcher_managed_artifact_ref_only")
    return _readiness_check("sandbox", "blocked", "attested_sandbox_policy_noncompliant")


def _attestation_network_check(value: Mapping[str, Any]) -> dict[str, str]:
    egress = str(value.get("egress") or "unknown").lower()
    if egress == "deny_by_default":
        return _readiness_check("network", "ready", "attested_egress_deny_by_default")
    if egress == "allowlist":
        return _readiness_check("network", "warning", "attested_egress_restricted")
    if egress == "allow_all":
        return _readiness_check("network", "blocked", "attested_egress_policy_noncompliant")
    return _readiness_check("network", "unknown", "attested_network_policy_unknown")


def _attestation_execution_check(value: Mapping[str, Any]) -> dict[str, str]:
    mode = str(value.get("mode") or "").lower()
    if mode == "dispatcher_only" and value.get("execution_enabled") is False:
        return _readiness_check("execution", "ready", "attested_dispatcher_only_no_local_execution")
    return _readiness_check("execution", "blocked", "attested_execution_policy_noncompliant")


def _runtime_check(name: str, capabilities: Mapping[str, Any] | None, key: str) -> dict[str, str]:
    if capabilities is None or key not in capabilities:
        return _readiness_check(name, "unknown", "capability_not_provided")
    state = _readiness_state(capabilities[key])
    if state == "ready":
        return _readiness_check(name, "ready", "capability_ready")
    if state == "blocked":
        return _readiness_check(name, "blocked", "capability_unavailable")
    return _readiness_check(name, "unknown", "capability_unrecognized")


def _license_check(value: Any, has_preflight_input: bool) -> dict[str, str]:
    if _confirmation_state(value) == "confirmed":
        return _readiness_check("license", "ready", "license_confirmed")
    if value is None and not has_preflight_input:
        return _readiness_check("license", "unknown", "license_confirmation_not_provided")
    return _readiness_check("license", "blocked", "license_confirmation_required")


def _sandbox_check(policy: Mapping[str, Any] | None) -> dict[str, str]:
    sandbox = _optional_mapping(policy.get("sandbox"), "$.dispatcher_policy.sandbox") if policy else None
    if sandbox is None:
        return _readiness_check("sandbox", "unknown", "sandbox_policy_not_provided")
    execution = str(sandbox.get("execution") or "").lower()
    filesystem = str(sandbox.get("filesystem") or "").lower()
    if execution == "dispatcher_managed" and filesystem == "artifact_ref_only":
        return _readiness_check("sandbox", "ready", "dispatcher_managed_artifact_ref_only")
    return _readiness_check("sandbox", "blocked", "sandbox_policy_noncompliant")


def _network_check(policy: Mapping[str, Any] | None) -> dict[str, str]:
    if policy is None:
        return _readiness_check("network", "unknown", "network_policy_not_provided")
    value = str(
        policy.get("network")
        or policy.get("egress")
        or policy.get("network_egress")
        or ""
    ).lower()
    if value == "deny_by_default":
        return _readiness_check("network", "ready", "egress_deny_by_default")
    if value in {"allowlist", "allowlisted", "restricted"}:
        return _readiness_check("network", "warning", "egress_restricted")
    if value in {"allow_all", "unrestricted", "public_internet"}:
        return _readiness_check("network", "blocked", "egress_policy_noncompliant")
    return _readiness_check("network", "unknown", "network_policy_not_provided")


def _readiness_check(name: str, status: str, code: str) -> dict[str, str]:
    return {"name": name, "status": status, "code": code}


def _readiness_state(value: Any) -> str:
    if value is True:
        return "ready"
    if value is False:
        return "blocked"
    if isinstance(value, Mapping):
        return _readiness_state(value.get("status") or value.get("available") or value.get("ready"))
    normalized = str(value).lower()
    if normalized in {"ready", "available", "installed", "ok", "true", "yes"}:
        return "ready"
    if normalized in {"blocked", "unavailable", "missing", "disabled", "false", "no"}:
        return "blocked"
    return "unknown"


def _confirmation_state(value: Any) -> str:
    if value is True:
        return "confirmed"
    if isinstance(value, Mapping):
        confirmed = value.get("confirmed")
        if confirmed is True:
            return "confirmed"
    return "missing"


def _validate_props(props: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    required = schema.get("required", [])
    if isinstance(required, Sequence) and not isinstance(required, (str, bytes, bytearray)):
        missing = [key for key in required if isinstance(key, str) and key not in props]
        if missing:
            raise RemotionTemplateError(
                "remotion.props_missing_required",
                f"Missing required Remotion props: {', '.join(sorted(missing))}.",
            )

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return
    if schema.get("additionalProperties") is False:
        unknown = sorted(str(key) for key in props if key not in properties)
        if unknown:
            raise RemotionTemplateError(
                "remotion.props_unknown",
                f"Unknown Remotion props are not allowed: {', '.join(unknown)}.",
            )

    for key, definition in properties.items():
        if key not in props or not isinstance(definition, Mapping):
            continue
        expected_type = definition.get("type")
        if expected_type is not None and not _matches_json_type(props[key], expected_type):
            raise RemotionTemplateError(
                "remotion.props_type_mismatch",
                f"Remotion prop {key!r} does not match expected type {expected_type!r}.",
            )
        enum = definition.get("enum")
        if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes, bytearray)):
            if props[key] not in enum:
                raise RemotionTemplateError(
                    "remotion.props_enum_mismatch",
                    f"Remotion prop {key!r} is not an allowed enum value.",
                )


def _matches_json_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_type(value, item) for item in expected_type)
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": (isinstance(value, (int, float)) and not isinstance(value, bool)),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "null": value is None,
    }.get(str(expected_type), True)


def _select_composition(compositions: Sequence[Any], composition_id: str) -> Mapping[str, Any]:
    for item in compositions:
        if not isinstance(item, Mapping):
            continue
        candidate = str(item.get("composition_id") or item.get("id") or "")
        if candidate == composition_id:
            return item
    raise RemotionTemplateError(
        "remotion.composition_not_found",
        f"Remotion composition {composition_id!r} was not found in template manifest.",
    )


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RemotionTemplateError("remotion.invalid_payload", f"{path} must be an object.")
    return value


def _optional_mapping(value: Any, path: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, path)


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RemotionTemplateError("remotion.invalid_payload", f"{path} must be an array.")
    if not value:
        raise RemotionTemplateError("remotion.invalid_payload", f"{path} must not be empty.")
    return value


def _safe_id(value: str, path: str) -> str:
    if not _SAFE_ID_PATTERN.fullmatch(value):
        raise RemotionTemplateError(
            "remotion.invalid_identifier",
            f"{path} must be a safe identifier without local paths or shell fragments.",
        )
    return value


def _positive_int(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RemotionTemplateError("remotion.invalid_dimensions", f"{path} must be an integer.")
    if value < minimum or value > maximum:
        raise RemotionTemplateError(
            "remotion.invalid_dimensions",
            f"{path} must be between {minimum} and {maximum}.",
        )
    return value


def _first_present(*mappings: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for mapping in mappings:
        for key in keys:
            if key in mapping:
                return mapping[key]
    return None


def _render_format(input_payload: Mapping[str, Any]) -> str:
    render_settings = input_payload.get("render_settings")
    value = render_settings.get("format") if isinstance(render_settings, Mapping) else input_payload.get("format")
    if value is None:
        return "mp4"
    value_string = str(value).lower()
    if value_string not in {"mp4", "webm", "gif", "png_sequence"}:
        raise RemotionTemplateError(
            "remotion.render_format_unsupported",
            f"Unsupported Remotion render format {value_string!r}.",
        )
    return value_string


def _public_manifest_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "template_id": manifest.get("template_id") or manifest.get("id"),
        "version": manifest.get("version"),
        "compositions": [
            {
                "composition_id": item.get("composition_id") or item.get("id"),
                "duration_frames": item.get("duration_frames")
                or item.get("duration_in_frames")
                or item.get("durationInFrames"),
                "fps": item.get("fps"),
                "width": item.get("width"),
                "height": item.get("height"),
            }
            for item in manifest.get("compositions", [])
            if isinstance(item, Mapping)
        ],
    }


def _public_artifact_ref(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    ref = _mapping(value, "$.template_artifact_ref")
    public_keys = {
        "artifact_id",
        "artifact_type",
        "mime_type",
        "size_bytes",
        "checksum",
        "data_class",
        "retention_policy",
        "expires_at",
        "download_url",
        "access_policy",
    }
    return {str(key): ref[key] for key in public_keys if key in ref}


def _caller_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _assert_caller_safe(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        leaked_keys = {str(key) for key in value}.intersection(_FORBIDDEN_PUBLIC_KEYS)
        if leaked_keys:
            raise RemotionTemplateError(
                "remotion.unsafe_payload",
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
                raise RemotionTemplateError(
                    "remotion.unsafe_payload",
                    f"{path} includes a local path-like value.",
                )
        for pattern in _RAW_COMMAND_PATTERNS:
            if pattern.search(value):
                raise RemotionTemplateError(
                    "remotion.unsafe_payload",
                    f"{path} includes a raw command-like value.",
                )


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _usage_metrics(
    capability: str,
    artifact_refs: tuple[ArtifactRef, ...] = (),
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "operation": capability.rsplit(".", maxsplit=1)[-1],
        "node_invocations": 0,
        "chromium_invocations": 0,
    }
    if artifact_refs:
        metrics["artifact_count"] = len(artifact_refs)
        metrics["output_bytes"] = sum(ref.size_bytes for ref in artifact_refs)
    return metrics
