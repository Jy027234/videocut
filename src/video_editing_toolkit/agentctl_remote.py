"""Optional remote agentctl pre-integration probe for P0.9."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


TOOLKIT_ID = "video-editing-toolkit"
SCHEMA = "video_editing_toolkit.agentctl_remote.probe.v0"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "manifests"
    / "video-editing-toolkit.p0.manifest.json"
)

REQUIRED_AGENTCTL_PATHS = frozenset(
    {
        "/healthz",
        "/openapi.json",
        "/tool-catalog",
        "/tool-catalog/register",
        "/runtime/backends",
        "/runtime/backends/workers/protocol",
        "/runtime/backends/workers/heartbeat",
        "/runtime/backends/jobs",
        "/runtime/backends/jobs/lease",
        "/runtime/backends/jobs/{job_id}/complete",
        "/runspecs/run",
        "/runspecs/validate",
    }
)

Urlopen = Callable[..., Any]


@dataclass(frozen=True)
class AgentctlRemoteConfig:
    base_url: str = DEFAULT_BASE_URL
    token: str | None = None
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> "AgentctlRemoteConfig":
        selected_timeout = timeout_seconds
        if selected_timeout is None:
            selected_timeout = _float_env("VIDEO_TOOLKIT_AGENTCTL_TIMEOUT_SECONDS", 5.0)
        return cls(
            base_url=base_url
            or os.environ.get("VIDEO_TOOLKIT_AGENTCTL_BASE_URL")
            or DEFAULT_BASE_URL,
            token=token
            if token is not None
            else os.environ.get("VIDEO_TOOLKIT_AGENTCTL_TOKEN"),
            timeout_seconds=selected_timeout,
        )


class AgentctlRemoteError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class AgentctlRemoteClient:
    def __init__(
        self,
        config: AgentctlRemoteConfig,
        *,
        urlopen: Urlopen | None = None,
    ) -> None:
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._urlopen = urlopen or urllib.request.urlopen

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Mapping[str, Any] | None = None) -> Any:
        return self.request("POST", path, body=body)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{_normalize_path(path)}"
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            payload = _decode_json_bytes(exc.read())
            raise AgentctlRemoteError(
                _safe_error_message(payload, fallback=f"HTTP {exc.code}"),
                status_code=exc.code,
                error_code=_error_code(payload),
            ) from exc
        except urllib.error.URLError as exc:
            raise AgentctlRemoteError(f"connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AgentctlRemoteError("request timed out") from exc
        return _decode_json_bytes(raw)


def run_agentctl_remote_probe(
    *,
    config: AgentctlRemoteConfig,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    tenant_id: str = "demo_tenant",
    register: bool = False,
    validate_runspec: bool = False,
    worker_smoke: bool = False,
    client: AgentctlRemoteClient | None = None,
) -> dict[str, Any]:
    remote = client or AgentctlRemoteClient(config)
    endpoints: dict[str, Any] = {}
    timings_ms: dict[str, float] = {}

    health = _fetch(remote, endpoints, timings_ms, "healthz", "GET", "/healthz")
    openapi = _fetch(remote, endpoints, timings_ms, "openapi", "GET", "/openapi.json")
    catalog = _fetch(remote, endpoints, timings_ms, "tool_catalog", "GET", "/tool-catalog")
    protocol = _fetch(
        remote,
        endpoints,
        timings_ms,
        "runtime_worker_protocol",
        "GET",
        "/runtime/backends/workers/protocol",
    )
    backends = _fetch(
        remote,
        endpoints,
        timings_ms,
        "runtime_backends",
        "GET",
        "/runtime/backends",
    )
    jobs = _fetch(
        remote,
        endpoints,
        timings_ms,
        "runtime_jobs",
        "GET",
        "/runtime/backends/jobs",
        required=False,
    )

    registration_payload = build_tool_catalog_registration_payload(
        manifest_path,
        tenant_id=tenant_id,
    )
    runspec_payload = build_runspec_validation_payload(tenant_id=tenant_id)
    if validate_runspec:
        runspec_validation_result = _fetch(
            remote,
            endpoints,
            timings_ms,
            "runspec_validate",
            "POST",
            "/runspecs/validate",
            body=runspec_payload,
        )
    else:
        runspec_validation_result = {
            "skipped": True,
            "reason": "runspec_validation_not_requested",
        }
        endpoints["runspec_validate"] = {
            "ok": True,
            "skipped": True,
            "method": "POST",
            "path": "/runspecs/validate",
        }

    if register:
        registration_result = _fetch(
            remote,
            endpoints,
            timings_ms,
            "tool_catalog_register",
            "POST",
            "/tool-catalog/register",
            body=registration_payload,
        )
    else:
        registration_result = {
            "skipped": True,
            "reason": "mutation_not_requested",
        }
        endpoints["tool_catalog_register"] = {
            "ok": True,
            "skipped": True,
            "method": "POST",
            "path": "/tool-catalog/register",
        }

    worker_result: dict[str, Any] = {
        "skipped": True,
        "reason": "worker_smoke_not_requested",
    }
    if worker_smoke:
        worker_result = run_worker_smoke(remote, endpoints=endpoints, timings_ms=timings_ms)

    missing_paths = _missing_required_paths(openapi)
    report = {
        "schema": SCHEMA,
        "transport": "agentctl.remote",
        "toolkit_id": TOOLKIT_ID,
        "ok": _required_endpoints_ok(endpoints) and not missing_paths,
        "agentctl": _agentctl_summary(health, openapi),
        "tool_catalog": _tool_catalog_summary(catalog, registration_payload),
        "runtime": _runtime_summary(protocol, backends, jobs),
        "runspec_validation": {
            "dry_run": not validate_runspec,
            "payload": runspec_payload,
            "result": runspec_validation_result,
            "valid": _get(runspec_validation_result, "valid"),
        },
        "compatibility": {
            "required_paths_present": not missing_paths,
            "missing_required_paths": missing_paths,
            "checked_paths": sorted(REQUIRED_AGENTCTL_PATHS),
        },
        "registration": {
            "tool_id": registration_payload["tool_id"],
            "capability_count": len(registration_payload["tool_schema"]["properties"]["capability"]["enum"]),
            "dry_run": not register,
            "payload": registration_payload,
            "result": registration_result,
        },
        "worker_smoke": worker_result,
        "performance_decision": _performance_decision(backends),
        "endpoints": endpoints,
        "timings_ms": timings_ms,
    }
    return _caller_safe(report, token=config.token)


def build_tool_catalog_registration_payload(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    tenant_id: str = "demo_tenant",
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    capabilities = [
        item["capability"]
        for item in manifest.get("capabilities", [])
        if isinstance(item, Mapping)
        and item.get("status") == "enabled"
        and isinstance(item.get("capability"), str)
    ]
    return {
        "tenant_id": tenant_id,
        "tool_id": manifest.get("toolkit_id", TOOLKIT_ID),
        "display_name": manifest.get("display_name", "Video Editing Toolkit"),
        "tool_schema": {
            "type": "object",
            "additionalProperties": True,
            "required": ["toolkit_id", "capability", "input"],
            "properties": {
                "toolkit_id": {"const": manifest.get("toolkit_id", TOOLKIT_ID)},
                "capability": {
                    "type": "string",
                    "enum": sorted(capabilities),
                },
                "input": {"type": "object"},
                "artifact_refs": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "policy_context": {"type": "object"},
            },
        },
        "side_effects": [
            "artifact:read",
            "artifact:write",
            "trace:write",
            "render:cpu",
        ],
        "required_scopes": list(manifest.get("required_scopes", [])),
        "secret_refs": [],
        "metadata": {
            "version": manifest.get("version"),
            "category": manifest.get("category"),
            "status": manifest.get("status"),
            "runtime_adapter_target": _runtime_adapter_target(manifest),
            "preferred_agentctl_path": "/runtime/backends/workers/protocol",
            "execution_model": "external_video_toolkit_worker",
            "artifact_contract": "artifact_ref_only",
            "network_access": "disabled_by_default",
        },
    }


def build_runspec_validation_payload(*, tenant_id: str = "demo_tenant") -> dict[str, Any]:
    return {
        "kind": "RunSpecDraft",
        "draft_id": "runspecdraft_video_toolkit_p0_probe",
        "title": "Video Editing Toolkit P0 no-upload probe",
        "description": "Validate the agentctl RunSpec envelope for an external video toolkit worker.",
        "target_agent": "video_editing_toolkit_agentctl",
        "tenant_id": tenant_id,
        "trace_id": "trace_video_toolkit_p0_probe",
        "priority": "low",
        "data_sensitivity": "D1",
        "risk_level": "R1",
        "required_level": "L1",
        "routing_mode": "external_worker",
        "business_chain_id": "video_toolkit_p0_preintegration",
        "source": "video_editing_toolkit.p0_probe",
        "input_payload": {
            "toolkit_id": TOOLKIT_ID,
            "capability": "video.project_edit.create_project",
            "input": {
                "project_id": "proj_agentctl_remote_probe",
            },
            "artifact_refs": [],
            "policy_context": {
                "tenant_id": tenant_id,
                "user_id": "agentctl_remote_probe",
                "data_policy": {"artifact_contract": "artifact_ref_only"},
                "quota_policy": {"profile": "p0_probe"},
            },
        },
        "metadata": {
            "toolkit_id": TOOLKIT_ID,
            "execution_model": "external_video_toolkit_worker",
            "capability_class": "no_upload_contract_probe",
            "dispatch_recommendation": "enqueue_only_after_worker_registration",
            "run_heavy_media_inside_agentctl": False,
        },
    }


def build_runspec_enqueue_payload(
    *,
    tenant_id: str = "demo_tenant",
    backend_id: str = "local",
    capability: str = "video.project_edit.create_project",
    input_payload: Mapping[str, Any] | None = None,
    artifact_refs: Sequence[Mapping[str, Any]] | None = None,
    trace_id: str = "trace_video_toolkit_queue_smoke",
    draft_id: str = "runspecdraft_video_toolkit_queue_smoke",
) -> dict[str, Any]:
    """Build a RunSpec payload for queue smoke tests against existing artifact_refs."""

    payload = build_runspec_validation_payload(tenant_id=tenant_id)
    payload.update(
        {
            "draft_id": draft_id,
            "title": "Video Editing Toolkit queue smoke",
            "description": "Enqueue an external video toolkit worker run against existing Platform Core artifact_refs.",
            "trace_id": trace_id,
            "dispatch_mode": "enqueue",
            "backend_id": backend_id,
        }
    )
    payload["input_payload"] = {
        "toolkit_id": TOOLKIT_ID,
        "capability": capability,
        "input": dict(input_payload or {"project_id": "proj_agentctl_queue_smoke"}),
        "artifact_refs": [dict(item) for item in artifact_refs or ()],
        "policy_context": {
            "tenant_id": tenant_id,
            "user_id": "agentctl_queue_smoke",
            "data_policy": {"artifact_contract": "artifact_ref_only"},
            "quota_policy": {"profile": "queue_smoke"},
        },
    }
    payload["metadata"] = {
        **dict(payload.get("metadata") or {}),
        "capability_class": "queue_smoke_existing_artifact_refs",
        "dispatch_recommendation": "enqueue_with_external_worker",
    }
    return payload


def run_worker_smoke(
    client: AgentctlRemoteClient,
    *,
    endpoints: dict[str, Any],
    timings_ms: dict[str, float],
) -> dict[str, Any]:
    worker_id = "video-toolkit-p0-probe"
    heartbeat_body = {
        "worker_id": worker_id,
        "backend_id": "local",
        "capacity": 1,
        "ttl_seconds": 30,
        "tags": ["video-toolkit", "p0-probe"],
        "metadata": {
            "toolkit_id": TOOLKIT_ID,
            "purpose": "agentctl pre-integration smoke",
        },
    }
    heartbeat = _fetch(
        client,
        endpoints,
        timings_ms,
        "runtime_worker_heartbeat",
        "POST",
        "/runtime/backends/workers/heartbeat",
        body=heartbeat_body,
        required=False,
    )
    lease = _fetch(
        client,
        endpoints,
        timings_ms,
        "runtime_job_lease",
        "POST",
        "/runtime/backends/jobs/lease",
        body={"worker_id": worker_id, "backend_id": "local", "lease_seconds": 30},
        required=False,
    )
    return {
        "worker_id": worker_id,
        "heartbeat_ok": endpoints.get("runtime_worker_heartbeat", {}).get("ok") is True,
        "lease_ok": endpoints.get("runtime_job_lease", {}).get("ok") is True,
        "heartbeat": _summarize_worker_response(heartbeat),
        "lease": _summarize_worker_response(lease),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe a remote agentctl Docker/API boundary for the video editing toolkit.",
    )
    parser.add_argument("--base-url", help="agentctl base URL. Defaults to VIDEO_TOOLKIT_AGENTCTL_BASE_URL or localhost.")
    parser.add_argument("--token", help="Bearer token. Prefer VIDEO_TOOLKIT_AGENTCTL_TOKEN for local use.")
    parser.add_argument("--timeout-seconds", type=float, help="HTTP timeout in seconds.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Toolkit manifest to convert into a tool-catalog payload.")
    parser.add_argument("--tenant-id", default="demo_tenant", help="Tenant id for the optional tool-catalog payload.")
    parser.add_argument("--register", action="store_true", help="Actually POST to /tool-catalog/register. Default is dry-run.")
    parser.add_argument("--validate-runspec", action="store_true", help="POST a no-upload RunSpecDraft to /runspecs/validate.")
    parser.add_argument("--worker-smoke", action="store_true", help="POST a short worker heartbeat and idle lease smoke.")
    args = parser.parse_args(argv)

    config = AgentctlRemoteConfig.from_env(
        base_url=args.base_url,
        token=args.token,
        timeout_seconds=args.timeout_seconds,
    )
    report = run_agentctl_remote_probe(
        config=config,
        manifest_path=args.manifest,
        tenant_id=args.tenant_id,
        register=args.register,
        validate_runspec=args.validate_runspec,
        worker_smoke=args.worker_smoke,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("ok") else 2


def _fetch(
    client: AgentctlRemoteClient,
    endpoints: dict[str, Any],
    timings_ms: dict[str, float],
    name: str,
    method: str,
    path: str,
    *,
    body: Mapping[str, Any] | None = None,
    required: bool = True,
) -> Any:
    start = time.perf_counter()
    try:
        if method == "GET":
            payload = client.get(path)
        else:
            payload = client.post(path, body)
    except AgentctlRemoteError as exc:
        endpoints[name] = {
            "ok": False,
            "required": required,
            "method": method,
            "path": path,
            "status_code": exc.status_code,
            "error_code": exc.error_code,
            "error_message": str(exc),
        }
        timings_ms[name] = _elapsed_ms(start)
        return None

    endpoints[name] = {
        "ok": True,
        "required": required,
        "method": method,
        "path": path,
    }
    timings_ms[name] = _elapsed_ms(start)
    return payload


def _required_endpoints_ok(endpoints: Mapping[str, Any]) -> bool:
    for item in endpoints.values():
        if item.get("required", True) and item.get("ok") is not True:
            return False
    return True


def _agentctl_summary(health: Any, openapi: Any) -> dict[str, Any]:
    return {
        "health": _get(health, "status"),
        "api_title": _get(_get(openapi, "info"), "title"),
        "api_version": _get(_get(openapi, "info"), "version"),
        "route_count": _get(openapi, "x-agentctl-route-count"),
        "generated_from": _get(openapi, "x-agentctl-generated-from"),
    }


def _tool_catalog_summary(catalog: Any, registration_payload: Mapping[str, Any]) -> dict[str, Any]:
    tools = _list(_get(catalog, "tools"))
    tool_id = str(registration_payload.get("tool_id"))
    return {
        "count": _get(catalog, "count", len(tools)),
        "toolkit_already_registered": any(_get(tool, "tool_id") == tool_id for tool in tools),
    }


def _runtime_summary(protocol: Any, backends: Any, jobs: Any) -> dict[str, Any]:
    backend_items = _list(_get(backends, "backends"))
    ready_backends = [
        _get(item, "id")
        for item in backend_items
        if _get(item, "available") is True or _get(item, "status") == "ready"
    ]
    return {
        "protocol_version": _get(protocol, "protocol_version"),
        "transport": _get(protocol, "transport"),
        "lifecycle": _list(_get(protocol, "lifecycle")),
        "default_backend_id": _get(backends, "default_backend_id"),
        "ready_backends": ready_backends,
        "docker_backend": _backend_summary(backend_items, "docker"),
        "job_count": len(_list(_get(jobs, "jobs"))),
    }


def _backend_summary(backends: list[Any], backend_id: str) -> dict[str, Any]:
    for item in backends:
        if _get(item, "id") == backend_id:
            return {
                "id": _get(item, "id"),
                "kind": _get(item, "kind"),
                "enabled": _get(item, "enabled"),
                "available": _get(item, "available"),
                "status": _get(item, "status"),
                "dispatch_mode": _get(_get(item, "probe"), "dispatch_mode"),
            }
    return {"id": backend_id, "status": "missing"}


def _performance_decision(backends: Any) -> dict[str, Any]:
    backend_items = _list(_get(backends, "backends"))
    docker_backend = _backend_summary(backend_items, "docker")
    docker_ready = docker_backend.get("enabled") is True and docker_backend.get("available") is True
    return {
        "recommended_stage": "P0.9-agentctl-docker-preintegration",
        "connect_now": True,
        "promote_to_p1": False,
        "deployment_model": "standalone_video_toolkit_worker",
        "agentctl_role": "catalog_and_runtime_dispatch_boundary",
        "run_heavy_media_inside_agentctl": False,
        "isolated_runtime_backend_available": docker_ready,
        "reasons": [
            "agentctl HTTP API is available for catalog, runtime protocol, and job dispatch checks",
            "video rendering, scene analysis, and speech work should stay in a separate toolkit worker/container",
            "current agentctl Docker backend can be treated as a control-plane boundary until isolated workers are enabled",
        ],
    }


def _missing_required_paths(openapi: Any) -> list[str]:
    paths = _get(openapi, "paths", {})
    if not isinstance(paths, Mapping):
        return sorted(REQUIRED_AGENTCTL_PATHS)
    return sorted(path for path in REQUIRED_AGENTCTL_PATHS if path not in paths)


def _summarize_worker_response(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    summary: dict[str, Any] = {}
    for key in (
        "ok",
        "status",
        "worker_id",
        "backend_id",
        "lease_id",
        "expired_leases_requeued",
        "job",
    ):
        if key in value:
            summary[key] = value[key]
    return summary or {"keys": sorted(str(key) for key in value)}


def _load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    raw = Path(manifest_path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Toolkit manifest must be a JSON object.")
    return payload


def _runtime_adapter_target(manifest: Mapping[str, Any]) -> str | None:
    runtime = manifest.get("runtime_adapter")
    if not isinstance(runtime, Mapping):
        return None
    value = runtime.get("target")
    return value if isinstance(value, str) else None


def _decode_json_bytes(raw: bytes) -> Any:
    if not raw:
        return {}
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _safe_error_message(payload: Any, *, fallback: str) -> str:
    if isinstance(payload, Mapping):
        for key in ("detail", "error_message", "message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return fallback


def _error_code(payload: Any) -> str | None:
    if isinstance(payload, Mapping):
        value = payload.get("error_code") or payload.get("code")
        if isinstance(value, str) and value:
            return value
    return None


def _caller_safe(value: Any, *, token: str | None) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            key_string = str(key)
            if "token" in key_string.lower() or "secret" in key_string.lower():
                safe[key_string] = "[redacted]"
            else:
                safe[key_string] = _caller_safe(child, token=token)
        return safe
    if isinstance(value, list):
        return [_caller_safe(child, token=token) for child in value]
    if isinstance(value, str) and token:
        return value.replace(token, "[redacted]")
    return value


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return default


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
