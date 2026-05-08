"""Platform Core handoff contracts for future toolkit integration.

This module is intentionally local and dependency-free. It fixes the shape that
Platform Core can later call into without making this P0 toolkit depend on a
real Platform Core service.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen as default_urlopen


TOOLKIT_ID = "video-editing-toolkit"
SCHEMA = "video_editing_toolkit.platform_core.handoff.v0"
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "manifests"
    / "video-editing-toolkit.p0.manifest.json"
)
DEFAULT_PLATFORM_CORE_BASE_URL = "http://127.0.0.1:8010"

PUBLIC_ARTIFACT_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_type",
        "owner_tenant_id",
        "created_by_run_id",
        "mime_type",
        "size_bytes",
        "checksum",
        "data_class",
        "retention_policy",
        "expires_at",
        "access_policy",
        "download_url",
    }
)

FORBIDDEN_PUBLIC_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "cmd",
    "command",
    "env",
    "environment",
    "file_path",
    "filesystem_path",
    "internal_path",
    "local_path",
    "password",
    "private_key",
    "raw_command",
    "raw_shell",
    "secret",
    "stderr",
    "stdout",
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


class PlatformCoreClientError(RuntimeError):
    """Raised when Platform Core returns an error or an invalid response."""


class PlatformCoreHTTPError(PlatformCoreClientError):
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body
        detail = body.decode("utf-8", errors="replace")[:500]
        super().__init__(f"Platform Core HTTP {status_code}: {detail}")


@dataclass(frozen=True)
class PlatformCoreClient:
    """Small stdlib-only client for Platform Core live artifact byte smokes."""

    base_url: str = DEFAULT_PLATFORM_CORE_BASE_URL
    token: str | None = None
    timeout_seconds: float = 30.0
    urlopen: Any = default_urlopen

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        tenant_name: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/auth/register",
            json_body={
                "email": email,
                "password": password,
                "display_name": display_name,
                "tenant_name": tenant_name,
            },
        )

    def create_service_account(
        self,
        *,
        tenant_id: str,
        app_id: str = "agentctl",
        name: str = "video toolkit worker",
        scopes: Sequence[str] = ("toolkit.artifacts.read", "toolkit.artifacts.write", "agentctl.run"),
        token: str | None = None,
        expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "app_id": app_id,
            "name": name,
            "scopes": list(scopes),
        }
        if expires_in_days is not None:
            body["expires_in_days"] = expires_in_days
        return self._request_json(
            "POST",
            f"/tenants/{quote(tenant_id, safe='')}/service-accounts",
            json_body=body,
            token=token,
        )

    def create_toolkit_artifact(
        self,
        *,
        content: bytes,
        toolkit_id: str = TOOLKIT_ID,
        capability: str | None = None,
        artifact_type: str = "source_video",
        file_name: str | None = None,
        mime_type: str = "application/octet-stream",
        data_class: str = "D3",
        retention_policy: str = "short_lived",
        access_policy: Mapping[str, Any] | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        expires_at: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/toolkit-artifacts",
            json_body=build_toolkit_artifact_create_payload(
                content=content,
                toolkit_id=toolkit_id,
                capability=capability,
                artifact_type=artifact_type,
                file_name=file_name,
                mime_type=mime_type,
                data_class=data_class,
                retention_policy=retention_policy,
                access_policy=access_policy,
                run_id=run_id,
                trace_id=trace_id,
                tenant_id=tenant_id,
                metadata=metadata,
                expires_at=expires_at,
            ),
            token=token,
        )

    def download_artifact_bytes(
        self,
        artifact_id_or_download_url: str,
        *,
        token: str | None = None,
    ) -> bytes:
        path = artifact_id_or_download_url
        if not path.startswith(("http://", "https://", "/")):
            path = f"/toolkit-artifacts/{quote(path, safe='')}/bytes"
        return self._request_bytes("GET", path, token=token)

    def _request_json(
        self,
        method: str,
        path_or_url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        body = self._request_bytes(method, path_or_url, json_body=json_body, token=token)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise PlatformCoreClientError("Platform Core JSON response must be an object.")
        return payload

    def _request_bytes(
        self,
        method: str,
        path_or_url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        token: str | None = None,
    ) -> bytes:
        headers = {"Accept": "application/json", "User-Agent": "video-editing-toolkit-platform-core-smoke"}
        data = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        auth_token = token if token is not None else self.token
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        request = Request(
            _join_platform_core_url(self.base_url, path_or_url),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            raise PlatformCoreHTTPError(exc.code, exc.read()) from exc
        except URLError as exc:
            raise PlatformCoreClientError(f"Platform Core request failed: {exc.reason}") from exc


def build_toolkit_artifact_create_payload(
    *,
    content: bytes,
    toolkit_id: str = TOOLKIT_ID,
    capability: str | None = None,
    artifact_type: str = "source_video",
    file_name: str | None = None,
    mime_type: str = "application/octet-stream",
    data_class: str = "D3",
    retention_policy: str = "short_lived",
    access_policy: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "toolkit_id": toolkit_id,
        "artifact_type": artifact_type,
        "mime_type": mime_type,
        "data_class": data_class,
        "retention_policy": retention_policy,
        "access_policy": dict(access_policy or {}),
        "metadata": dict(metadata or {}),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    for key, value in {
        "tenant_id": tenant_id,
        "capability": capability,
        "file_name": file_name,
        "run_id": run_id,
        "trace_id": trace_id,
        "expires_at": expires_at,
    }.items():
        if value is not None:
            payload[key] = value
    return payload


def verify_artifact_bytes(
    downloaded: bytes,
    *,
    expected_size_bytes: int | None = None,
    expected_checksum: str | None = None,
) -> dict[str, Any]:
    digest = hashlib.sha256(downloaded).hexdigest()
    if expected_size_bytes is not None and len(downloaded) != expected_size_bytes:
        raise ValueError(f"Downloaded artifact size mismatch: got {len(downloaded)}, expected {expected_size_bytes}.")
    normalized_checksum = _normalize_sha256(expected_checksum)
    if normalized_checksum is not None and digest != normalized_checksum:
        raise ValueError(f"Downloaded artifact checksum mismatch: got sha256:{digest}.")
    return {"size_bytes": len(downloaded), "sha256": digest}


def build_platform_core_toolkit_descriptor(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Build the Platform Core-facing toolkit descriptor from the P0 manifest."""

    manifest = _load_manifest(manifest_path)
    capabilities = [
        item
        for item in manifest.get("capabilities", [])
        if isinstance(item, Mapping)
        and item.get("status") == "enabled"
        and isinstance(item.get("capability"), str)
    ]
    descriptor = {
        "schema": SCHEMA,
        "contract": "platform_core_toolkit_descriptor.v0",
        "toolkit_id": manifest.get("toolkit_id", TOOLKIT_ID),
        "display_name": manifest.get("display_name"),
        "version": manifest.get("version"),
        "status": manifest.get("status"),
        "category": manifest.get("category"),
        "capabilities": [
            {
                "capability": item["capability"],
                "version": item.get("version"),
                "status": item.get("status"),
                "data_sensitivity": item.get("data_sensitivity"),
                "approval_policy": item.get("approval_policy"),
                "artifact_policy": item.get("artifact_policy"),
                "input_schema": item.get("input_schema"),
                "output_schema": item.get("output_schema"),
            }
            for item in capabilities
        ],
        "runtime_adapter": manifest.get("runtime_adapter", {}),
        "required_permissions": list(manifest.get("required_permissions", [])),
        "required_scopes": list(manifest.get("required_scopes", [])),
        "quota_metrics": list(manifest.get("quota_metrics", [])),
        "pricing_metrics": list(manifest.get("pricing_metrics", [])),
        "artifact_policy": manifest.get("artifact_policy", {}),
        "sandbox_policy": manifest.get("sandbox_policy", {}),
        "approval_policy": manifest.get("approval_policy", {}),
        "handoff": {
            "request_contract": "platform_core_toolkit_run_request.v0",
            "completion_contract": "platform_core_toolkit_run_completion.v0",
            "artifact_contract": "artifact_ref_only",
            "trace_contract": "trace_id_to_trace_ref",
            "execution_model": "external_video_toolkit_worker",
            "adapter_entrypoints": [
                "prepare(input, context)",
                "run(validated_input, context)",
                "cancel(run_id)",
                "status(run_id)",
                "cleanup(run_id, retention_policy)",
            ],
            "local_dev_surfaces": {
                "agentctl_cli": "video-toolkit-agentctl",
                "worker_cli": "video-toolkit-agentctl-worker",
                "local_api": "video-toolkit-local-api",
            },
        },
    }
    return _caller_safe(descriptor)


