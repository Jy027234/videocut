# Agentctl Docker Pre-Integration

Date: 2026-05-07

Status: P0.9 control-plane pre-integration. This verifies that the independent
video toolkit can be discovered by a local agentctl Docker deployment without
moving media workloads into the agentctl container.

## Decision

Based on product performance risk, keep the video toolkit as a standalone
worker/service. Use agentctl as the control plane for catalog registration,
RunSpec shape validation, runtime worker protocol discovery, queue dispatch, and
trace handoff.

Do not run FFmpeg, OpenCV, Whisper, TTS, scene detection, or rendering inside
the agentctl control-plane container.

## Local Probe

Set a local dev token through the environment. Do not commit the token.

```powershell
$env:PYTHONPATH='src'
$env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'

py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765
```

The default probe is read-oriented. It checks:

```text
GET /healthz
GET /openapi.json
GET /tool-catalog
GET /runtime/backends
GET /runtime/backends/workers/protocol
GET /runtime/backends/jobs
```

The probe also builds, but does not submit, a manifest-backed
`/tool-catalog/register` payload.

## RunSpec Validation

Validate the no-upload execution envelope without queueing or running media
work:

```powershell
py -m video_editing_toolkit.agentctl_remote `
  --base-url http://127.0.0.1:8765 `
  --validate-runspec
```

The validation payload is a `RunSpecDraft` whose `input_payload` contains the
same agentctl-like video toolkit envelope used by the local bridge:

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "input": {
    "project_id": "proj_agentctl_remote_probe"
  },
  "artifact_refs": [],
  "policy_context": {
    "tenant_id": "demo_tenant"
  }
}
```

P0.9 validates only a no-upload capability. Artifact-dependent media runs must
wait for the external worker and artifact service boundary.

## Tool Catalog Registration

Register the P0 manifest as a draft tool catalog entry only when explicitly
requested:

```powershell
py -m video_editing_toolkit.agentctl_remote `
  --base-url http://127.0.0.1:8765 `
  --register
```

The registration payload is derived from
`manifests/video-editing-toolkit.p0.manifest.json` and includes:

```text
tool_id: video-editing-toolkit
display_name: Video Editing Toolkit
tool_schema: toolkit_id + capability enum + input + artifact_refs + policy_context
required_scopes: toolkit.video_editing.p0
side_effects: artifact:read, artifact:write, trace:write, render:cpu
metadata.execution_model: external_video_toolkit_worker
metadata.preferred_agentctl_path: /runtime/backends/workers/protocol
```

Local dev catalog registration proves the call path and shape. It is not a
production persistence, rollout, or authorization guarantee.

## Worker Smoke

The worker smoke is also explicit:

```powershell
py -m video_editing_toolkit.agentctl_remote `
  --base-url http://127.0.0.1:8765 `
  --worker-smoke
```

It sends a short heartbeat and an idle lease probe:

```text
POST /runtime/backends/workers/heartbeat
POST /runtime/backends/jobs/lease
```

This does not execute video tasks. It only confirms the future external worker
protocol can handshake with agentctl.

## Current Local Result

Observed against local Docker `agentctl:full` on 2026-05-07:

```text
agentctl API: 0.2.0b2
health: ok
route count: 356
runtime worker protocol: 0.1.0
ready backend: local
docker backend: disabled
jobs: 0
RunSpec validate: valid
worker heartbeat/idle lease: ok
tool catalog draft registration: accepted
```

Performance decision:

```text
connect_now: true
promote_to_p1: false
deployment_model: standalone_video_toolkit_worker
agentctl_role: catalog_and_runtime_dispatch_boundary
run_heavy_media_inside_agentctl: false
```

## P1 Readiness Dependencies

Do not promote from P0.9 to P1 until:

```text
1. A standalone video toolkit worker implements agentctl worker heartbeat, lease, execute, and complete.
2. Artifact refs come from Platform Core or a compatible artifact service, not local paths.
3. Queue execution uses enqueue/worker dispatch, not in-process agentctl execution.
4. Production authz, scopes, approval context, trace, retries, cancellation, and resource quotas are explicit.
5. Docker or remote worker backend is enabled for isolated heavy media work.
```
