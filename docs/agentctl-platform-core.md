# Agentctl And Platform Core Bridge

P0.6 adds a local command surface that lets agents submit one structured
toolkit capability without depending on Platform Core, network services, Redis,
or object storage. It is a compatibility rehearsal for the future agentctl
adapter boundary, not the final Platform Core implementation.

## Local Command

Use the module directly from a source checkout:

```powershell
$env:PYTHONPATH='src'
py -m video_editing_toolkit.agentctl --input-json '{"toolkit_id":"video-editing-toolkit","capability":"video.project_edit.create_project","input":{"project_id":"proj_agentctl_demo"}}'
```

After editable install:

```powershell
video-toolkit-agentctl --input-json '{"toolkit_id":"video-editing-toolkit","capability":"video.delivery.generate_variants","input":{"project_id":"proj_agentctl_demo","target":"web"}}'
```

The command also reads JSON from stdin:

```powershell
'{"toolkit_id":"video-editing-toolkit","capability":"video.delivery.generate_variants","input":{"project_id":"proj_agentctl_demo","target":"review"}}' |
  video-toolkit-agentctl --artifact-root .video-toolkit-data/agentctl-artifacts
```

`--artifact-root` is optional. It selects the local `LocalArtifactStore` root
for generated artifacts or pre-existing local artifact ids. The path is never
returned in public JSON.

## Request Envelope

The local bridge accepts this shape:

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "version": "0.1.0",
  "run_id": "optional caller-provided run id",
  "tool_call_id": "optional caller-provided tool call id",
  "input": {},
  "artifact_ids": [],
  "artifact_refs": [],
  "policy_context": {
    "tenant_id": "demo_tenant",
    "user_id": "demo_user",
    "share_id": null,
    "data_policy": {},
    "quota_policy": {}
  }
}
```

Only `toolkit_id`, `capability`, and `input` are expected for ordinary P0.6
runs. `artifact_ids` and `artifact_refs` are accepted for local handoff tests,
but P0.6 does not upload external files. Artifact-dependent media capabilities
can only read artifacts that already exist below the selected local artifact
store root. For no-upload structured capabilities such as
`video.project_edit.create_project` and `video.delivery.generate_variants`,
unreferenced top-level artifact refs are accepted as future handoff metadata but
are not resolved into worker paths.

## Execution Flow

The bridge performs the same in-process sequence every time:

```text
parse JSON envelope
create LocalArtifactStore
create LocalRunService
register_p0_adapter_handlers
submit_public
process_next_public
print caller-safe JSON
```

This keeps the P0.6 behavior close to the future agentctl shape while remaining
simple enough for local contract tests and parallel worker development.

## Response Envelope

Output is a caller-facing JSON object:

```json
{
  "schema": "video_editing_toolkit.agentctl.local_run.v0",
  "transport": "agentctl.local",
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "ok": true,
  "queued": {
    "status": "queued"
  },
  "processed": {
    "status": "succeeded",
    "output": {}
  }
}
```

`queued` is the result from `LocalRunService.submit_public()`. `processed` is
the result from `LocalRunService.process_next_public()`. `ok` is true only when
the processed run status is `succeeded`.

Unknown capabilities are still submitted to the local runtime and fail in a
stable, JSON-safe way:

```json
{
  "ok": false,
  "processed": {
    "status": "failed",
    "error_code": "handler_not_registered"
  }
}
```

## Public Safety Rules

The command output must be safe to show to agents and tests. It does not echo
the raw request and strips or redacts caller-unsafe fields such as:

- `storage_uri`
- local filesystem paths
- worker-only paths
- raw shell or FFmpeg commands
- `private_key`, `api_key`, `client_secret`, tokens, passwords, and secrets

Artifact references are exposed only through public artifact fields such as
`artifact_id`, type, checksum, size, retention metadata, and local public
download handles.

## Future Platform Core Mapping

| P0.6 local bridge | Future Platform Core responsibility |
| --- | --- |
| JSON stdin or `--input-json` | agentctl tool run request envelope |
| `LocalArtifactStore` root | object storage and artifact service |
| caller-safe artifact refs | Platform artifact handles |
| `LocalRunService.submit_public()` | Platform run submission |
| `process_next_public()` | worker queue execution and status updates |
| local stable failure JSON | Platform error reporting and retry policy |

The bridge intentionally avoids real Platform Core clients. When Platform Core
integration lands, the request and response shapes can stay close while storage,
authz, queueing, and trace propagation move behind the platform boundary.

## P0.9 Remote Agentctl Probe

P0.9 adds `video_editing_toolkit.agentctl_remote` and the
`video-toolkit-agentctl-remote` console entrypoint as an optional probe against a
real local agentctl Docker service. This is not a replacement for the local
bridge above; it verifies that the future control-plane boundary exists before
P1 capability work starts.

Default probe:

```powershell
$env:PYTHONPATH='src'
$env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765
```

Explicit pre-integration actions:

```powershell
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --validate-runspec
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --register
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --worker-smoke
```

The remote probe checks agentctl health, OpenAPI routes, tool catalog,
`/runspecs/validate`, and the runtime worker protocol. The registration payload
is derived from the P0 manifest and marks the execution model as
`external_video_toolkit_worker`.

P0.9 keeps heavy media work outside agentctl. The local Docker agentctl should
act as catalog, RunSpec, queue, and worker-protocol control plane; FFmpeg,
OpenCV, Whisper, TTS, and render workloads remain in standalone toolkit
workers.

## P0.15 Platform Core Handoff

P0.15 adds `video_editing_toolkit.platform_core` and the
`video-toolkit-platform-core` console entrypoint. This is an interface
reservation layer, not a live Platform Core client.

It provides three local contracts:

```text
1. platform_core_toolkit_descriptor.v0
   Manifest-backed descriptor for Tool Catalog import and product review.

