# Agentctl Runtime Worker

Date: 2026-05-07

Status: P0.14 external worker loop plus controlled artifact materialization,
resource-policy preflight, optional subprocess execution, and worker lifecycle
control scaffolding for the video editing toolkit.

## Purpose

P0.10 turns the P0.9 control-plane probe into a minimal executable runtime
boundary:

```text
agentctl /runspecs/run dispatch_mode=enqueue
  -> runtime job queued
  -> video-toolkit-agentctl-worker heartbeat
  -> lease one job
  -> execute the toolkit envelope locally
  -> complete the job in agentctl
```

This still does not make agentctl run media workloads in-process. The worker is
the execution boundary.

## Command

Run one external worker cycle:

```powershell
$env:PYTHONPATH='src'
$env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'

py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --worker-id video-toolkit-worker-1 `
  --backend-id local `
  --artifact-base-url http://127.0.0.1:8765 `
  --allowed-resource-classes cpu_light `
  --max-job-input-bytes 536870912 `
  --max-run-timeout-seconds 120 `
  --execution-backend subprocess `
  --max-attempts 2 `
  --once
```

Enqueue and consume a no-upload probe job:

```powershell
py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --worker-id video-toolkit-worker-1 `
  --backend-id local `
  --enqueue-probe
```

The `--enqueue-probe` command submits a `RunSpecDraft` with
`dispatch_mode=enqueue` and `input_payload`:

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "input": {
    "project_id": "proj_agentctl_remote_probe"
  },
  "artifact_refs": []
}
```

For safety, `--enqueue-probe` records the returned runtime `job_id` and only
completes that exact job. If the worker leases a different queued job on the
same backend, it returns `unexpected_job_leased` and does not call
`/complete`.

Artifact-dependent jobs can use the same worker path when the leased toolkit
envelope contains caller-safe `artifact_refs` with controlled `download_url`
values:

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.asset_ingest.build_asset_index",
  "input": {
    "project_id": "proj_materialized",
    "artifact_ids": ["artifact_platform_video"]
  },
  "artifact_refs": [
    {
      "artifact_id": "artifact_platform_video",
      "artifact_type": "source_video",
      "owner_tenant_id": "tenant_demo",
      "mime_type": "video/mp4",
      "size_bytes": 12345,
      "checksum": "sha256:...",
      "download_url": "/artifacts/download/artifact_platform_video"
    }
  ]
}
```

The worker resolves relative `download_url` values against
`--artifact-base-url` or `VIDEO_TOOLKIT_ARTIFACT_BASE_URL`. When not set
explicitly, it defaults to the configured agentctl `--base-url`.

## Worker Contract

The worker sends:

```text
POST /runtime/backends/workers/heartbeat
POST /runtime/backends/jobs/lease
POST /runtime/backends/jobs/{job_id}/complete
```

A leased job must contain either:

```text
job.payload.input_payload.toolkit_id
job.payload.input_payload.capability
job.payload.input_payload.input
```

or a direct toolkit envelope under `job.payload`.

The worker sets `run_id` to the runtime `job_id` and `tool_call_id` to the
runtime `lease_id` when the caller did not provide them. This keeps local
toolkit results traceable back to agentctl runtime jobs.

Before materialization and local execution, P0.12 checks worker execution
policy:

```text
1. capability must be registered in CAPABILITY_ROUTES.
2. Optional allowed_capabilities must include the capability.
3. The route resource_class must be enabled for this worker.
4. Declared artifact size_bytes must fit route and worker max input limits.
5. Route timeout_seconds must fit worker max_run_timeout_seconds.
6. Fail with video_toolkit_worker.execution_policy_rejected without downloading bytes or exposing local details.
```

The default external worker accepts only `cpu_light` routes. CPU-heavy,
GPU-optional, and future GPU-required routes require explicit worker startup
configuration:

```powershell
py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --allowed-resource-classes cpu_light,cpu_heavy `
  --max-run-timeout-seconds 900 `
  --once
```

Then P0.11/P0.12 materializes selected input artifact refs into
`LocalArtifactStore`:

