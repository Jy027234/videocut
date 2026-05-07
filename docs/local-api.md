# Local HTTP API

P0.7 adds a minimal FastAPI surface for local development. FastAPI and uvicorn
remain optional and are available through the `api` extra only.

Install with API dependencies:

```powershell
py -m pip install -e ".[api,dev]"
```

Run the local API:

```powershell
video-toolkit-local-api --host 127.0.0.1 --port 8765
```

The API is process-local. It creates an in-memory `LocalRunService`, a local
artifact store, and the registered P0 adapter handlers inside the API process.

## App Factory

Tests and embedding code should use `create_app()`:

```python
from video_editing_toolkit.local_api import create_app

app = create_app(artifact_root=".video-toolkit-data/local-api-artifacts")
```

`create_app()` imports FastAPI lazily. Importing `video_editing_toolkit.local_api`
does not require FastAPI.

## Endpoints

```text
POST /local/toolkit-runs
GET  /local/toolkit-runs/{run_id}
GET  /local/artifacts/{artifact_id}
GET  /local/manifests
```

`POST /local/toolkit-runs` accepts an agentctl-like envelope:

```json
{
  "run_id": "run_optional",
  "tool_call_id": "tool_call_optional",
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.project_edit.create_project",
  "version": "0.1.0-p0",
  "input": {
    "project_id": "proj_local_api_demo"
  },
  "artifact_refs": [],
  "policy_context": {
    "tenant_id": "demo_tenant",
    "user_id": "demo_user",
    "share_id": null,
    "data_policy": {},
    "quota_policy": {}
  },
  "dry_run": false
}
```

By default the local API submits the run and synchronously processes one queue
item, so the POST response is usually the processed public `RunResponse`. The
same run remains queryable through `GET /local/toolkit-runs/{run_id}`.

`GET /local/artifacts/{artifact_id}` returns public artifact metadata that has
already appeared in a run response. It does not stream artifact bytes and does
not expose local filesystem paths or internal storage URIs.

`GET /local/manifests` returns toolkit manifest JSON payloads from the
configured manifests directory. Responses include manifest file names only, not
absolute paths.

## Caller Safety

Every route returns caller-safe JSON:

- no `storage_uri`
- no local filesystem paths
- no raw shell or FFmpeg commands
- no private key, token, password, or secret fields

Local artifact bytes stay inside `LocalArtifactStore`. Workers may resolve
artifact ids to private local paths internally, but HTTP callers only see
public artifact refs and metadata.
