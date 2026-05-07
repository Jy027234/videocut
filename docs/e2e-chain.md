# P0.5 Local Chain

The P0.5 demo is a local, dependency-light rehearsal of the future Platform
Core / agentctl orchestration path. It does not expose raw commands, worker
addresses, or local filesystem paths.

## Run

From the repository root:

```powershell
$env:PYTHONPATH='src'
py -m video_editing_toolkit.demo
```

Or after editable install:

```powershell
video-toolkit-demo
```

## Chain

```text
upload_artifact
probe_media
build_asset_index
create_project
apply_timeline_patch
render_preview
create_delivery_manifest
```

`upload_artifact` is local setup through `LocalArtifactStore`. It prints only
`ArtifactRef.to_public_dict()` output. All capability steps use
`LocalRunService.submit_public()` followed by
`LocalRunService.process_next_public()`.

## Platform Core / agentctl Mapping

| Local demo step | Future responsibility |
| --- | --- |
| `upload_artifact` | Platform Core artifact upload returns a caller-safe artifact ref. |
| `submit_public` | agentctl submits a structured tool run. |
| `process_next_public` | Worker queue consumes and executes the capability. |
| `artifact_refs` | Platform artifact handles replace local storage details. |
| `trace_ref` | Platform trace/run id links the chain across services. |

## Graceful Failure Contract

The chain is tolerant of route-complete stages whose heavier worker path is not
available yet. Those stages return `failed` with stable adapter errors such as
`adapter.unavailable` or `adapter.not_implemented`, and later steps can still be
submitted when their inputs are already available.

The demo uses `video.project_edit.render_preview`, which returns a lightweight
preview artifact ref marker. The heavier `video.render.render_preview` worker
route is registered separately and may still return `adapter.unavailable` or
`adapter.not_implemented` depending on local dependencies and implementation
state.

The final `create_delivery_manifest` step produces a caller-safe
`delivery_manifest` JSON artifact. It is a manifest handoff contract, not a
final media package.

## Public Output Boundary

The JSON output is safe for docs and agent-flow demos:

- artifact references include ids, types, checksums, sizes, and public download
  handles;
- run responses include status, output, usage metrics, trace refs, and stable
  errors;
- local artifact-store paths and worker-resolved paths remain private.