```text
1. Preserve the Platform artifact_id after validating it as a safe local id.
2. Allow only relative download URLs or absolute URLs with the same origin as artifact_base_url.
3. Ignore storage_uri as a download source.
4. Send the worker bearer token only as an Authorization header to the allowed artifact endpoint.
5. Enforce max_artifact_bytes before storing the input.
6. Verify size_bytes and sha256 when provided.
7. Fail with video_toolkit_worker.artifact_materialization_failed without returning local paths, storage_uri, download URLs, or tokens.
```

P0.13 adds local execution modes:

```text
in_process
  Default compatibility mode.
  Calls run_agentctl() in the worker process.

subprocess
  Starts sys.executable -m video_editing_toolkit.agentctl with shell=False.
  Sends the toolkit envelope over stdin.
  Passes only --artifact-root as an argv parameter.
  Applies a worker-computed timeout based on route timeout, lease duration, and max_run_timeout_seconds.
  Normalizes timeout as video_toolkit_worker.execution_timeout.
  Does not return argv, stderr, environment, token, or local paths to callers.
```

P0.14 adds execution lifecycle scaffolding:

```text
execution_backend
  Registered values: in_process, subprocess, docker, remote.
  in_process and subprocess are executable in P0.14.
  docker and remote return stable video_toolkit_worker.execution_backend_unavailable until pool adapters exist.

attempt policy
  Worker heartbeat advertises max_attempts and retry_policy.
  Jobs whose current attempts value exceeds max_attempts are rejected before materialization or local execution.
  P0.14 does not implement automatic retry scheduling.

cancel contract
  Leased jobs marked cancel_requested/cancelled/cancelling are skipped before materialization or local execution.
  The worker completes them as failed with video_toolkit_worker.execution_cancelled and reason worker.cancel_requested.
  This is a pre-execution guard, not an in-flight media kill API.

trace and usage
  agentctl job trace_id is passed into the local toolkit envelope as trace_ref.
  Worker completion metadata carries trace_ref, usage_metrics, execution_backend, attempt, and max_attempts.
  Local runtime still records runtime_ms and adapter resource metadata when a toolkit run executes.
```

## Current Local Result

Observed against local Docker `agentctl:full` on 2026-05-07:

```text
/runspecs/run dispatch_mode=enqueue -> queued
/runtime/backends/jobs/lease -> leased
video.project_edit.create_project -> succeeded
/runtime/backends/jobs/{job_id}/complete -> completed
```

The completed result included:

```text
run_id: agentctl runtime job id
tool_call_id: agentctl lease id
status: completed
capability: video.project_edit.create_project
```

Local P0.11 contract tests also cover a fake Platform Core artifact endpoint
for `video.asset_ingest.build_asset_index`; no live byte-service smoke is
claimed yet because the current local API artifact endpoint is metadata-only.

## Guardrails

P0.11 proves worker protocol execution plus controlled local materialization of
input artifact refs. P0.12 adds route-aware worker policy, but it is still a
preflight guard. P0.13 subprocess mode gives the local worker a process boundary
and timeout kill point. P0.14 adds execution-backend registration, attempt
preflight, pre-execution cancel handling, and trace/usage completion metadata.
These are still not a full CPU/GPU/memory sandbox or production retry/cancel
system. Use artifact-dependent jobs only when the upstream artifact service
provides a byte endpoint compatible with this contract and the worker has
appropriate CPU/GPU resource isolation.

Do not use this loop for high-cost FFmpeg/OpenCV/Whisper or render production
jobs until:

```text
1. A Docker or remote backend is enabled for isolated heavy media execution.
2. Cancellation, retries, and trace propagation are explicit.
3. High-sensitivity capabilities have approval_context and policy checks.
4. Artifact service authz, expiry, retention, and tenant checks are enforced upstream.
```

Live smoke warning:

```text
The local agentctl backend queue is shared by backend_id. A generic worker can
lease any queued job on that backend. Use --enqueue-probe for targeted smoke
because it refuses to complete a job whose id differs from the probe job.
```
