# Runtime API

P0 provides a local Python runtime surface that mirrors the future agentctl
adapter shape without requiring Platform Core, agentctl, Redis, or object
storage.

## Run Request

`RunRequest` fields:

- `run_id`
- `tool_call_id`
- `toolkit_id`
- `capability`
- `version`
- `input`
- `artifact_refs`
- `policy_context`
- `dry_run`

`policy_context` keeps demo defaults for local development but preserves the
future authorization shape:

- `tenant_id`
- `user_id`
- `share_id`
- `data_policy`
- `quota_policy`

## Run Response

Internal `RunResponse` fields:

- `run_id`
- `tool_call_id`
- `status`: `queued`, `running`, `succeeded`, `failed`, or `cancelled`
- `output`
- `artifact_refs`
- `usage_metrics`
- `trace_ref`
- `error_code`
- `error_message`

Caller-facing code should serialize responses with
`RunResponse.to_public_dict()`. The public payload keeps the same top-level
shape but converts enum and datetime values to JSON-safe values and serializes
artifact references with `ArtifactRef.to_public_dict()`.

## Artifact Ref

`ArtifactRef` is the artifact object used inside the local runtime. Local
filesystem paths are kept inside `LocalArtifactStore` and are not exposed in
public responses.

Internal fields:

- `artifact_id`
- `artifact_type`
- `owner_tenant_id`
- `created_by_run_id`
- `storage_uri`
- `mime_type`
- `size_bytes`
- `checksum`
- `data_class`
- `retention_policy`
- `expires_at`
- `access_policy`
- `download_url`

`storage_uri` is internal-only and is omitted by
`ArtifactRef.to_public_dict()`. Public artifact refs include:

- `artifact_id`
- `artifact_type`
- `mime_type`
- `size_bytes`
- `checksum`
- `data_class`
- `retention_policy`
- `expires_at`
- `access_policy`
- `download_url` when available

## Local Queue

`InMemoryLocalQueue` is a process-local FIFO queue keyed by `run_id`.

Core methods:

- `enqueue(run_id)`
- `dequeue()`
- `cancel(run_id)`
- `clear_cancelled(run_id)`

## Local Artifact Store

`LocalArtifactStore` writes files below a configured local root directory and
returns controlled artifact references.

Core methods:

- `put_bytes(...) -> ArtifactRef`
- `put_file(...) -> ArtifactRef`
- `open_local_path(artifact_id) -> Path | None`
- `delete(artifact_id) -> bool`

`open_local_path` is intentionally retained for local workers that need to read
artifact bytes from disk. It is not part of the caller-facing response contract.

## Local Run Service

`LocalRunService` coordinates the P0 run lifecycle.

Core methods:

- `register_handler(toolkit_id, capability, handler)`
- `submit(request) -> RunResponse`
- `status(run_id) -> RunResponse | None`
- `cancel(run_id) -> RunResponse | None`
- `cleanup(run_id, delete_artifacts=False) -> bool`
- `process_next() -> RunResponse | None`
- `process(run_id) -> RunResponse | None`

Public serialization helpers:

- `submit_public(request) -> dict`
- `status_public(run_id) -> dict | None`
- `cancel_public(run_id) -> dict | None`
- `process_next_public() -> dict | None`
- `process_public(run_id) -> dict | None`

These helpers return `RunResponse.to_public_dict()` payloads and do not expose
`storage_uri` or local filesystem paths from `Path` values.

## P0.7 Local HTTP API

`video_editing_toolkit.local_api` exposes the section 9 local runtime endpoints
through FastAPI:

```text
POST /local/toolkit-runs
GET  /local/toolkit-runs/{run_id}
GET  /local/artifacts/{artifact_id}
GET  /local/manifests
```

FastAPI is an optional dependency under the `api` extra. The module provides
`create_app()` for tests and embedding; FastAPI is imported lazily inside that
factory so default runtime imports do not require API dependencies.

`POST /local/toolkit-runs` accepts the agentctl-like envelope used by the P0.6
bridge, creates a `RunRequest`, calls `submit_public()`, then synchronously
processes one local queue item by default. The response and later status query
are public `RunResponse` dictionaries.

`GET /local/artifacts/{artifact_id}` returns only public artifact metadata that
has already appeared in a run response. It does not return bytes,
`storage_uri`, local filesystem paths, or worker-only references.

See `docs/local-api.md` for the endpoint contract and local server command.

## P0.6 Local Agentctl Bridge

`video_editing_toolkit.agentctl` provides a lightweight local command entry
that mirrors the future agentctl run envelope without importing Platform Core
or making network calls.

Input is a JSON object supplied with `--input-json` or on stdin:

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "input": {
    "project_id": "proj_agentctl_demo"
  },
  "artifact_ids": [],
  "artifact_refs": []
}
```

The command creates `LocalArtifactStore`, `LocalRunService`, registers all P0
adapter handlers with `register_p0_adapter_handlers()`, calls
`submit_public()`, then calls `process_next_public()` once.

Example:

```powershell
$env:PYTHONPATH='src'
'{"toolkit_id":"video-editing-toolkit","capability":"video.delivery.generate_variants","input":{"project_id":"proj_demo","target":"web"}}' |
  py -m video_editing_toolkit.agentctl --artifact-root .video-toolkit-data/agentctl-artifacts
```

Output is a caller-safe envelope:

```json
{
  "schema": "video_editing_toolkit.agentctl.local_run.v0",
  "transport": "agentctl.local",
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "ok": true,
  "queued": {},
  "processed": {}
}
```

`queued` and `processed` are the same public dictionaries returned by the
runtime service. The bridge never returns the raw request, local artifact root,
`storage_uri`, worker paths, raw commands, or private key fields. Unknown
capabilities are submitted through the same local service and return a stable
failed `processed` response with `error_code: "handler_not_registered"`.

P0.6 does not upload external files. Artifact ids or caller-safe artifact refs
may be included for structured handoff testing, but media-reading capabilities
still require the referenced artifact to already exist in the configured local
artifact store. For no-upload capabilities such as
`video.project_edit.create_project` and `video.delivery.generate_variants`,
unreferenced top-level artifact refs are accepted by the bridge but are not
resolved into worker paths.

## P0.5 Local Chain

`video_editing_toolkit.demo` exercises the runtime as a local stand-in for the
future Platform Core / agentctl path. The demo uploads a tiny artifact into
`LocalArtifactStore`, then uses public service methods for every capability
step:

- `video.asset_ingest.probe_media`
- `video.asset_ingest.build_asset_index`
- `video.project_edit.create_project`
- `video.project_edit.apply_timeline_patch`
- `video.project_edit.render_preview`
- `video.delivery.create_delivery_manifest`

The upload step is local setup, equivalent to a future Platform Core artifact
upload. Every worker step is submitted with `submit_public()` and advanced with
`process_next_public()`. The output is intentionally caller-facing: it includes
run ids, statuses, capability names, artifact refs, project ids, version ids,
usage metrics, and stable errors, while keeping worker-only paths private.

Some P0.5 capabilities can be route-complete before their heavier worker path is
complete. When that happens, the runtime still returns a graceful public
response with a stable error such as `adapter.not_implemented` or
`adapter.unavailable`. The demo contract allows those failures without exposing
private worker details.

Handlers use this local signature:

```python
def handler(request: RunRequest, artifact_store: LocalArtifactStore) -> dict:
    return {
        "output": {},
        "artifact_refs": [],
        "usage_metrics": {},
    }
```

The service converts handler dictionaries into `RunResponse` objects and records
`runtime_ms` in `usage_metrics`.