def platform_core_envelope_to_agentctl(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a future Platform Core run request into the local agentctl shape."""

    toolkit_id = _required_string(payload, "toolkit_id")
    if toolkit_id != TOOLKIT_ID:
        raise ValueError("toolkit_id is not supported by this toolkit.")
    capability = _required_string(payload, "capability")
    input_payload = payload.get("input", {})
    if not isinstance(input_payload, Mapping):
        raise ValueError("input must be a JSON object.")

    run_id = (
        _optional_string(payload.get("run_id"))
        or _optional_string(payload.get("platform_run_id"))
        or _optional_string(payload.get("runtime_job_id"))
    )
    tool_call_id = (
        _optional_string(payload.get("tool_call_id"))
        or _optional_string(payload.get("platform_tool_call_id"))
        or _optional_string(payload.get("lease_id"))
    )
    trace_ref = (
        _optional_string(payload.get("trace_ref"))
        or _optional_string(payload.get("trace_id"))
        or _optional_string(payload.get("platform_trace_id"))
    )
    policy_context = _platform_policy_context(payload)
    envelope: dict[str, Any] = {
        "toolkit_id": toolkit_id,
        "capability": capability,
        "version": _optional_string(payload.get("version")) or "0.1.0",
        "input": dict(input_payload),
        "artifact_refs": _public_artifact_refs(payload.get("artifact_refs")),
        "policy_context": policy_context,
    }
    if run_id:
        envelope["run_id"] = run_id
    if tool_call_id:
        envelope["tool_call_id"] = tool_call_id
    if trace_ref:
        envelope["trace_ref"] = trace_ref
    approval_context = payload.get("approval_context")
    if isinstance(approval_context, Mapping):
        envelope["approval_context"] = _caller_safe(dict(approval_context))
    return _caller_safe(envelope)


def build_platform_core_completion(
    local_result: Mapping[str, Any],
    *,
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize local agentctl/worker output into a Platform Core completion."""

    processed = local_result.get("processed")
    if not isinstance(processed, Mapping):
        processed = local_result.get("result") if isinstance(local_result.get("result"), Mapping) else {}
    request = request or {}
    toolkit_id = (
        _optional_string(local_result.get("toolkit_id"))
        or _optional_string(request.get("toolkit_id"))
        or TOOLKIT_ID
    )
    capability = _optional_string(local_result.get("capability")) or _optional_string(request.get("capability"))
    status = _completion_status(local_result, processed)
    completion = {
        "schema": SCHEMA,
        "contract": "platform_core_toolkit_run_completion.v0",
        "toolkit_id": toolkit_id,
        "capability": capability,
        "run_id": _optional_string(processed.get("run_id"))
        or _optional_string(local_result.get("run_id"))
        or _optional_string(request.get("run_id"))
        or _optional_string(request.get("platform_run_id")),
        "tool_call_id": _optional_string(processed.get("tool_call_id"))
        or _optional_string(local_result.get("tool_call_id"))
        or _optional_string(request.get("tool_call_id"))
        or _optional_string(request.get("platform_tool_call_id")),
        "status": status,
        "output": processed.get("output") if isinstance(processed.get("output"), Mapping) else {},
        "artifact_refs": _public_artifact_refs(processed.get("artifact_refs")),
        "usage_metrics": _mapping_or_empty(processed.get("usage_metrics")),
        "trace_ref": _optional_string(processed.get("trace_ref"))
        or _optional_string(local_result.get("trace_ref"))
        or _optional_string(request.get("trace_ref"))
        or _optional_string(request.get("trace_id")),
        "error_code": _optional_string(processed.get("error_code"))
        or _optional_string(local_result.get("error_code")),
        "error_message": _optional_string(processed.get("error_message"))
        or _optional_string(local_result.get("error_message")),
        "artifact_contract": "artifact_ref_only",
    }
    return _caller_safe(completion)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build local Platform Core handoff payloads for the video editing toolkit.",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--descriptor", action="store_true", help="Print the Platform Core toolkit descriptor.")
    parser.add_argument("--input-json", help="Platform Core run request to normalize. Defaults to stdin.")
    parser.add_argument("--completion-json", help="Local result JSON to normalize as a Platform Core completion.")
    parser.add_argument("--base-url", default=DEFAULT_PLATFORM_CORE_BASE_URL, help="Platform Core base URL.")
    parser.add_argument("--token-env", default="PLATFORM_CORE_TOKEN", help="Environment variable containing a bearer token.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    subparsers = parser.add_subparsers(dest="command")

    register_parser = subparsers.add_parser("register", help="Register a smoke tenant.")
    register_parser.add_argument("--email", required=True)
    register_parser.add_argument("--password-env", default="PLATFORM_CORE_REGISTER_PASSWORD")
    register_parser.add_argument("--display-name", required=True)
    register_parser.add_argument("--tenant-name", required=True)

    service_parser = subparsers.add_parser("create-service-account", help="Create a Platform Core service account.")
    service_parser.add_argument("--tenant-id", required=True)
    service_parser.add_argument("--owner-token-env", default="PLATFORM_CORE_OWNER_TOKEN")
    service_parser.add_argument("--app-id", default="agentctl")
    service_parser.add_argument("--name", default="video toolkit worker")
    service_parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        default=[],
        help="Service account scope. May be passed more than once.",
    )
    service_parser.add_argument("--expires-in-days", type=int)

    artifact_parser = subparsers.add_parser("create-artifact", help="Upload inline bytes as a toolkit artifact.")
    artifact_parser.add_argument("--service-token-env", default="PLATFORM_CORE_SERVICE_TOKEN")
    artifact_parser.add_argument("--file", required=True, help="Local byte source to upload.")
    artifact_parser.add_argument("--toolkit-id", default=TOOLKIT_ID)
    artifact_parser.add_argument("--capability")
    artifact_parser.add_argument("--artifact-type", default="source_video")
    artifact_parser.add_argument("--file-name")
    artifact_parser.add_argument("--mime-type", default="application/octet-stream")
    artifact_parser.add_argument("--data-class", default="D3")
    artifact_parser.add_argument("--retention-policy", default="short_lived")
    artifact_parser.add_argument("--run-id")
    artifact_parser.add_argument("--trace-id")

    download_parser = subparsers.add_parser("download-artifact-bytes", help="Download artifact bytes and print checksum metadata.")
    download_parser.add_argument("--service-token-env", default="PLATFORM_CORE_SERVICE_TOKEN")
    download_parser.add_argument("--artifact", required=True, help="Artifact id or download URL.")
    download_parser.add_argument("--expect-size-bytes", type=int)
    download_parser.add_argument("--expect-sha256")
    args = parser.parse_args(argv)

    if args.command:
        payload = _run_platform_core_client_command(args)
    elif args.descriptor:
        payload = build_platform_core_toolkit_descriptor(args.manifest)
    elif args.completion_json:
        payload = build_platform_core_completion(_load_json_text(args.completion_json))
    else:
        raw = args.input_json if args.input_json is not None else sys.stdin.read()
        payload = platform_core_envelope_to_agentctl(_load_json_text(raw))
    print(json.dumps(_caller_safe(payload), ensure_ascii=False, sort_keys=True))
    return 0


