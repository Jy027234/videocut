# Video Editing Toolkit

Independent P0 development scaffold for the agent-assisted video editing toolkit.

This project is designed to run outside Platform Core, Studio, and the main API servers. It exposes local development contracts that can later be replaced by Platform Core Tool Catalog manifests and agentctl Tool Adapters.

## P0 Scope

```text
manifest/schema drafts
local toolkit run lifecycle
artifact_ref and local artifact store
queue and status tracking
adapter contracts for FFmpeg, PySceneDetect, OpenCV, Whisper
timeline patch validation foundation
QA/release gate fixtures
```

## Runtime Boundary

```text
Studio / Platform Core -> agentctl -> queue -> video-editing-toolkit worker -> artifact store
```

The toolkit must not expose raw shell commands, raw FFmpeg commands, internal worker addresses, or local filesystem paths to agents or callers.

## Development Commands

Run tests:

```powershell
py -m pytest tests
```

Run the local P0.5 chain demo without installing the package:

```powershell
$env:PYTHONPATH='src'
py -m video_editing_toolkit.demo
```

Or install in editable mode first:

```powershell
py -m pip install -e ".[dev]"
video-toolkit-demo
```

Run one structured capability through the P0.6 local agentctl bridge:

```powershell
$request = @{
  toolkit_id = "video-editing-toolkit"
  capability = "video.project_edit.create_project"
  input = @{ project_id = "proj_agentctl_demo" }
} | ConvertTo-Json -Depth 8 -Compress

$env:PYTHONPATH='src'
py -m video_editing_toolkit.agentctl --input-json $request
```

After editable install, the equivalent script entry is:

```powershell
video-toolkit-agentctl --input-json $request
```

The bridge also accepts JSON on stdin and an optional local artifact store root:

```powershell
$request | video-toolkit-agentctl --artifact-root .video-toolkit-data/agentctl-artifacts
```

P0.6 is intentionally local-only: it creates `LocalRunService`,
`LocalArtifactStore`, and the registered P0 adapter handlers in-process, then
submits and processes one run. It is best suited for structured capabilities
that do not require a fresh external file upload, such as
`video.project_edit.create_project` and `video.delivery.generate_variants`.

Run the P0.7 local HTTP API with optional API dependencies:

```powershell
py -m pip install -e ".[api,dev]"
video-toolkit-local-api --host 127.0.0.1 --port 8765
```

The local HTTP API provides:

```text
POST /local/toolkit-runs
GET  /local/toolkit-runs/{run_id}
GET  /local/artifacts/{artifact_id}
GET  /local/manifests
```

`POST /local/toolkit-runs` accepts the same agentctl-like envelope shape, submits
the run, and synchronously processes one queue item by default. HTTP responses
use caller-safe public runtime payloads: artifact ids and public metadata are
visible, while local paths, `storage_uri`, raw commands, and private key fields
are not returned. See `docs/local-api.md` for details.

The demo creates a tiny local artifact, uploads it into the local artifact store, then executes the public runtime chain:

```text
upload_artifact -> probe_media -> build_asset_index -> create_project -> apply_timeline_patch -> render_preview
  -> create_delivery_manifest
```

All run output is produced with `LocalRunService.submit_public()` and `LocalRunService.process_next_public()`. Public payloads expose `artifact_id`, project ids, version ids, run ids, and stable error codes, but not local filesystem paths.

On a host without media dependencies, execution tests skip real worker paths or return stable `adapter.unavailable` results while still exercising asset indexing, project creation, timeline patching, and preview contracts. Route-complete but worker-incomplete capabilities may return `adapter.not_implemented`; the chain is designed so docs and agent flows can keep exercising the future Platform Core shape. In Docker, the default worker runs real `ffprobe`, `extract_audio`, `extract_frames`, `normalize_asset`, and FFmpeg render flows; the `analysis` profile runs real PySceneDetect/OpenCV scene and visual-analysis flows; the `speech` profile provides the isolated Whisper/model boundary while keeping model execution disabled by default.

See `docs/e2e-chain.md` for the local chain contract and how it maps to future Platform Core / agentctl orchestration.
See `docs/agentctl-platform-core.md` for the P0.6 bridge envelope and future
Platform Core call shape.
See `docs/agentctl-docker-preintegration.md` for the P0.9 local Docker
agentctl probe, tool-catalog draft registration, and RunSpec validation path.
See `docs/release-gate.md` for the P0.9 gate, including current blockers
and explicit non-blockers such as the full timeline compositor, formal Platform
Core authz, and persistent queues.

Run the optional P0.9 remote agentctl probe against a local Docker agentctl:

```powershell
$env:PYTHONPATH='src'
$env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --validate-runspec
```

Registration and worker handshake are explicit:

```powershell
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --register
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --worker-smoke
```

P0.9 keeps FFmpeg/OpenCV/Whisper/rendering in the independent toolkit worker;
agentctl is used as catalog and runtime-dispatch control plane only.

Run the P0.10-P0.14 external worker once, or enqueue and consume a no-upload probe:

```powershell
py -m video_editing_toolkit.agentctl_worker --base-url http://127.0.0.1:8765 --once
py -m video_editing_toolkit.agentctl_worker --base-url http://127.0.0.1:8765 --enqueue-probe
```

P0.11 adds worker-side artifact materialization for queued artifact-dependent
jobs. When a leased job contains caller-safe `artifact_refs` with controlled
relative `download_url` values, the worker downloads bytes from the configured
artifact service, verifies `size_bytes` and `sha256`, stores them under the
same safe `artifact_id`, then runs the local adapter path:

```powershell
py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --artifact-base-url http://127.0.0.1:8765 `
  --max-artifact-bytes 536870912 `
  --once
```

P0.12 adds route-aware worker policy before any artifact bytes are downloaded.
The default worker accepts only `cpu_light` routes; heavier routes must be
enabled explicitly:

```powershell
py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --allowed-resource-classes cpu_light,cpu_heavy `
  --allowed-capabilities video.asset_ingest.probe_media,video.asset_ingest.normalize_asset `
  --max-job-input-bytes 4294967296 `
  --max-run-timeout-seconds 900 `
  --once
```

P0.13 adds an optional subprocess execution mode. The default stays
`in_process`; `subprocess` gives local development a separate Python process
and timeout kill point while keeping the toolkit envelope on stdin:

```powershell
py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --execution-mode subprocess `
  --max-run-timeout-seconds 120 `
  --once
```

P0.14 registers the execution-backend shape for later isolated pools, while
keeping `docker` and `remote` as stable unavailable placeholders until real
pool adapters exist. It also carries trace/usage metadata through worker
completion, adds an attempt preflight policy, and exposes local queued-run
cancellation in the development API:

```powershell
py -m video_editing_toolkit.agentctl_worker `
  --base-url http://127.0.0.1:8765 `
  --execution-backend subprocess `
  --max-attempts 2 `
  --once
```

See `docs/agentctl-runtime-worker.md` for the worker heartbeat/lease/complete
contract.

Generate the P0.15 Platform Core handoff descriptor, or normalize a future
Platform Core run request into the local agentctl envelope:

```powershell
py -m video_editing_toolkit.platform_core --descriptor

$request = @{
  platform_run_id = "platform_run_demo"
  platform_trace_id = "trace_platform_demo"
  toolkit_id = "video-editing-toolkit"
  capability = "video.project_edit.create_project"
  input = @{ project_id = "proj_platform_demo" }
} | ConvertTo-Json -Depth 8 -Compress

py -m video_editing_toolkit.platform_core --input-json $request
```

P0.15 is still interface reservation only: it does not call a live Platform
Core service, upload bytes, or bypass Platform Core authorization.

Generate P1.7/P1.8 Platform Core rehearsal payloads and the P1.8 explicit
local loop runner preview:

```powershell
py -m video_editing_toolkit.platform_core --manifest-registration-dry-run
py -m video_editing_toolkit.platform_core --local-loop-package
py -m video_editing_toolkit.platform_core_loop
```

These payloads preserve P1 disabled capability status and preview the future
Platform Core + agentctl + external worker loop without registering tools,
enqueueing jobs, downloading artifacts, publishing releases, or modifying the
Platform Core repository.

Only the explicit runner opt-in performs local enqueue/lease/complete calls:

```powershell
py -m video_editing_toolkit.platform_core_loop `
  --base-url http://127.0.0.1:8765 `
  --artifact-base-url http://127.0.0.1:8010 `
  --execute-local-loop
```

## Docker Worker

Build and run the local worker image:

```powershell
docker compose build
docker compose run --rm toolkit
```

Check FFmpeg inside the container:

```powershell
docker compose run --rm toolkit ffmpeg -version
docker compose run --rm toolkit ffprobe -version
```

Run the demo in Docker:

```powershell
docker compose run --rm toolkit video-toolkit-demo
```

The host machine may not have `ffmpeg`, `ffprobe`, PySceneDetect, OpenCV, or Whisper dependencies; Docker is the intended P0.4 media worker environment.
See `docs/docker.md` for the default worker plus dedicated `cpu_light`, `cpu_heavy`, `analysis`, `speech`, and `render` profile boundaries.
