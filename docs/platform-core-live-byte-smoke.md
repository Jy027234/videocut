# Platform Core Live Byte Pull Smoke

Date: 2026-05-08

Status: completed

This smoke verifies the live artifact byte path between local Platform Core, Docker agentctl, and the video toolkit worker.

The one-off run is now codified in `video_editing_toolkit.platform_core`:

- `PlatformCoreClient.register(...)`
- `PlatformCoreClient.create_service_account(...)`
- `PlatformCoreClient.create_toolkit_artifact(...)`
- `PlatformCoreClient.download_artifact_bytes(...)`
- `build_toolkit_artifact_create_payload(...)`
- `verify_artifact_bytes(...)`

The client is stdlib-only and accepts an injectable `urlopen`, so unit tests can lock the HTTP contract without touching a real Platform Core service.

## Environment

- Platform Core: `http://127.0.0.1:8010`
- Platform Core env: `video-toolkit-smoke`
- Platform Core DB: `D:\app\zhiziagent-platform-core\.tmp\video-toolkit-platform-core-smoke.db`
- Source video: `D:\app\video\cd3078834c5422d93aa7113ace956588.mp4`
- Worker artifact root: `D:\个人文件\个人开发\标准工具组\video-editing-toolkit\.video-toolkit-data\platform-core-live-smoke-worker-artifacts`

## Direct Worker Flow

1. Registered a smoke tenant through `/auth/register`.
2. Created an `agentctl` service account with `toolkit.artifacts.read` and `agentctl.run`.
3. Uploaded the video bytes to `/toolkit-artifacts`.
4. Downloaded bytes directly through `/toolkit-artifacts/{artifact_id}/bytes` using the service token.
5. Ran `VideoToolkitAgentctlWorker.execute_job()` with an artifact-ref-only job envelope.
6. The worker materialized the artifact through `artifact_ref.download_url` and verified size and SHA-256.

## Result

```json
{
  "artifact_id": "tka_fcfb1185d18143b383796b42",
  "download_url": "/toolkit-artifacts/tka_fcfb1185d18143b383796b42/bytes",
  "size_bytes": 2933584,
  "sha256": "a35de091716d72c21d74d7d6ae4e0f4439d8994e068035d11c5db26f9b13fc8d",
  "worker_status": "completed",
  "resource_class": "cpu_heavy",
  "route_timeout_seconds": 900
}
```

Note: local `ffprobe` is not available on the host PATH, so this smoke validates the live byte pull and worker materialization path by byte-for-byte checksum. Media probing remains covered by the Docker FFmpeg smoke.

## Agentctl Queue Flow

The reusable queue smoke is now codified in `video_editing_toolkit.agentctl_live_smoke`:

- Build a `/runspecs/run` payload with `dispatch_mode=enqueue`.
- Point the RunSpec at existing Platform Core `artifact_refs`.
- Register/heartbeat a video worker against Docker agentctl.
- Lease the queued runtime job.
- Materialize bytes from Platform Core using a dedicated artifact token.
- Execute the toolkit capability and complete the runtime job.

The worker now supports split credentials:

- `token`: agentctl control-plane bearer token.
- `artifact_token`: Platform Core service-account token for artifact byte downloads.
- `VIDEO_TOOLKIT_ARTIFACT_TOKEN`: environment variable for artifact downloads.
- `--artifact-token`: CLI override for artifact downloads.

## Agentctl Queue Result

```json
{
  "artifact_id": "tka_4f25f8a673ae412780912cb3",
  "artifact_ref_count": 1,
  "job_id": "rtjob_b46fd72d4beb4370",
  "queue_status": "completed",
  "worker_status": "completed",
  "output_status": "completed",
  "separate_artifact_credentials": true,
  "size_bytes": 2933584,
  "sha256": "a35de091716d72c21d74d7d6ae4e0f4439d8994e068035d11c5db26f9b13fc8d"
}
```

## Reusable CLI Shape

Do not pass real tokens or passwords as literal command arguments. The CLI reads credentials from environment variables and redacts token-like fields in JSON output.

```powershell
$env:PLATFORM_CORE_REGISTER_PASSWORD = "<smoke-password>"
python -m video_editing_toolkit.platform_core `
  --base-url http://127.0.0.1:8010 `
  register `
  --email video-toolkit-smoke@example.invalid `
  --display-name "Video Toolkit Smoke" `
  --tenant-name "Video Toolkit Smoke"
```

```powershell
$env:PLATFORM_CORE_OWNER_TOKEN = "<owner-access-token>"
python -m video_editing_toolkit.platform_core `
  --base-url http://127.0.0.1:8010 `
  create-service-account `
  --tenant-id "<tenant-id>" `
  --scope toolkit.artifacts.read `
  --scope toolkit.artifacts.write `
  --scope agentctl.run
```

```powershell
$env:PLATFORM_CORE_SERVICE_TOKEN = "<service-token>"
python -m video_editing_toolkit.platform_core `
  --base-url http://127.0.0.1:8010 `
  create-artifact `
  --file "<source-video.mp4>" `
  --capability video.asset_ingest.probe_media `
  --artifact-type source_video `
  --mime-type video/mp4 `
  --run-id run_video_smoke `
  --trace-id trace_video_smoke
```

```powershell
$env:PLATFORM_CORE_SERVICE_TOKEN = "<service-token>"
python -m video_editing_toolkit.platform_core `
  --base-url http://127.0.0.1:8010 `
  download-artifact-bytes `
  --artifact "<artifact-id-or-download-url>" `
  --expect-size-bytes 2933584 `
  --expect-sha256 a35de091716d72c21d74d7d6ae4e0f4439d8994e068035d11c5db26f9b13fc8d
```

The command prints metadata only for downloads: `size_bytes` and `sha256`. It does not write downloaded bytes to disk, does not persist tokens, and does not require local Platform Core DB access.

For a real queue smoke after an artifact has been created:

```powershell
$env:VIDEO_TOOLKIT_AGENTCTL_TOKEN = "<agentctl-control-plane-token>"
$env:VIDEO_TOOLKIT_ARTIFACT_TOKEN = "<platform-core-service-token>"
python -m video_editing_toolkit.agentctl_live_smoke `
  --base-url http://127.0.0.1:8765 `
  --artifact-base-url http://127.0.0.1:8010 `
  --artifact-ref-json '<artifact-ref-json>' `
  --capability video.asset_ingest.build_asset_index `
  --allowed-capabilities video.asset_ingest.build_asset_index
```

The queue smoke prints caller-safe metadata only. It does not print bearer tokens, local worker paths, or raw download URLs.