def _run_platform_core_client_command(args: argparse.Namespace) -> dict[str, Any]:
    client = PlatformCoreClient(
        base_url=args.base_url,
        token=_env_value(args.token_env),
        timeout_seconds=args.timeout,
    )
    if args.command == "register":
        return client.register(
            email=args.email,
            password=_required_env_value(args.password_env),
            display_name=args.display_name,
            tenant_name=args.tenant_name,
        )
    if args.command == "create-service-account":
        scopes = args.scopes or ["toolkit.artifacts.read", "toolkit.artifacts.write", "agentctl.run"]
        return client.create_service_account(
            tenant_id=args.tenant_id,
            app_id=args.app_id,
            name=args.name,
            scopes=scopes,
            token=_required_env_value(args.owner_token_env),
            expires_in_days=args.expires_in_days,
        )
    if args.command == "create-artifact":
        content = Path(args.file).read_bytes()
        created = client.create_toolkit_artifact(
            content=content,
            toolkit_id=args.toolkit_id,
            capability=args.capability,
            artifact_type=args.artifact_type,
            file_name=args.file_name or Path(args.file).name,
            mime_type=args.mime_type,
            data_class=args.data_class,
            retention_policy=args.retention_policy,
            run_id=args.run_id,
            trace_id=args.trace_id,
            token=_required_env_value(args.service_token_env),
        )
        ref = created.get("artifact_ref")
        if isinstance(ref, Mapping):
            check = verify_artifact_bytes(
                content,
                expected_size_bytes=ref.get("size_bytes") if isinstance(ref.get("size_bytes"), int) else None,
                expected_checksum=_optional_string(ref.get("checksum")),
            )
            created["local_upload_check"] = check
        return _caller_safe(created)
    if args.command == "download-artifact-bytes":
        downloaded = client.download_artifact_bytes(
            args.artifact,
            token=_required_env_value(args.service_token_env),
        )
        return verify_artifact_bytes(
            downloaded,
            expected_size_bytes=args.expect_size_bytes,
            expected_checksum=args.expect_sha256,
        )
    raise ValueError(f"Unsupported command: {args.command}")


