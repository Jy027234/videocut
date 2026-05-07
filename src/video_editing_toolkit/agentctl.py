"""Local agentctl-compatible command bridge for P0.6."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from video_editing_toolkit.runtime import (
    LocalRunService,
    PolicyContext,
    RunRequest,
    register_p0_adapter_handlers,
)
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore


TOOLKIT_ID = "video-editing-toolkit"
SCHEMA = "video_editing_toolkit.agentctl.local_run.v0"
DEFAULT_ARTIFACT_ROOT = Path(".video-toolkit-data") / "agentctl-artifacts"
NO_UPLOAD_CAPABILITIES = frozenset(
    {
        "video.project_edit.create_project",
        "video.delivery.generate_variants",
    }
)
ARTIFACT_INPUT_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_ids",
        "artifact_ref",
        "artifact_refs",
    }
)

FORBIDDEN_PUBLIC_KEYS = {
    "api_key",
    "auth_token",
    "client_secret",
    "file_path",
    "filesystem_path",
    "ffmpeg_command",
    "internal_path",
    "internal_worker_url",
    "local_path",
    "password",
    "private_key",
    "raw_command",
    "raw_shell",
    "secret",
    "storage_uri",
    "token",
    "worker_path",
    "worker_url",
}

LOCAL_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)[^\s\"']+"),
    re.compile(r"\\\\[^\\/\s\"']+[\\/][^\s\"']+"),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"local-artifact://", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])/(Users|home|var|tmp|private|mnt)/[^\s\"']+"),
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a local video-editing-toolkit capability with an agentctl-like JSON envelope.",
    )
    parser.add_argument(
        "--input-json",
        help="JSON request object. When omitted, JSON is read from stdin.",
    )
    parser.add_argument(
        "--artifact-root",
        help="Optional local artifact store root. Never returned in public JSON.",
    )
    args = parser.parse_args(argv)

    raw_input = args.input_json if args.input_json is not None else sys.stdin.read()
    response, exit_code = run_agentctl_json(
        raw_input,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    return exit_code


def run_agentctl_json(
    raw_input: str,
    *,
    artifact_root: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        return _error_response(
            "agentctl.invalid_json",
            f"Input must be a JSON object: {exc.msg}.",
        ), 2

    if not isinstance(payload, Mapping):
        return _error_response(
            "agentctl.invalid_request",
            "Input must be a JSON object.",
        ), 2

    try:
        response = run_agentctl(payload, artifact_root=artifact_root)
    except ValueError as exc:
        return _error_response("agentctl.invalid_request", str(exc)), 2
    return response, 0


def run_agentctl(
    payload: Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
) -> dict[str, Any]:
    toolkit_id = _required_string(payload, "toolkit_id")
    capability = _required_string(payload, "capability")
    input_payload = payload.get("input", {})
    if not isinstance(input_payload, Mapping):
        raise ValueError("input must be a JSON object when provided.")

    policy_context = _policy_context(payload)
    run_id = _optional_string(payload.get("run_id"))
    tool_call_id = _optional_string(payload.get("tool_call_id"))
    trace_ref = _optional_string(payload.get("trace_ref")) or _optional_string(payload.get("trace_id"))
    version = _optional_string(payload.get("version")) or "0.1.0"
    dry_run = bool(payload.get("dry_run", False))
    artifact_refs = _artifact_refs(payload, policy_context=policy_context)
    if _should_hold_agentctl_artifact_refs(
        capability,
        input_payload,
        artifact_refs,
    ):
        artifact_refs = []

    request_kwargs: dict[str, Any] = {}
    if run_id is not None:
        request_kwargs["run_id"] = run_id
    if tool_call_id is not None:
        request_kwargs["tool_call_id"] = tool_call_id

    request = RunRequest(
        toolkit_id=toolkit_id,
        capability=capability,
        input=dict(input_payload),
        version=version,
        artifact_refs=artifact_refs,
        policy_context=policy_context,
        dry_run=dry_run,
        trace_ref=trace_ref,
        **request_kwargs,
    )

    selected_root = _artifact_root(payload, artifact_root)
    service = LocalRunService(
        artifact_store=LocalArtifactStore(selected_root)
    )
    register_p0_adapter_handlers(service)

    queued = service.submit_public(request)
    processed = service.process_next_public()
    response = {
        "schema": SCHEMA,
        "transport": "agentctl.local",
        "toolkit_id": toolkit_id,
        "capability": capability,
        "ok": bool(processed and processed.get("status") == "succeeded"),
        "queued": queued,
        "processed": processed,
    }
    return _caller_safe(response)


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required and must be a non-empty string.")
    return value


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _policy_context(payload: Mapping[str, Any]) -> PolicyContext:
    raw_context = payload.get("policy_context", {})
    if not isinstance(raw_context, Mapping):
        raw_context = {}
    return PolicyContext(
        tenant_id=_context_string(raw_context, "tenant_id", payload.get("tenant_id"), "demo_tenant"),
        user_id=_context_string(raw_context, "user_id", payload.get("user_id"), "demo_user"),
        share_id=_optional_string(raw_context.get("share_id")),
        data_policy=_context_mapping(raw_context.get("data_policy")),
        quota_policy=_context_mapping(raw_context.get("quota_policy")),
    )


def _context_string(
    raw_context: Mapping[str, Any],
    key: str,
    fallback_value: Any,
    default: str,
) -> str:
    value = raw_context.get(key)
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(fallback_value, str) and fallback_value.strip():
        return fallback_value
    return default


def _context_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _artifact_refs(
    payload: Mapping[str, Any],
    *,
    policy_context: PolicyContext,
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for value in _artifact_ref_inputs(payload):
        ref = _coerce_artifact_ref(value, policy_context=policy_context)
        if ref is not None and ref.artifact_id not in {item.artifact_id for item in refs}:
            refs.append(ref)
    return refs


def _should_hold_agentctl_artifact_refs(
    capability: str,
    input_payload: Mapping[str, Any],
    artifact_refs: list[ArtifactRef],
) -> bool:
    return bool(
        artifact_refs
        and capability in NO_UPLOAD_CAPABILITIES
        and not _input_has_artifact_reference(input_payload)
    )


def _input_has_artifact_reference(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(str(key) in ARTIFACT_INPUT_KEYS for key in value):
            return True
        return any(_input_has_artifact_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_input_has_artifact_reference(child) for child in value)
    return False


def _artifact_ref_inputs(payload: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("artifact_refs", "artifact_ids"):
        raw_value = payload.get(key)
        if isinstance(raw_value, list):
            values.extend(raw_value)
    raw_ref = payload.get("artifact_ref")
    if raw_ref is not None:
        values.append(raw_ref)
    raw_id = payload.get("artifact_id")
    if isinstance(raw_id, str):
        values.append(raw_id)
    return values


def _coerce_artifact_ref(
    value: Any,
    *,
    policy_context: PolicyContext,
) -> ArtifactRef | None:
    if isinstance(value, str):
        artifact_id = value.strip()
        raw: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        artifact_id = str(value.get("artifact_id") or value.get("ref") or "").strip()
        raw = value
    else:
        return None

    if not artifact_id:
        return None

    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type=_string_field(raw, "artifact_type", _string_field(raw, "kind", "artifact")),
        owner_tenant_id=_string_field(raw, "owner_tenant_id", policy_context.tenant_id),
        created_by_run_id=_string_field(raw, "created_by_run_id", "agentctl_input"),
        storage_uri=f"local-artifact://{artifact_id}/agentctl-input",
        mime_type=_string_field(raw, "mime_type", _string_field(raw, "media_type", "application/octet-stream")),
        size_bytes=_int_field(raw.get("size_bytes"), 0),
        checksum=_string_field(raw, "checksum", "sha256:unknown"),
        data_class=_string_field(raw, "data_class", "sensitive"),
        retention_policy=_string_field(raw, "retention_policy", "short_lived"),
        expires_at=_datetime_field(raw.get("expires_at")),
        access_policy=_context_mapping(raw.get("access_policy")),
        download_url=_safe_download_url(raw.get("download_url")),
    )


def _string_field(payload: Mapping[str, Any], key: str, default: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _int_field(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _datetime_field(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_download_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/local/artifacts/"):
        return None
    return value


def _artifact_root(
    payload: Mapping[str, Any],
    cli_artifact_root: str | Path | None,
) -> Path:
    if cli_artifact_root is not None:
        return Path(cli_artifact_root)
    raw_payload_root = payload.get("artifact_store_root")
    if isinstance(raw_payload_root, str) and raw_payload_root.strip():
        return Path(raw_payload_root)
    raw_env_root = os.environ.get("VIDEO_TOOLKIT_ARTIFACT_ROOT")
    if raw_env_root:
        return Path(raw_env_root)
    return DEFAULT_ARTIFACT_ROOT


def _error_response(error_code: str, error_message: str) -> dict[str, Any]:
    return _caller_safe(
        {
            "schema": SCHEMA,
            "transport": "agentctl.local",
            "ok": False,
            "queued": None,
            "processed": None,
            "error_code": error_code,
            "error_message": error_message,
        }
    )


def _caller_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            key_string = str(key)
            if key_string in FORBIDDEN_PUBLIC_KEYS:
                continue
            if _is_sensitive_key(key_string):
                safe[key_string] = "[redacted]"
            else:
                safe[key_string] = _caller_safe(child)
        return safe
    if isinstance(value, list):
        return [_caller_safe(child) for child in value]
    if isinstance(value, tuple):
        return [_caller_safe(child) for child in value]
    if isinstance(value, str):
        return "[redacted]" if _looks_like_local_path(value) else value
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in ("private_key", "api_key", "secret", "token", "password"))


def _looks_like_local_path(value: str) -> bool:
    return any(pattern.search(value) for pattern in LOCAL_PATH_PATTERNS)


if __name__ == "__main__":
    raise SystemExit(main())