2. platform_core_toolkit_run_request.v0
   Future Platform Core request normalized into the local agentctl envelope.

3. platform_core_toolkit_run_completion.v0
   Local agentctl/worker result normalized into Platform Core completion shape.
```

Descriptor smoke:

```powershell
$env:PYTHONPATH='src'
py -m video_editing_toolkit.platform_core --descriptor
```

Request normalization:

```json
{
  "platform_run_id": "platform_run_001",
  "platform_tool_call_id": "platform_tool_call_001",
  "platform_trace_id": "trace_platform_001",
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "tenant_id": "tenant_demo",
  "user_id": "user_demo",
  "input": {
    "project_id": "proj_platform"
  },
  "artifact_refs": [
    {
      "artifact_id": "artifact_platform_source",
      "artifact_type": "source_video",
      "owner_tenant_id": "tenant_demo",
      "mime_type": "video/mp4",
      "size_bytes": 123,
      "checksum": "sha256:...",
      "download_url": "/artifacts/download/artifact_platform_source"
    }
  ]
}
```

The normalized local envelope preserves:

```text
platform_run_id -> run_id
platform_tool_call_id -> tool_call_id
platform_trace_id / trace_id -> trace_ref
tenant_id / user_id -> policy_context
artifact_refs -> caller-safe artifact_ref handoff
```

Completion normalization preserves:

```text
run_id
tool_call_id
status
output
artifact_refs
usage_metrics
trace_ref
error_code / error_message
artifact_contract=artifact_ref_only
```

Safety rules:

```text
1. P0.15 does not store Platform Core tokens or provider keys.
2. P0.15 does not call Platform Core network APIs.
3. storage_uri remains internal-only and is not returned in handoff payloads.
4. Local paths, worker paths, argv, stderr, env, raw commands, and secret-like fields are stripped or redacted.
5. Artifact bytes still require the P0.11/P0.12 worker materialization contract and an authorized byte endpoint.
```
