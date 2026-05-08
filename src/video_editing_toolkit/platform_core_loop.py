"""Explicit opt-in Platform Core local loop runner.

The default path remains a no-mutation rehearsal package. Network-like calls
only happen when the caller passes ``execute=True`` or the CLI receives
``--execute-local-loop``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from video_editing_toolkit.agentctl_remote import (
    DEFAULT_BASE_URL as DEFAULT_AGENTCTL_BASE_URL,
    AgentctlRemoteClient,
    AgentctlRemoteConfig,
)
from video_editing_toolkit.agentctl_worker import (
    VideoToolkitAgentctlWorker,
    VideoToolkitWorkerConfig,
    runtime_job_id_from_enqueue,
)
from video_editing_toolkit.platform_core import (
    DEFAULT_P1_MANIFEST_PATH,
    SCHEMA as PLATFORM_CORE_SCHEMA,
    TOOLKIT_ID,
    build_platform_core_completion,
    build_platform_core_learning_audit_event,
    build_platform_core_local_loop_rehearsal_package,
    build_platform_core_manifest_registration_dry_run,
)


CONTRACT = "platform_core_local_loop_runner.v0"
NO_MUTATION_CONTRACT = "platform_core_local_loop_runner_preview.v0"
DEFAULT_WORKER_ID = "video-toolkit-platform-core-loop"

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

SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "password",
        "sat",
        "secret",
        "signature",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
    }
)


@dataclass(frozen=True)
class PlatformCoreLocalLoopConfig:
    """Configuration for the explicit local loop runner."""

    tenant_id: str = "platform_review"
    capability: str = "video.project_edit.create_project"
    input_payload: Mapping[str, Any] | None = None
    artifact_refs: Sequence[Mapping[str, Any]] = ()
    manifest_path: str | Path = DEFAULT_P1_MANIFEST_PATH
    base_url: str = DEFAULT_AGENTCTL_BASE_URL
    artifact_base_url: str | None = None
    token: str | None = None
    artifact_token: str | None = None
    worker_id: str = DEFAULT_WORKER_ID
    backend_id: str = "local"
    timeout_seconds: float = 10.0
    artifact_root: str | Path = Path(".video-toolkit-data") / "platform-core-loop-artifacts"
    execution_mode: str = "in_process"
    max_run_timeout_seconds: int = 120
    max_job_input_bytes: int = 512 * 1024 * 1024

    @classmethod
    def from_env(
        cls,
        *,
        tenant_id: str = "platform_review",
        capability: str = "video.project_edit.create_project",
        input_payload: Mapping[str, Any] | None = None,
        artifact_refs: Sequence[Mapping[str, Any]] = (),
        manifest_path: str | Path = DEFAULT_P1_MANIFEST_PATH,
        base_url: str | None = None,
        artifact_base_url: str | None = None,
        token: str | None = None,
        artifact_token: str | None = None,
        artifact_root: str | Path | None = None,
        execution_mode: str | None = None,
    ) -> "PlatformCoreLocalLoopConfig":
        return cls(
            tenant_id=tenant_id,
            capability=capability,
            input_payload=input_payload,
            artifact_refs=artifact_refs,
            manifest_path=manifest_path,
            base_url=base_url
            or os.environ.get("VIDEO_TOOLKIT_AGENTCTL_BASE_URL")
            or DEFAULT_AGENTCTL_BASE_URL,
            artifact_base_url=artifact_base_url
            or os.environ.get("VIDEO_TOOLKIT_ARTIFACT_BASE_URL")
            or os.environ.get("VIDEO_TOOLKIT_PLATFORM_CORE_BASE_URL"),
            token=token if token is not None else os.environ.get("VIDEO_TOOLKIT_AGENTCTL_TOKEN"),
            artifact_token=artifact_token
            if artifact_token is not None
            else os.environ.get("VIDEO_TOOLKIT_ARTIFACT_TOKEN"),
            artifact_root=artifact_root
            or os.environ.get("VIDEO_TOOLKIT_ARTIFACT_ROOT")
            or Path(".video-toolkit-data") / "platform-core-loop-artifacts",
            execution_mode=execution_mode
            or os.environ.get("VIDEO_TOOLKIT_EXECUTION_MODE")
            or "in_process",
        )


def build_platform_core_local_loop_preview(
    config: PlatformCoreLocalLoopConfig | None = None,
) -> dict[str, Any]:
    """Return the P1.7 local loop package without enqueueing or executing."""

    selected = config or PlatformCoreLocalLoopConfig()
    package = build_platform_core_local_loop_rehearsal_package(
        selected.manifest_path,
        tenant_id=selected.tenant_id,
        capability=selected.capability,
        input_payload=selected.input_payload,
        artifact_refs=selected.artifact_refs,
    )
    return _caller_safe(
        {
            "schema": PLATFORM_CORE_SCHEMA,
            "contract": NO_MUTATION_CONTRACT,
            "toolkit_id": TOOLKIT_ID,
            "status": "preview_only",
            "dry_run": True,
            "network_mutation": False,
            "execution_performed": False,
            "explicit_opt_in_required": True,
            "local_loop_package": package,
        },
        tokens=(selected.token, selected.artifact_token),
    )


def run_platform_core_local_loop(
    config: PlatformCoreLocalLoopConfig | None = None,
    *,
    execute: bool = False,
    client: Any | None = None,
    artifact_fetcher: Any | None = None,
    local_runner: Any | None = None,
) -> dict[str, Any]:
    """Run the local loop only when explicitly opted in.

    With ``execute=False`` this is equivalent to a no-mutation preview. With
    ``execute=True`` the caller must intentionally provide or accept a client,
    then the function enqueues a RunSpec, runs exactly the expected leased job,
    and normalizes the worker result into Platform Core completion/audit shapes.
    """

    selected = config or PlatformCoreLocalLoopConfig()
    preview = build_platform_core_local_loop_preview(selected)
    if not execute:
        return preview

    remote = client or AgentctlRemoteClient(
        AgentctlRemoteConfig(
            base_url=selected.base_url,
            token=selected.token,
            timeout_seconds=selected.timeout_seconds,
        )
    )
    package = preview["local_loop_package"]
    runspec_payload = dict(package["runspec_enqueue_preview"])
    enqueue_result = remote.post("/runspecs/run", runspec_payload)
    expected_job_id = runtime_job_id_from_enqueue(enqueue_result)

    worker = VideoToolkitAgentctlWorker(
        _worker_config(selected),
        client=remote,
        artifact_fetcher=artifact_fetcher,
        local_runner=local_runner,
    )
    worker_result = worker.run_once(expected_job_id=expected_job_id)
    completion_source = _completion_source_from_worker_result(worker_result, remote)
    completion = build_platform_core_completion(
        completion_source,
        request=package["platform_core_request"],
    )
    audit_event = build_platform_core_learning_audit_event(
        {
            "request": package["platform_core_request"],
            "completion": completion,
        }
    )
    return _caller_safe(
        {
            "schema": PLATFORM_CORE_SCHEMA,
            "contract": CONTRACT,
            "toolkit_id": TOOLKIT_ID,
            "status": "completed" if worker_result.get("ok") is True else "failed",
            "dry_run": False,
            "network_mutation": True,
            "execution_performed": True,
            "explicit_opt_in": True,
            "manifest_registration_dry_run": build_platform_core_manifest_registration_dry_run(
                selected.manifest_path,
                tenant_id=selected.tenant_id,
            ),
            "runspec_enqueue": {
                "payload": runspec_payload,
                "result": enqueue_result,
                "runtime_job_id": expected_job_id,
            },
            "worker_run": worker_result,
            "platform_core_completion": completion,
            "audit_event": audit_event,
        },
        tokens=(selected.token, selected.artifact_token),
    )


def run_platform_core_local_loop_live(
    config: PlatformCoreLocalLoopConfig,
    *,
    artifact_fetcher: Any | None = None,
    local_runner: Any | None = None,
) -> dict[str, Any]:
    """Explicit live-network entrypoint for operator-controlled runs."""

    return run_platform_core_local_loop(
        config,
        execute=True,
        client=None,
        artifact_fetcher=artifact_fetcher,
        local_runner=local_runner,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or explicitly execute the Platform Core local loop runner.",
    )
    parser.add_argument("--execute-local-loop", action="store_true", help="Opt in to enqueue and worker execution.")
    parser.add_argument("--manifest", default=str(DEFAULT_P1_MANIFEST_PATH))
    parser.add_argument("--tenant-id", default="platform_review")
    parser.add_argument("--capability", default="video.project_edit.create_project")
    parser.add_argument("--input-json", help="Capability input object. Defaults to a project-edit no-upload input.")
    parser.add_argument("--artifact-ref-json", action="append", default=[])
    parser.add_argument("--base-url", default=DEFAULT_AGENTCTL_BASE_URL)
    parser.add_argument("--artifact-base-url", help="Base URL for Platform Core artifact byte downloads.")
    parser.add_argument("--token-env", default="VIDEO_TOOLKIT_AGENTCTL_TOKEN")
    parser.add_argument("--artifact-token-env", default="VIDEO_TOOLKIT_ARTIFACT_TOKEN")
    parser.add_argument("--artifact-root", default=str(Path(".video-toolkit-data") / "platform-core-loop-artifacts"))
    parser.add_argument("--execution-mode", default="in_process")
    args = parser.parse_args(argv)

    config = PlatformCoreLocalLoopConfig.from_env(
        tenant_id=args.tenant_id,
        capability=args.capability,
        input_payload=_load_json_text(args.input_json) if args.input_json else None,
        artifact_refs=[_load_json_text(item) for item in args.artifact_ref_json],
        manifest_path=args.manifest,
        base_url=args.base_url,
        artifact_base_url=args.artifact_base_url,
        token=os.environ.get(args.token_env),
        artifact_token=os.environ.get(args.artifact_token_env),
        artifact_root=args.artifact_root,
        execution_mode=args.execution_mode,
    )
    payload = run_platform_core_local_loop(config, execute=args.execute_local_loop)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("status") in {"preview_only", "completed"} else 2


def _worker_config(config: PlatformCoreLocalLoopConfig) -> VideoToolkitWorkerConfig:
    return VideoToolkitWorkerConfig(
        base_url=config.base_url,
        token=config.token,
        worker_id=config.worker_id,
        backend_id=config.backend_id,
        ttl_seconds=60,
        lease_seconds=30,
        timeout_seconds=config.timeout_seconds,
        artifact_root=Path(config.artifact_root),
        artifact_base_url=config.artifact_base_url or config.base_url,
        artifact_token=config.artifact_token,
        allowed_resource_classes=("cpu_light",),
        max_job_input_bytes=config.max_job_input_bytes,
        max_run_timeout_seconds=config.max_run_timeout_seconds,
        execution_mode=config.execution_mode,
    )


def _completion_source_from_worker_result(worker_result: Mapping[str, Any], client: Any) -> dict[str, Any]:
    completion_body = _latest_completion_body(client)
    if completion_body:
        return completion_body
    result = worker_result.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    return dict(worker_result)


def _latest_completion_body(client: Any) -> dict[str, Any]:
    requests = getattr(client, "requests", None)
    if not isinstance(requests, list):
        return {}
    for request in reversed(requests):
        if not isinstance(request, Mapping):
            continue
        path = request.get("path")
        body = request.get("body")
        if isinstance(path, str) and path.endswith("/complete") and isinstance(body, Mapping):
            return dict(body)
    return {}


def _load_json_text(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("JSON value must be an object.")
    return payload


def _caller_safe(value: Any, *, tokens: Sequence[str | None] = ()) -> Any:
    redaction_tokens = tuple(item for item in tokens if isinstance(item, str) and item)
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            key_string = str(key)
            normalized = key_string.lower()
            if normalized in FORBIDDEN_PUBLIC_KEYS:
                continue
            if any(part in normalized for part in ("token", "secret", "password", "api_key", "private_key")):
                safe[key_string] = "[redacted]"
                continue
            if normalized == "download_url" and isinstance(child, str):
                safe[key_string] = _safe_download_url(child, tokens=redaction_tokens)
            else:
                safe[key_string] = _caller_safe(child, tokens=redaction_tokens)
        return safe
    if isinstance(value, list):
        return [_caller_safe(child, tokens=redaction_tokens) for child in value]
    if isinstance(value, tuple):
        return [_caller_safe(child, tokens=redaction_tokens) for child in value]
    if isinstance(value, str):
        rendered = value
        for token in redaction_tokens:
            rendered = rendered.replace(token, "[redacted]")
        if any(pattern.search(rendered) for pattern in LOCAL_PATH_PATTERNS):
            return "[redacted]"
        return rendered
    return value


def _safe_download_url(value: str, *, tokens: Sequence[str]) -> str:
    rendered = value
    for token in tokens:
        rendered = rendered.replace(token, "[redacted]")
    parts = urlsplit(rendered)
    if not parts.query:
        return rendered
    query = [
        (key, "[redacted]" if key.lower() in SENSITIVE_QUERY_KEYS else query_value)
        for key, query_value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
