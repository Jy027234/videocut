"""External agentctl runtime worker for the video editing toolkit."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

from video_editing_toolkit.agentctl_remote import (
    AgentctlRemoteClient,
    AgentctlRemoteConfig,
    build_runspec_validation_payload,
)
from video_editing_toolkit.agentctl_worker_policy import (
    DEFAULT_ALLOWED_RESOURCE_CLASSES,
    WorkerExecutionPolicyConfig,
    WorkerExecutionPolicyError,
    parse_csv_tuple,
    validate_worker_execution_policy,
)
from video_editing_toolkit.agentctl_worker_runner import (
    IN_PROCESS_EXECUTION_MODE,
    SUPPORTED_EXECUTION_BACKENDS,
    WorkerExecutionBackendUnavailable,
    WorkerLocalExecutionError,
    WorkerLocalExecutionTimeout,
    run_local_agentctl,
)
from video_editing_toolkit.storage import (
    ArtifactMaterializationConfig,
    ArtifactMaterializationError,
    LocalArtifactStore,
    materialize_artifact_refs,
)
from video_editing_toolkit.storage.materialize import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    ArtifactBytesFetcher,
)


SCHEMA = "video_editing_toolkit.agentctl_worker.run.v0"
TOOLKIT_ID = "video-editing-toolkit"
DEFAULT_WORKER_ID = "video-toolkit-worker-1"
DEFAULT_BACKEND_ID = "local"
DEFAULT_ARTIFACT_ROOT = Path(".video-toolkit-data") / "agentctl-worker-artifacts"
WORKER_LIFECYCLE_CONTRACT = "p0.14_execution_backend_attempt_trace_usage"

FORBIDDEN_PUBLIC_KEYS = {
    "argv",
    "authorization",
    "cmd",
    "command",
    "env",
    "environment",
    "file_path",
    "filesystem_path",
    "internal_path",
    "local_path",
    "stderr",
    "stdout",
    "storage_uri",
    "worker_path",
}

LOCAL_DETAIL_PATTERNS = (
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)[^\s\"']+"),
    re.compile(r"\\\\[^\\/\s\"']+[\\/][^\s\"']+"),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"local-artifact://", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])/(Users|home|var|tmp|private|mnt)/[^\s\"']+"),
)

URL_OR_SECRET_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"(?i)(bearer|token|secret|password|api[_-]?key)\s*[:=]"),
)


@dataclass(frozen=True)
class VideoToolkitWorkerConfig:
    base_url: str
    token: str | None
    worker_id: str = DEFAULT_WORKER_ID
    backend_id: str = DEFAULT_BACKEND_ID
    capacity: int = 1
    ttl_seconds: int = 120
    lease_seconds: int = 300
    timeout_seconds: float = 10.0
    idle_sleep_seconds: float = 2.0
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT
    artifact_base_url: str | None = None
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    allowed_resource_classes: tuple[str, ...] = DEFAULT_ALLOWED_RESOURCE_CLASSES
    allowed_capabilities: tuple[str, ...] = ()
    max_job_input_bytes: int = 512 * 1024 * 1024
    max_run_timeout_seconds: int = 120
    execution_mode: str = IN_PROCESS_EXECUTION_MODE
    max_attempts: int = 1

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        token: str | None = None,
        worker_id: str | None = None,
        backend_id: str | None = None,
        capacity: int | None = None,
        ttl_seconds: int | None = None,
        lease_seconds: int | None = None,
        timeout_seconds: float | None = None,
        idle_sleep_seconds: float | None = None,
        artifact_root: str | Path | None = None,
        artifact_base_url: str | None = None,
        max_artifact_bytes: int | None = None,
        allowed_resource_classes: Sequence[str] | None = None,
        allowed_capabilities: Sequence[str] | None = None,
        max_job_input_bytes: int | None = None,
        max_run_timeout_seconds: int | None = None,
        execution_mode: str | None = None,
        max_attempts: int | None = None,
    ) -> "VideoToolkitWorkerConfig":
        selected_base_url = (
            base_url
            or os.environ.get("VIDEO_TOOLKIT_AGENTCTL_BASE_URL")
            or "http://127.0.0.1:8765"
        )
        return cls(
            base_url=selected_base_url,
            token=token
            if token is not None
            else os.environ.get("VIDEO_TOOLKIT_AGENTCTL_TOKEN"),
            worker_id=worker_id
            or os.environ.get("VIDEO_TOOLKIT_AGENTCTL_WORKER_ID")
            or DEFAULT_WORKER_ID,
            backend_id=backend_id
            or os.environ.get("VIDEO_TOOLKIT_AGENTCTL_BACKEND_ID")
            or DEFAULT_BACKEND_ID,
            capacity=capacity
            if capacity is not None
            else _int_env("VIDEO_TOOLKIT_AGENTCTL_WORKER_CAPACITY", 1),
            ttl_seconds=ttl_seconds
            if ttl_seconds is not None
            else _int_env("VIDEO_TOOLKIT_AGENTCTL_TTL_SECONDS", 120),
            lease_seconds=lease_seconds
            if lease_seconds is not None
            else _int_env("VIDEO_TOOLKIT_AGENTCTL_LEASE_SECONDS", 300),
            timeout_seconds=timeout_seconds
            if timeout_seconds is not None
            else _float_env("VIDEO_TOOLKIT_AGENTCTL_TIMEOUT_SECONDS", 10.0),
            idle_sleep_seconds=idle_sleep_seconds
            if idle_sleep_seconds is not None
            else _float_env("VIDEO_TOOLKIT_AGENTCTL_IDLE_SLEEP_SECONDS", 2.0),
            artifact_root=Path(
                artifact_root
                or os.environ.get("VIDEO_TOOLKIT_ARTIFACT_ROOT")
                or DEFAULT_ARTIFACT_ROOT
            ),
            artifact_base_url=artifact_base_url
            or os.environ.get("VIDEO_TOOLKIT_ARTIFACT_BASE_URL")
            or selected_base_url,
            max_artifact_bytes=max_artifact_bytes
            if max_artifact_bytes is not None
            else _int_env("VIDEO_TOOLKIT_MAX_ARTIFACT_BYTES", DEFAULT_MAX_ARTIFACT_BYTES),
            allowed_resource_classes=tuple(allowed_resource_classes)
            if allowed_resource_classes is not None
            else (
                parse_csv_tuple(os.environ.get("VIDEO_TOOLKIT_ALLOWED_RESOURCE_CLASSES"))
                or DEFAULT_ALLOWED_RESOURCE_CLASSES
            ),
            allowed_capabilities=tuple(allowed_capabilities)
            if allowed_capabilities is not None
            else parse_csv_tuple(os.environ.get("VIDEO_TOOLKIT_ALLOWED_CAPABILITIES")),
            max_job_input_bytes=max_job_input_bytes
            if max_job_input_bytes is not None
            else _int_env("VIDEO_TOOLKIT_MAX_JOB_INPUT_BYTES", 512 * 1024 * 1024),
            max_run_timeout_seconds=max_run_timeout_seconds
            if max_run_timeout_seconds is not None
            else _int_env("VIDEO_TOOLKIT_MAX_RUN_TIMEOUT_SECONDS", 120),
            execution_mode=execution_mode
            or os.environ.get("VIDEO_TOOLKIT_EXECUTION_BACKEND")
            or os.environ.get("VIDEO_TOOLKIT_EXECUTION_MODE")
            or IN_PROCESS_EXECUTION_MODE,
            max_attempts=max_attempts
            if max_attempts is not None
            else _int_env("VIDEO_TOOLKIT_MAX_ATTEMPTS", 1),
        )

    def remote_config(self) -> AgentctlRemoteConfig:
        return AgentctlRemoteConfig(
            base_url=self.base_url,
            token=self.token,
            timeout_seconds=self.timeout_seconds,
        )

    def materialization_config(self) -> ArtifactMaterializationConfig:
        return ArtifactMaterializationConfig(
            artifact_base_url=self.artifact_base_url,
            token=self.token,
            timeout_seconds=self.timeout_seconds,
            max_artifact_bytes=self.max_artifact_bytes,
        )

    def execution_policy_config(self) -> WorkerExecutionPolicyConfig:
        return WorkerExecutionPolicyConfig(
            allowed_resource_classes=self.allowed_resource_classes,
            allowed_capabilities=self.allowed_capabilities,
            max_job_input_bytes=self.max_job_input_bytes,
            max_run_timeout_seconds=self.max_run_timeout_seconds,
        )


class VideoToolkitAgentctlWorker:
    def __init__(
        self,
        config: VideoToolkitWorkerConfig,
        *,
        client: AgentctlRemoteClient | None = None,
        artifact_fetcher: ArtifactBytesFetcher | None = None,
        local_runner: Any | None = None,
    ) -> None:
        self.config = config
        self.client = client or AgentctlRemoteClient(config.remote_config())
        self.artifact_fetcher = artifact_fetcher
        self.local_runner = local_runner or run_local_agentctl

    def run_once(self, *, expected_job_id: str | None = None) -> dict[str, Any]:
        heartbeat = self.heartbeat()
        lease = self.lease()
        job = lease.get("job")
        if not isinstance(job, Mapping):
            return _caller_safe(
                {
                    "schema": SCHEMA,
                    "transport": "agentctl.runtime_worker",
                    "ok": True,
                    "status": "idle",
                    "worker_id": self.config.worker_id,
                    "backend_id": self.config.backend_id,
                    "heartbeat": _summarize_worker(heartbeat),
                    "lease": _summarize_lease(lease),
                    "completion": None,
                },
                token=self.config.token,
            )

        job_id = _optional_string(job.get("job_id"))
        if expected_job_id is not None and job_id != expected_job_id:
            return _caller_safe(
                {
                    "schema": SCHEMA,
                    "transport": "agentctl.runtime_worker",
                    "ok": False,
                    "status": "unexpected_job_leased",
                    "worker_id": self.config.worker_id,
                    "backend_id": self.config.backend_id,
                    "heartbeat": _summarize_worker(heartbeat),
                    "lease": _summarize_lease(lease),
                    "expected_job_id": expected_job_id,
                    "leased_job_id": job_id,
                    "completion": None,
                    "error_code": "video_toolkit_worker.unexpected_job_leased",
                    "error_message": "Worker leased a job that was not created by the explicit enqueue probe.",
                },
                token=self.config.token,
            )

        result = self.execute_job(job, lease_id=_optional_string(lease.get("lease_id")))
        completion = self.complete(job, lease, result)
        return _caller_safe(
            {
                "schema": SCHEMA,
                "transport": "agentctl.runtime_worker",
                "ok": result["status"] == "completed",
                "status": result["status"],
                "worker_id": self.config.worker_id,
                "backend_id": self.config.backend_id,
                "heartbeat": _summarize_worker(heartbeat),
                "lease": _summarize_lease(lease),
                "job": {
                    "job_id": job.get("job_id"),
                    "target_agent": job.get("target_agent"),
                    "tenant": job.get("tenant"),
                    "trace_id": job.get("trace_id"),
                    "status": job.get("status"),
                    "attempts": job.get("attempts"),
                },
                "result": result,
                "completion": _summarize_completion(completion),
            },
            token=self.config.token,
        )

    def run_loop(self, *, max_jobs: int | None = None) -> dict[str, Any]:
        processed = 0
        idle_cycles = 0
        last_result: dict[str, Any] | None = None
        while max_jobs is None or processed < max_jobs:
            result = self.run_once()
            last_result = result
            if result["status"] == "idle":
                idle_cycles += 1
                if max_jobs is not None:
                    break
                time.sleep(max(self.config.idle_sleep_seconds, 0.0))
                continue
            processed += 1
        return _caller_safe(
            {
                "schema": SCHEMA,
                "transport": "agentctl.runtime_worker",
                "ok": True,
                "status": "stopped",
                "worker_id": self.config.worker_id,
                "backend_id": self.config.backend_id,
                "processed_jobs": processed,
                "idle_cycles": idle_cycles,
                "last_result": last_result,
            },
            token=self.config.token,
        )

    def heartbeat(self) -> dict[str, Any]:
        return self.client.post(
            "/runtime/backends/workers/heartbeat",
            {
                "worker_id": self.config.worker_id,
                "backend_id": self.config.backend_id,
                "capacity": self.config.capacity,
                "ttl_seconds": self.config.ttl_seconds,
                "tags": ["video-toolkit", "external-worker"],
                "metadata": {
                    "toolkit_id": TOOLKIT_ID,
                    "runner": "video_editing_toolkit.agentctl_worker",
                    "artifact_contract": "artifact_ref_only",
                    "artifact_materialization": "controlled_download_to_local_store",
                    "allowed_resource_classes": list(self.config.allowed_resource_classes),
                    "allowed_capabilities": list(self.config.allowed_capabilities),
                    "max_job_input_bytes": self.config.max_job_input_bytes,
                    "max_run_timeout_seconds": self.config.max_run_timeout_seconds,
                    "execution_mode": self.config.execution_mode,
                    "execution_backend": self.config.execution_mode,
                    "supported_execution_backends": sorted(SUPPORTED_EXECUTION_BACKENDS),
                    "worker_lifecycle_contract": WORKER_LIFECYCLE_CONTRACT,
                    "max_attempts": self.config.max_attempts,
                    "retry_policy": {
                        "mode": "attempt_preflight_only",
                        "max_attempts": self.config.max_attempts,
                    },
                    "cancel_contract": "pre_execution_cancel_requested_only",
                },
            },
        )

    def lease(self) -> dict[str, Any]:
        return self.client.post(
            "/runtime/backends/jobs/lease",
            {
                "worker_id": self.config.worker_id,
                "backend_id": self.config.backend_id,
                "lease_seconds": self.config.lease_seconds,
            },
        )

    def execute_job(self, job: Mapping[str, Any], *, lease_id: str | None) -> dict[str, Any]:
        started = perf_counter()
        attempt = _job_attempt(job)
        trace_ref = _trace_ref_from_job(job)
        try:
            if _job_cancel_requested(job):
                return _worker_error_result(
                    status="failed",
                    execution_mode=self.config.execution_mode,
                    error_code="video_toolkit_worker.execution_cancelled",
                    error_message="Worker skipped local execution because the runtime job is marked for cancellation.",
                    reason_code="worker.cancel_requested",
                    started=started,
                    attempt=attempt,
                    max_attempts=self.config.max_attempts,
                    trace_ref=trace_ref,
                    extra_output={"cancelled": True},
                )
            if attempt > self.config.max_attempts:
                return _worker_error_result(
                    status="failed",
                    execution_mode=self.config.execution_mode,
                    error_code="video_toolkit_worker.retry_attempts_exhausted",
                    error_message="Runtime job attempt exceeds this worker retry policy.",
                    reason_code="worker.max_attempts_exceeded",
                    started=started,
                    attempt=attempt,
                    max_attempts=self.config.max_attempts,
                    trace_ref=trace_ref,
                )
            envelope = toolkit_envelope_from_job(
                job,
                worker_id=self.config.worker_id,
                lease_id=lease_id,
            )
            trace_ref = _optional_string(envelope.get("trace_ref")) or trace_ref
            policy = validate_worker_execution_policy(
                envelope,
                config=self.config.execution_policy_config(),
            )
            artifact_store = LocalArtifactStore(self.config.artifact_root)
            materialize_artifact_refs(
                envelope,
                artifact_store=artifact_store,
                config=self.config.materialization_config(),
                fetch_bytes=self.artifact_fetcher,
            )
            local_result = self.local_runner(
                envelope,
                artifact_root=self.config.artifact_root,
                execution_mode=self.config.execution_mode,
                timeout_seconds=_execution_timeout_seconds(
                    policy.route_timeout_seconds,
                    self.config,
                ),
            )
            status = "completed" if local_result.get("ok") is True else "failed"
            trace_ref = _trace_ref_from_agentctl_result(local_result) or trace_ref
            usage_metrics = _worker_usage_metrics(
                local_result,
                started=started,
                policy=policy,
                execution_mode=self.config.execution_mode,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
            )
            return {
                "status": status,
                "execution_mode": self.config.execution_mode,
                "execution_backend": self.config.execution_mode,
                "trace_ref": trace_ref,
                "usage_metrics": usage_metrics,
                "attempt": attempt,
                "max_attempts": self.config.max_attempts,
                "output": local_result,
                "error": None
                if status == "completed"
                else _safe_error_message(_error_from_agentctl_result(local_result)),
            }
        except WorkerExecutionPolicyError as exc:
            return _worker_error_result(
                status="failed",
                execution_mode=self.config.execution_mode,
                error_code="video_toolkit_worker.execution_policy_rejected",
                error_message=exc.error_message,
                reason_code=exc.reason_code,
                started=started,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
                trace_ref=trace_ref,
                extra_output={
                    "capability": exc.capability,
                    "resource_class": exc.resource_class,
                },
            )
        except WorkerLocalExecutionTimeout as exc:
            return _worker_error_result(
                status="failed",
                execution_mode=self.config.execution_mode,
                error_code="video_toolkit_worker.execution_timeout",
                error_message=exc.error_message,
                reason_code=exc.reason_code,
                started=started,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
                trace_ref=trace_ref,
            )
        except WorkerExecutionBackendUnavailable as exc:
            return _worker_error_result(
                status="failed",
                execution_mode=self.config.execution_mode,
                error_code="video_toolkit_worker.execution_backend_unavailable",
                error_message=exc.error_message,
                reason_code=exc.reason_code,
                started=started,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
                trace_ref=trace_ref,
                extra_output={"execution_backend": getattr(exc, "execution_backend", self.config.execution_mode)},
            )
        except WorkerLocalExecutionError as exc:
            return _worker_error_result(
                status="failed",
                execution_mode=self.config.execution_mode,
                error_code="video_toolkit_worker.local_execution_failed",
                error_message=exc.error_message,
                reason_code=exc.reason_code,
                started=started,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
                trace_ref=trace_ref,
            )
        except ArtifactMaterializationError as exc:
            return _worker_error_result(
                status="failed",
                execution_mode=self.config.execution_mode,
                error_code="video_toolkit_worker.artifact_materialization_failed",
                error_message=exc.error_message,
                reason_code=exc.error_code,
                started=started,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
                trace_ref=trace_ref,
                extra_output={"artifact_id": exc.artifact_id},
            )
        except Exception as exc:
            return _worker_error_result(
                status="failed",
                execution_mode=self.config.execution_mode,
                error_code="video_toolkit_worker.execution_failed",
                error_message=str(exc),
                reason_code="worker.execution_failed",
                started=started,
                attempt=attempt,
                max_attempts=self.config.max_attempts,
                trace_ref=trace_ref,
                extra_output={"exception": exc.__class__.__name__},
            )

    def complete(
        self,
        job: Mapping[str, Any],
        lease: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        job_id = _required_string(job, "job_id")
        body = {
            "worker_id": self.config.worker_id,
            "lease_id": lease.get("lease_id"),
            "status": result["status"],
            "result": result.get("output"),
            "error": result.get("error"),
            "metadata": {
                "worker_lifecycle_contract": WORKER_LIFECYCLE_CONTRACT,
                "execution_backend": result.get("execution_backend")
                or result.get("execution_mode")
                or self.config.execution_mode,
                "trace_ref": result.get("trace_ref"),
                "usage_metrics": result.get("usage_metrics", {}),
                "attempt": result.get("attempt"),
                "max_attempts": result.get("max_attempts", self.config.max_attempts),
                "retry_policy": {
                    "mode": "attempt_preflight_only",
                    "max_attempts": self.config.max_attempts,
                },
            },
        }
        return self.client.post(
            f"/runtime/backends/jobs/{job_id}/complete",
            _caller_safe(body, token=self.config.token),
        )


def toolkit_envelope_from_job(
    job: Mapping[str, Any],
    *,
    worker_id: str,
    lease_id: str | None = None,
) -> dict[str, Any]:
    payload = _mapping_field(job, "payload")
    candidate = _mapping_field(payload, "input_payload") or payload
    if not candidate:
        raise ValueError("job payload is missing input_payload")
    toolkit_id = candidate.get("toolkit_id")
    capability = candidate.get("capability")
    if toolkit_id != TOOLKIT_ID or not isinstance(capability, str) or not capability:
        raise ValueError("job payload is not a video-editing-toolkit envelope")

    envelope = dict(candidate)
    if job.get("job_id") is not None:
        envelope.setdefault("run_id", str(job["job_id"]))
    if lease_id:
        envelope.setdefault("tool_call_id", lease_id)
    trace_ref = (
        _optional_string(envelope.get("trace_ref"))
        or _optional_string(envelope.get("trace_id"))
        or _optional_string(payload.get("trace_id"))
        or _optional_string(job.get("trace_id"))
    )
    if trace_ref:
        envelope.setdefault("trace_ref", trace_ref)
    if "policy_context" not in envelope:
        envelope["policy_context"] = {
            "tenant_id": _optional_string(job.get("tenant")) or "demo_tenant",
            "user_id": worker_id,
            "data_policy": {"artifact_contract": "artifact_ref_only"},
        }
    return envelope


def enqueue_probe_runspec(
    worker: VideoToolkitAgentctlWorker,
    *,
    tenant_id: str = "demo_tenant",
) -> dict[str, Any]:
    payload = build_runspec_validation_payload(tenant_id=tenant_id)
    payload["dispatch_mode"] = "enqueue"
    payload["backend_id"] = worker.config.backend_id
    payload["metadata"] = {
        **dict(payload.get("metadata") or {}),
        "queued_by": "video_editing_toolkit.agentctl_worker",
        "worker_id": worker.config.worker_id,
    }
    return worker.client.post("/runspecs/run", payload)


def runtime_job_id_from_enqueue(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    runtime_job = value.get("runtime_job")
    if isinstance(runtime_job, Mapping):
        return _optional_string(runtime_job.get("job_id"))
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the video editing toolkit as an external agentctl runtime worker.",
    )
    parser.add_argument("--base-url", help="agentctl base URL.")
    parser.add_argument("--token", help="Bearer token. Prefer VIDEO_TOOLKIT_AGENTCTL_TOKEN.")
    parser.add_argument("--worker-id", help="Worker id registered with agentctl.")
    parser.add_argument("--backend-id", help="Runtime backend id. Defaults to local.")
    parser.add_argument("--artifact-root", help="Local artifact store root for worker execution.")
    parser.add_argument("--artifact-base-url", help="Base URL used to fetch relative artifact download URLs.")
    parser.add_argument("--max-artifact-bytes", type=int, help="Maximum bytes per materialized input artifact.")
    parser.add_argument(
        "--allowed-resource-classes",
        help="Comma-separated resource classes this worker may execute. Defaults to cpu_light.",
    )
    parser.add_argument(
        "--allowed-capabilities",
        help="Comma-separated capability allowlist for this worker. Defaults to all known capabilities in allowed resource classes.",
    )
    parser.add_argument("--max-job-input-bytes", type=int, help="Maximum declared input bytes per job.")
    parser.add_argument("--max-run-timeout-seconds", type=int, help="Maximum route timeout this worker accepts.")
    parser.add_argument(
        "--execution-mode",
        choices=sorted(SUPPORTED_EXECUTION_BACKENDS),
        help="Compatibility alias for --execution-backend.",
    )
    parser.add_argument(
        "--execution-backend",
        choices=sorted(SUPPORTED_EXECUTION_BACKENDS),
        help="Execution backend. docker and remote are P0.14 registered but unavailable placeholders.",
    )
    parser.add_argument("--max-attempts", type=int, help="Maximum runtime job attempt accepted by this worker.")
    parser.add_argument("--capacity", type=int, help="Worker capacity for heartbeat.")
    parser.add_argument("--ttl-seconds", type=int, help="Worker heartbeat TTL.")
    parser.add_argument("--lease-seconds", type=int, help="Job lease duration.")
    parser.add_argument("--timeout-seconds", type=float, help="HTTP timeout.")
    parser.add_argument("--idle-sleep-seconds", type=float, help="Loop idle sleep.")
    parser.add_argument("--once", action="store_true", help="Run one heartbeat/lease/complete cycle.")
    parser.add_argument("--max-jobs", type=int, help="Run until this many jobs are processed, then stop.")
    parser.add_argument("--enqueue-probe", action="store_true", help="Enqueue a no-upload RunSpec probe before running.")
    parser.add_argument("--tenant-id", default="demo_tenant", help="Tenant for --enqueue-probe.")
    args = parser.parse_args(argv)

    config = VideoToolkitWorkerConfig.from_env(
        base_url=args.base_url,
        token=args.token,
        worker_id=args.worker_id,
        backend_id=args.backend_id,
        capacity=args.capacity,
        ttl_seconds=args.ttl_seconds,
        lease_seconds=args.lease_seconds,
        timeout_seconds=args.timeout_seconds,
        idle_sleep_seconds=args.idle_sleep_seconds,
        artifact_root=args.artifact_root,
        artifact_base_url=args.artifact_base_url,
        max_artifact_bytes=args.max_artifact_bytes,
        allowed_resource_classes=parse_csv_tuple(args.allowed_resource_classes)
        if args.allowed_resource_classes is not None
        else None,
        allowed_capabilities=parse_csv_tuple(args.allowed_capabilities)
        if args.allowed_capabilities is not None
        else None,
        max_job_input_bytes=args.max_job_input_bytes,
        max_run_timeout_seconds=args.max_run_timeout_seconds,
        execution_mode=args.execution_backend or args.execution_mode,
        max_attempts=args.max_attempts,
    )
    worker = VideoToolkitAgentctlWorker(config)
    enqueued: dict[str, Any] | None = None
    if args.enqueue_probe:
        enqueued = enqueue_probe_runspec(worker, tenant_id=args.tenant_id)

    if args.once or args.enqueue_probe:
        result = worker.run_once(expected_job_id=runtime_job_id_from_enqueue(enqueued))
    else:
        result = worker.run_loop(max_jobs=args.max_jobs)
    if enqueued is not None:
        result = {
            "schema": SCHEMA,
            "transport": "agentctl.runtime_worker",
            "ok": result.get("ok") is True,
            "status": result.get("status"),
            "enqueued": _summarize_enqueue(enqueued),
            "worker_run": result,
        }
    print(json.dumps(_caller_safe(result, token=config.token), ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


def _summarize_enqueue(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    runtime_job = value.get("runtime_job")
    if isinstance(runtime_job, Mapping):
        return {
            "runspec_id": value.get("runspec_id"),
            "status": value.get("status"),
            "dispatch_mode": value.get("dispatch_mode"),
            "runtime_job": {
                "job_id": runtime_job.get("job_id"),
                "backend_id": runtime_job.get("backend_id"),
                "backend_kind": runtime_job.get("backend_kind"),
                "status": runtime_job.get("status"),
                "target_agent": runtime_job.get("target_agent"),
            },
        }
    return value


def _summarize_worker(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    worker = value.get("worker")
    if isinstance(worker, Mapping):
        return {
            "worker_id": worker.get("worker_id"),
            "backend_id": worker.get("backend_id"),
            "backend_kind": worker.get("backend_kind"),
            "status": worker.get("status"),
            "alive": worker.get("alive"),
            "available_slots": worker.get("available_slots"),
        }
    return value


def _summarize_lease(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    job = value.get("job")
    return {
        "lease_id": value.get("lease_id"),
        "lease_seconds": value.get("lease_seconds"),
        "expired_leases_requeued": value.get("expired_leases_requeued"),
        "job": None
        if not isinstance(job, Mapping)
        else {
            "job_id": job.get("job_id"),
            "source": job.get("source"),
            "status": job.get("status"),
            "backend_id": job.get("backend_id"),
            "target_agent": job.get("target_agent"),
            "tenant": job.get("tenant"),
            "trace_id": job.get("trace_id"),
        },
    }


def _summarize_completion(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    job = value.get("job")
    if not isinstance(job, Mapping):
        return value
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "backend_id": job.get("backend_id"),
        "leased_by": job.get("leased_by"),
        "attempts": job.get("attempts"),
        "error": job.get("error"),
    }


def _worker_error_result(
    *,
    status: str,
    execution_mode: str,
    error_code: str,
    error_message: str,
    reason_code: str,
    started: float,
    attempt: int,
    max_attempts: int,
    trace_ref: str | None,
    extra_output: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    safe_message = _safe_error_message(error_message)
    usage_metrics = _worker_usage_metrics(
        {},
        started=started,
        policy=None,
        execution_mode=execution_mode,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    output: dict[str, Any] = {
        "schema": "video_editing_toolkit.agentctl_worker.error.v0",
        "ok": False,
        "error_code": error_code,
        "error_message": safe_message,
        "reason_code": reason_code,
        "execution_backend": execution_mode,
        "trace_ref": trace_ref,
        "usage_metrics": usage_metrics,
    }
    if extra_output:
        output.update(dict(extra_output))
    return {
        "status": status,
        "execution_mode": execution_mode,
        "execution_backend": execution_mode,
        "trace_ref": trace_ref,
        "usage_metrics": usage_metrics,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "output": output,
        "error": safe_message,
    }


def _worker_usage_metrics(
    local_result: Mapping[str, Any],
    *,
    started: float,
    policy: Any,
    execution_mode: str,
    attempt: int,
    max_attempts: int,
) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    processed = local_result.get("processed")
    if isinstance(processed, Mapping):
        processed_usage = processed.get("usage_metrics")
        if isinstance(processed_usage, Mapping):
            usage.update(dict(processed_usage))
    direct_usage = local_result.get("usage_metrics")
    if isinstance(direct_usage, Mapping):
        usage.update(dict(direct_usage))
    usage["worker_runtime_ms"] = round((perf_counter() - started) * 1000, 3)
    usage["execution_backend"] = execution_mode
    usage["attempt"] = attempt
    usage["max_attempts"] = max_attempts
    if policy is not None:
        usage["resource_class"] = policy.resource_class
        usage["declared_input_bytes"] = policy.declared_input_bytes
        usage["route_timeout_seconds"] = policy.route_timeout_seconds
    return usage


def _job_attempt(job: Mapping[str, Any]) -> int:
    value = job.get("attempts")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return 1
        return parsed if parsed > 0 else 1
    return 1


def _job_cancel_requested(job: Mapping[str, Any]) -> bool:
    if job.get("cancel_requested") is True:
        return True
    status = job.get("status")
    if isinstance(status, str) and status.lower() in {"cancelled", "cancel_requested", "cancelling"}:
        return True
    metadata = job.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("cancel_requested") is True:
        return True
    payload = job.get("payload")
    if isinstance(payload, Mapping) and payload.get("cancel_requested") is True:
        return True
    return False


def _trace_ref_from_job(job: Mapping[str, Any]) -> str | None:
    payload = job.get("payload")
    input_payload: Any = None
    if isinstance(payload, Mapping):
        input_payload = payload.get("input_payload")
    return (
        _optional_string(job.get("trace_id"))
        or (_optional_string(payload.get("trace_id")) if isinstance(payload, Mapping) else None)
        or (_optional_string(input_payload.get("trace_ref")) if isinstance(input_payload, Mapping) else None)
        or (_optional_string(input_payload.get("trace_id")) if isinstance(input_payload, Mapping) else None)
    )


def _trace_ref_from_agentctl_result(value: Mapping[str, Any]) -> str | None:
    processed = value.get("processed")
    if isinstance(processed, Mapping):
        trace_ref = _optional_string(processed.get("trace_ref"))
        if trace_ref:
            return trace_ref
    queued = value.get("queued")
    if isinstance(queued, Mapping):
        trace_ref = _optional_string(queued.get("trace_ref"))
        if trace_ref:
            return trace_ref
    return _optional_string(value.get("trace_ref"))


def _error_from_agentctl_result(value: Mapping[str, Any]) -> str:
    processed = value.get("processed")
    if isinstance(processed, Mapping):
        message = processed.get("error_message") or processed.get("error_code")
        if isinstance(message, str) and message:
            return message
    message = value.get("error_message") or value.get("error_code")
    return str(message or "video toolkit job failed")


def _safe_error_message(message: Any) -> str:
    rendered = str(message or "video toolkit job failed")
    if any(pattern.search(rendered) for pattern in LOCAL_DETAIL_PATTERNS):
        return "Worker failure details were redacted."
    if any(pattern.search(rendered) for pattern in URL_OR_SECRET_PATTERNS):
        return "Worker failure details were redacted."
    return rendered


def _execution_timeout_seconds(
    route_timeout_seconds: int | None,
    config: VideoToolkitWorkerConfig,
) -> int:
    values = [
        config.max_run_timeout_seconds,
        config.lease_seconds,
    ]
    if route_timeout_seconds is not None:
        values.append(route_timeout_seconds)
    return max(min(values), 1)


def _mapping_field(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    child = value.get(key)
    return dict(child) if isinstance(child, Mapping) else {}


def _required_string(value: Mapping[str, Any], key: str) -> str:
    child = value.get(key)
    if not isinstance(child, str) or not child:
        raise ValueError(f"{key} is required")
    return child


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _caller_safe(value: Any, *, token: str | None) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, child in value.items():
            key_string = str(key)
            normalized_key = key_string.lower()
            if normalized_key in FORBIDDEN_PUBLIC_KEYS:
                continue
            if any(part in normalized_key for part in ("token", "secret", "password", "api_key", "private_key")):
                safe[key_string] = "[redacted]"
            else:
                safe[key_string] = _caller_safe(child, token=token)
        return safe
    if isinstance(value, list):
        return [_caller_safe(child, token=token) for child in value]
    if isinstance(value, str):
        rendered = value.replace(token, "[redacted]") if token else value
        if any(pattern.search(rendered) for pattern in LOCAL_DETAIL_PATTERNS):
            return "[redacted]"
        if any(pattern.search(rendered) for pattern in URL_OR_SECRET_PATTERNS):
            return "[redacted]"
        return rendered
    return value


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


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
