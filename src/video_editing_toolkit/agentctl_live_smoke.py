"""Reusable live queue smoke for agentctl enqueue/lease/complete."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping, Sequence

from video_editing_toolkit.agentctl_remote import build_runspec_enqueue_payload
from video_editing_toolkit.agentctl_worker import (
    SCHEMA as WORKER_SCHEMA,
    VideoToolkitAgentctlWorker,
    VideoToolkitWorkerConfig,
    _caller_safe,
    runtime_job_id_from_enqueue,
)
from video_editing_toolkit.agentctl_worker_policy import parse_csv_tuple
from video_editing_toolkit.storage.materialize import ArtifactBytesFetcher


SCHEMA = "video_editing_toolkit.agentctl_live_smoke.queue.v0"


def run_agentctl_queue_smoke(
    *,
    config: VideoToolkitWorkerConfig,
    tenant_id: str = "demo_tenant",
    capability: str = "video.asset_ingest.build_asset_index",
    input_payload: Mapping[str, Any] | None = None,
    artifact_refs: Sequence[Mapping[str, Any]] = (),
    client: Any | None = None,
    artifact_fetcher: ArtifactBytesFetcher | None = None,
    local_runner: Any | None = None,
) -> dict[str, Any]:
    worker = VideoToolkitAgentctlWorker(
        config,
        client=client,
        artifact_fetcher=artifact_fetcher,
        local_runner=local_runner,
    )
    enqueue_payload = build_runspec_enqueue_payload(
        tenant_id=tenant_id,
        backend_id=config.backend_id,
        capability=capability,
        input_payload=input_payload,
        artifact_refs=artifact_refs,
    )
    enqueue_payload["metadata"] = {
        **dict(enqueue_payload.get("metadata") or {}),
        "queued_by": "video_editing_toolkit.agentctl_live_smoke",
        "worker_id": config.worker_id,
    }
    enqueued = worker.client.post("/runspecs/run", enqueue_payload)
    expected_job_id = runtime_job_id_from_enqueue(enqueued)
    worker_run = worker.run_once(expected_job_id=expected_job_id)
    result = {
        "schema": SCHEMA,
        "transport": "agentctl.queue_smoke",
        "ok": worker_run.get("ok") is True,
        "status": worker_run.get("status"),
        "control_plane": {
            "enqueue_path": "/runspecs/run",
            "dispatch_mode": "enqueue",
            "backend_id": config.backend_id,
            "expected_job_id": expected_job_id,
        },
        "artifact_download": {
            "artifact_base_url_configured": bool(config.artifact_base_url),
            "separate_artifact_credentials": bool(config.artifact_token and config.artifact_token != config.token),
            "artifact_ref_count": len(artifact_refs),
        },
        "enqueued": _summarize_enqueue(enqueued),
        "worker_run": worker_run,
        "worker_schema": WORKER_SCHEMA,
    }
    return _caller_safe(
        result,
        token=config.token,
        extra_tokens=(config.artifact_token,),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a real agentctl queue smoke: /runspecs/run enqueue, worker heartbeat/lease/execute/complete.",
    )
    parser.add_argument("--base-url", help="agentctl control-plane base URL.")
    parser.add_argument("--token", help="Bearer token for agentctl control-plane requests.")
    parser.add_argument("--artifact-base-url", help="Base URL used to download artifact bytes.")
    parser.add_argument("--artifact-token", help="Bearer token for artifact byte downloads.")
    parser.add_argument("--artifact-ref-json", required=True, help="JSON object or array of existing Platform Core artifact_refs.")
    parser.add_argument("--input-json", help="Toolkit input JSON. Defaults to artifact_ids inferred from artifact_refs.")
    parser.add_argument("--capability", default="video.asset_ingest.build_asset_index", help="Toolkit capability to execute.")
    parser.add_argument("--tenant-id", default="demo_tenant", help="Tenant id for the RunSpec.")
    parser.add_argument("--worker-id", help="Worker id registered with agentctl.")
    parser.add_argument("--backend-id", help="Runtime backend id. Defaults to local.")
    parser.add_argument("--artifact-root", help="Local artifact store root for worker execution.")
    parser.add_argument("--timeout-seconds", type=float, help="HTTP timeout.")
    parser.add_argument("--lease-seconds", type=int, help="Job lease duration.")
    parser.add_argument("--ttl-seconds", type=int, help="Worker heartbeat TTL.")
    parser.add_argument("--max-artifact-bytes", type=int, help="Maximum bytes per materialized input artifact.")
    parser.add_argument("--max-job-input-bytes", type=int, help="Maximum declared input bytes per job.")
    parser.add_argument("--max-run-timeout-seconds", type=int, help="Maximum route timeout this worker accepts.")
    parser.add_argument("--allowed-resource-classes", help="Comma-separated worker resource classes.")
    parser.add_argument("--allowed-capabilities", help="Comma-separated capability allowlist.")
    args = parser.parse_args(argv)

    artifact_refs = _artifact_refs_from_json(args.artifact_ref_json)
    input_payload = _input_from_args(args.input_json, artifact_refs=artifact_refs)
    config = VideoToolkitWorkerConfig.from_env(
        base_url=args.base_url,
        token=args.token,
        worker_id=args.worker_id,
        backend_id=args.backend_id,
        artifact_root=args.artifact_root,
        artifact_base_url=args.artifact_base_url,
        artifact_token=args.artifact_token,
        timeout_seconds=args.timeout_seconds,
        lease_seconds=args.lease_seconds,
        ttl_seconds=args.ttl_seconds,
        max_artifact_bytes=args.max_artifact_bytes,
        max_job_input_bytes=args.max_job_input_bytes,
        max_run_timeout_seconds=args.max_run_timeout_seconds,
        allowed_resource_classes=parse_csv_tuple(args.allowed_resource_classes)
        if args.allowed_resource_classes is not None
        else None,
        allowed_capabilities=parse_csv_tuple(args.allowed_capabilities)
        if args.allowed_capabilities is not None
        else None,
    )
    report = run_agentctl_queue_smoke(
        config=config,
        tenant_id=args.tenant_id,
        capability=args.capability,
        input_payload=input_payload,
        artifact_refs=artifact_refs,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("ok") else 2


def _artifact_refs_from_json(raw: str) -> tuple[Mapping[str, Any], ...]:
    payload = json.loads(raw)
    if isinstance(payload, Mapping):
        return (dict(payload),)
    if isinstance(payload, list) and all(isinstance(item, Mapping) for item in payload):
        return tuple(dict(item) for item in payload)
    raise ValueError("--artifact-ref-json must be a JSON object or array of objects")


def _input_from_args(raw: str | None, *, artifact_refs: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if raw:
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise ValueError("--input-json must be a JSON object")
        return dict(payload)
    artifact_ids = [
        str(ref.get("artifact_id") or ref.get("ref"))
        for ref in artifact_refs
        if isinstance(ref.get("artifact_id") or ref.get("ref"), str)
    ]
    return {
        "project_id": "proj_agentctl_queue_smoke",
        "artifact_ids": artifact_ids,
    }


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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