def _completion_status(local_result: Mapping[str, Any], processed: Mapping[str, Any]) -> str:
    status = processed.get("status") or local_result.get("status")
    if status == "succeeded" or status == "completed":
        return "succeeded"
    if status == "cancelled":
        return "cancelled"
    return "failed"


def _platform_policy_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("policy_context")
    if not isinstance(raw, Mapping):
        raw = {}
    data_policy = _mapping_or_empty(raw.get("data_policy")) or _mapping_or_empty(payload.get("data_policy"))
    quota_policy = _mapping_or_empty(raw.get("quota_policy")) or _mapping_or_empty(payload.get("quota_policy"))
    return _caller_safe(
        {
            "tenant_id": _string_choice(raw.get("tenant_id"), payload.get("tenant_id"), "demo_tenant"),
            "user_id": _string_choice(raw.get("user_id"), payload.get("user_id"), "platform_core"),
            "share_id": _optional_string(raw.get("share_id")) or _optional_string(payload.get("share_id")),
            "data_policy": data_policy,
            "quota_policy": quota_policy,
        }
    )


def _public_artifact_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        artifact_id = item.get("artifact_id") or item.get("ref")
        if not isinstance(artifact_id, str) or not artifact_id:
            continue
        if artifact_id in seen:
            continue
        ref = {
            key: item[key]
            for key in PUBLIC_ARTIFACT_KEYS
            if key in item and item[key] is not None
        }
        ref["artifact_id"] = artifact_id
        ref.setdefault("artifact_type", item.get("kind") or "artifact")
        ref.setdefault("owner_tenant_id", item.get("owner_tenant_id") or "demo_tenant")
        ref.setdefault("access_policy", _mapping_or_empty(item.get("access_policy")))
        refs.append(_caller_safe(ref))
        seen.add(artifact_id)
    return refs


