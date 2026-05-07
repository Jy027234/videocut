# Platform Core Live Byte Pull Smoke

Date: 2026-05-08

Status: completed

This smoke verifies the live artifact byte path between local Platform Core and the video toolkit worker.

## Environment

- Platform Core: `http://127.0.0.1:8010`
- Platform Core env: `video-toolkit-smoke`
- Platform Core DB: `D:\app\zhiziagent-platform-core\.tmp\video-toolkit-platform-core-smoke.db`
- Source video: `D:\app\video\cd3078834c5422d93aa7113ace956588.mp4`
- Worker artifact root: `D:\个人文件\个人开发\标准工具组\video-editing-toolkit\.video-toolkit-data\platform-core-live-smoke-worker-artifacts`

## Flow

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