def _load_manifest(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Toolkit manifest must be a JSON object.")
    return payload


def _load_json_text(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object.")
    return payload


def _join_platform_core_url(base_url: str, path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    return urljoin(base_url.rstrip("/") + "/", path_or_url.lstrip("/"))


def _normalize_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized.startswith("sha256:"):
        normalized = normalized.split(":", 1)[1]
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("Expected checksum must be a sha256 hex digest.")
    return normalized


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _required_env_value(name: str) -> str:
    value = _env_value(name)
    if value is None:
        raise ValueError(f"Environment variable {name} is required.")
    return value


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required and must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_choice(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _caller_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            key_string = str(key)
            normalized = key_string.lower()
            if normalized in FORBIDDEN_PUBLIC_KEYS:
                continue
            if any(part in normalized for part in ("token", "secret", "password", "api_key", "private_key")):
                safe[key_string] = "[redacted]"
            else:
                safe[key_string] = _caller_safe(child)
        return safe
    if isinstance(value, list):
        return [_caller_safe(child) for child in value]
    if isinstance(value, tuple):
        return [_caller_safe(child) for child in value]
    if isinstance(value, str):
        return "[redacted]" if any(pattern.search(value) for pattern in LOCAL_PATH_PATTERNS) else value
    return value


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
