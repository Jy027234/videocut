# QA Release Gate Checklist

Date: 2026-05-07

Status: P0 acceptance skeleton. This document is owned by QA/release for release gating and must be updated with report artifact refs before any P0 release decision.

## Scope

P0 release gates cover:

- Manifest and schema machine readability.
- Capability input/output contract validation.
- Caller-facing artifact_ref safety.
- Timeline patch structure, version baseline, and injection rejection.
- P0 demo acceptance and report consistency.

Out of scope for this checklist:

- Implementing src runtime, adapters, storage, manifests, or schemas.
- Approving high-sensitivity capabilities for production use.
- Replacing Platform Core, agentctl, or security/compliance review.

## Required Reports

Each report must bind the same `toolkit_id`, `version`, `manifest_hash`, `schema_version`, `test_suite_version`, `git_revision`, and environment.

| Gate | Required report | Release requirement |
| --- | --- | --- |
| manifest-validator-agent | `qa/manifest-validation/{version}/{git_revision}.json` | `passed` |
| schema-test-agent | `qa/schema-test/{version}/{git_revision}.json` | `passed` |
| timeline-patch-test-agent | `qa/timeline-patch-test/{version}/{git_revision}.json` | `passed` |
| artifact-permission-test-agent | `qa/artifact-permission-test/{version}/{git_revision}.json` | `passed` |
| performance-benchmark-agent | `qa/performance-benchmark/{version}/{git_revision}.json` | `passed` or `conditional_go` with owner-approved thresholds |
| regression-acceptance-agent | `qa/regression-acceptance/{version}/{git_revision}.json` | `passed` |
| release-check-agent | `release/release-check/{version}/{git_revision}.json` | `go` |

## Blocker Checklist

A P0 release is `no_go` if any item below is true:

- Any manifest JSON is not parseable or misses required Tool Catalog fields.
- Any schema JSON is not a valid JSON Schema document.
- Any P0 positive fixture fails schema validation after schemas land.
- Any negative fixture is accepted without a stable `error_code`.
- Any caller-facing output exposes `storage_uri`, raw local paths, internal worker addresses, raw shell commands, raw FFmpeg commands, or plaintext credentials.
- Any artifact can be read across tenant boundaries without explicit Platform Core authorization.
- Any expired artifact remains accessible without renewal authorization.
- Any `timeline_patch` bypasses `project_id`, `base_version_id`, or `change_reason`.
- Any `timeline_patch` accepts scripts, commands, arbitrary expressions, or unregistered effects.
- Timeline patch replay is non-deterministic for the same base version and patch.
- Rollback corrupts version history or removes audit evidence.
- P0 demo cannot complete the core chain: probe, extract audio, extract frames, detect scenes, transcribe, apply timeline patch, preview render, final render, delivery manifest.
- Long-running jobs miss status, usage metrics, trace refs, or stable error codes.
- Release reports disagree on version, git revision, manifest hash, or schema version.

## Conditional Go Rules

`conditional_go` is allowed only for performance-benchmark-agent and only when:

- No security, artifact, schema, or timeline blocker exists.
- The exceeded threshold is documented with p50/p95/p99, input fixture size, and environment.
- A named owner accepts the risk and records a follow-up issue.
- The release-check-agent includes the waiver in `required_followups`.

## Test Commands

Recommended local commands:

```powershell
python -m pip install -e ".[dev]"
python -m pytest tests
python -m pytest tests/test_manifest_schema_contract.py
python -m pytest tests/test_artifact_ref_contract.py tests/test_timeline_patch_fixtures.py
python -m pytest tests/test_runtime_adapter_integration.py
docker compose run --rm toolkit pytest tests
docker compose --profile analysis run --rm analysis pytest tests/test_analysis_adapter_outputs.py
docker compose --profile speech run --rm speech pytest tests/test_speech_whisper_adapter_outputs.py
```

Current skeleton behavior:

- Manifest tests skip until `manifests/*.json` exists.
- Schema tests skip until `schemas/**/*.json` exists.
- Artifact and timeline fixture tests run against the QA-owned fixtures in `fixtures/`.
- FFmpeg probe-media checks generate a tiny WAV with the Python standard library and verify the probe path when `ffprobe` is available; the positive probe test skips when `ffprobe` is not installed.
- FFmpeg dependency checks return stable `adapter.unavailable` when the required binary is missing.
- P0.2 FFmpeg extract checks cover `extract_audio` and `extract_frames`: host environments without `ffmpeg` skip real-output cases but still verify stable `adapter.unavailable`; Docker environments generate a tiny AV fixture with real `ffmpeg` and require caller-safe output artifact refs.
- Real `extract_audio` and `extract_frames` Docker cases now enforce artifact type, MIME family, and public payload leak safety.
- P0.3 analysis checks cover `detect_scenes`, `check_visual_quality`, and `analyze_frames`: host missing-dependency paths use real dummy artifact refs and require stable caller-safe failures; analysis-profile tests generate tiny video/frame artifacts and require real PySceneDetect/OpenCV outputs without path, command, or storage URI leaks.
- P0.4 speech checks cover `audio.speech.transcribe` and `audio.speech.align_subtitles`: host/default Docker verify `transcribe` returns stable `adapter.unavailable` when model execution is not explicitly allowed, `align_subtitles` can pass as a pure structured operation without model access, and all speech outputs stay caller-safe.
- Speech-profile checks validate the profile boundary with `VIDEO_TOOLKIT_WORKER_PROFILE=speech`, GPU-optional resource class routing, and no leakage of storage URIs, local model/cache paths, or raw command strings.
- ProjectEditAdapter timeline patch execution cases include one accepted fixture and stable `request.invalid` failures for unsafe or incomplete patches.
- P0.5 AssetIndex/Delivery checks use real dummy artifacts from `LocalArtifactStore` and require caller-safe `asset_index`, `delivery_manifest`, and `package_manifest` artifact refs.
- P0.5 local chain covers upload artifact -> probe -> asset index -> project create -> timeline patch -> preview marker -> delivery manifest, with graceful `xfail` only if AssetIndex/Delivery regress to `adapter.not_implemented`.
- P0.6 artifact manifest schema checks validate the internal JSON files written for `asset_index`, `delivery_manifest`, and `package_manifest` artifacts against `schemas/artifact-manifests.schema.json`, while continuing to scan public responses for storage/path/command leaks.
- P0.6 agentctl bridge checks validate the local JSON envelope for structured capabilities, stdin and `--input-json` input modes, stable unknown-capability failure, and caller-safe output redaction.
- P0.7 FFmpeg/render checks validate real `normalize_asset`, `video.render.render_preview`, and `video.render.render_final` MP4 artifacts in the default Docker worker.
- P0.7 local HTTP API checks validate `POST /local/toolkit-runs`, `GET /local/toolkit-runs/{run_id}`, `GET /local/artifacts/{artifact_id}`, and `GET /local/manifests` when optional API dependencies are installed.
- P0.8 project artifact checks validate generated `timeline.json` and `render_config.json` files against `schemas/artifact-manifests.schema.json`.
- P0.8 release-candidate checks validate manifest `$ref` JSON Pointer fragments, runtime route registration, and agentctl/local API envelope consistency.
- P0.9 remote agentctl checks validate local Docker agentctl health/OpenAPI/tool-catalog/runtime-worker protocol discovery, caller-safe draft registration payloads, no-upload RunSpec validation, and the performance decision to keep heavy media execution in standalone video toolkit workers.
- P0.10 runtime worker checks validate heartbeat, idle lease, leased no-upload job execution, failed job completion, explicit RunSpec enqueue probe, and caller-safe completion payloads.

## Current P0.2 QA Snapshot

Date: 2026-05-07

```text
Host:
  py -m pytest tests
  17 passed, 3 skipped

Docker:
  docker compose run --rm toolkit pytest tests
  20 passed
```

P0.2 implementation result:

- `video.asset_ingest.extract_audio` returns a real output audio artifact ref with `artifact_type=extracted_audio` and `mime_type` under `audio/`.
- `video.asset_ingest.extract_frames` returns real frame artifact refs with `artifact_type=extracted_frames` and `image/*` MIME types.
- Public `RunResponse.to_public_dict()` payloads must not expose local paths, worker-only `_worker_media_path`, raw shell commands, raw FFmpeg/FFprobe command lines, or internal storage URIs.

## Current P0.3 Analysis QA Snapshot

Date: 2026-05-07

```text
Host:
  py -m pytest tests
  20 passed, 6 skipped

Default Docker toolkit:
  docker compose run --rm toolkit pytest tests
  23 passed, 3 skipped

Analysis Docker profile:
  docker compose --profile analysis run --rm analysis pytest tests/test_analysis_adapter_outputs.py
  3 passed, 3 skipped
```

The three skipped analysis-profile tests are the missing-dependency checks,
which are intentionally inactive once `scenedetect` and `cv2` are installed in
the analysis image. The three real-output analysis tests pass in that profile.

P0.3 analysis result:

- `video.analysis.detect_scenes` succeeds in the analysis profile against a generated hard-cut MP4 and returns structured scene metadata with caller-safe public serialization.
- `video.analysis.check_visual_quality` succeeds in the analysis profile against a generated PNG frame and returns `quality_summary`/sample metrics.
- `video.analysis.analyze_frames` succeeds in the analysis profile against a generated PNG frame and returns `frames`, `frame_count`, and summary metrics.
- Host environments without `scenedetect`/`cv2` now validate stable `adapter.unavailable` when artifact refs resolve, instead of depending on nonexistent artifact ids.
- PySceneDetect timecode extraction uses `seconds` and `frame_num` properties with fallback compatibility for older package versions.

## Current P0.4 Speech QA Snapshot

Date: 2026-05-07

```text
Host:
  py -m pytest tests/test_speech_whisper_adapter_outputs.py -q
  2 passed, 3 skipped

Host full suite:
  py -m pytest tests -q
  22 passed, 9 skipped

Default Docker toolkit:
  docker compose run --rm toolkit pytest tests -q
  25 passed, 6 skipped

Speech Docker profile:
  docker compose --profile speech run --rm speech pytest tests/test_speech_whisper_adapter_outputs.py -q
  4 passed, 1 skipped
```

P0.4 speech result:

- `audio.speech.transcribe` returns stable caller-safe `adapter.unavailable` when Whisper/model execution is not explicitly allowed.
- `audio.speech.align_subtitles` succeeds as a pure structured operation against `fixtures/speech/align_subtitles/basic_alignment_request.json` without requiring a model.
- Speech profile boundary tests assert `gpu_optional` routing and guard against public leakage of `storage_uri`, local paths, model/cache hints, and raw command strings.
- The explicit-model transcribe positive test remains skipped until a worker has an explicitly configured local Whisper model. It should turn green only when the model is available and model execution is intentionally enabled.

Required implementation coordination:

- Keep Whisper/Torch/model weights out of default Docker and analysis images.
- Use `VET_WHISPER_MODEL`, `VET_WHISPER_MODEL_DIR`, `VET_ALLOW_WHISPER`, and `VET_ALLOW_WHISPER_DOWNLOAD` as the canonical speech worker env vars. `WHISPER_CACHE_DIR` remains a Docker/cache compatibility alias.
- Preserve caller-safe error messages when dependency, model, or cache setup is missing.

## Current P0.5 AssetIndex / Delivery QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_asset_index_delivery_contract.py -q
  3 passed

Host full suite:
  py -m pytest tests -q
  25 passed, 9 skipped

Host local chain demo:
  $env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
  probe failed gracefully on host without ffprobe; asset_index, project_edit, preview marker, and delivery_manifest succeeded

Default Docker toolkit:
  docker compose run --rm toolkit pytest tests -q
  28 passed, 6 skipped

Default Docker toolkit demo:
  docker compose run --rm toolkit video-toolkit-demo
  probe, asset_index, project_edit, preview marker, and delivery_manifest succeeded
```

P0.5 QA result:

- `video.asset_ingest.build_asset_index` accepts real dummy input artifact refs and returns a unique caller-safe asset-index artifact ref.
- `video.delivery.create_delivery_manifest` returns a caller-safe delivery-manifest artifact ref from dummy render/index refs.
- `video.delivery.package_artifacts` returns a caller-safe package-manifest artifact ref from the delivery manifest and render refs.
- The local chain reaches upload artifact -> probe -> asset index -> project create -> timeline patch -> preview marker -> delivery manifest.
- Public payload scanning now also blocks `local-artifact://` values, in addition to forbidden storage/path/command keys and local path-like strings.

Required implementation coordination:

- Keep AssetIndex and Delivery outputs in public responses as artifact refs only; do not expose `storage_uri`, worker paths, filenames as paths, raw commands, or local package locations.
- Preserve artifact types accepted by QA: `asset_index` or `asset_index_json`, `delivery_manifest` or `delivery_manifest_json`, and `package_manifest` or `package_manifest_json`.
- It is acceptable for the same artifact ref to appear in output and top-level `artifact_refs`; tests dedupe by `artifact_id` while still requiring one unique produced artifact per capability.

## Current P0.6 Artifact Manifest Schema QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_artifact_manifest_schema_contract.py -q
  2 passed

Host schema gate:
  py -m pytest tests/test_manifest_schema_contract.py -q
  4 passed

Host full suite:
  py -m pytest tests -q
  30 passed, 9 skipped

Default Docker toolkit:
  docker compose run --rm toolkit pytest tests -q
  35 passed, 4 skipped
```

P0.6 schema result:

- Added `schemas/artifact-manifests.schema.json` as the JSON Schema entry point for generated artifact manifest files.
- Schema defs now cover `public_artifact_ref`, `asset_index_manifest`, `delivery_manifest`, `package_manifest`, and `variant_plan`.
- Contract tests generate real artifacts through `LocalRunService` and `LocalArtifactStore`, read the written JSON artifact files back from the store, and validate the content against the schema.
- Public `RunResponse.to_public_dict()` payloads remain scanned for `storage_uri`, local paths, raw commands, and `local-artifact://` leakage.

Required implementation coordination:

- Preserve manifest `schema` identifiers: `video_editing_toolkit.asset_index.v0`, `video_editing_toolkit.delivery_manifest.v0`, and `video_editing_toolkit.package_manifest.v0`.
- Keep `input_artifact_refs` caller-safe and free of storage internals; schema validation intentionally rejects unexpected artifact-ref keys such as `storage_uri`.
- If variant output fields expand beyond the current P0.5 scalar fields, update `schemas/artifact-manifests.schema.json` and the generated-artifact tests together.

## Current P0.6 Agentctl Bridge QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_agentctl_cli_contract.py -q
  3 passed

Host P0.6 targeted:
  py -m pytest tests/test_artifact_manifest_schema_contract.py tests/test_agentctl_cli_contract.py -q
  5 passed

Host smoke:
  py -m video_editing_toolkit.agentctl --input-json <generate_variants request>
  succeeded with caller-safe JSON and no local path/private-field leakage

Default Docker toolkit:
  docker compose build toolkit
  docker compose run --rm toolkit pytest tests -q
  35 passed, 4 skipped

Default Docker toolkit smoke:
  docker compose run --rm toolkit video-toolkit-agentctl --input-json <generate_variants request>
  succeeded with caller-safe JSON and no workspace/tmp/private-field leakage
```

P0.6 agentctl result:

- Added `video_editing_toolkit.agentctl` and the `video-toolkit-agentctl` console script as a local agentctl-compatible bridge.
- The bridge accepts JSON through `--input-json` or stdin and creates `LocalArtifactStore`, `LocalRunService`, and registered P0 adapter handlers in-process.
- It emits a caller-safe envelope with `queued` and `processed` public runtime payloads.
- Structured no-upload capabilities such as `video.project_edit.create_project` and `video.delivery.generate_variants` are the intended P0.6 target.
- Unknown capabilities return a stable failed `processed` response with `error_code: handler_not_registered`.

Required implementation coordination:

- Keep this bridge local-only until Platform Core authz, queueing, artifact storage, and trace propagation are explicit.
- Do not add real external file upload to the bridge without extending artifact policy and tests.
- Preserve redaction of storage URIs, local paths, raw commands, worker-only fields, and credential-like keys.

## Current P0.7 FFmpeg Render / Local API QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_ffmpeg_render_outputs.py tests/test_local_api_contract.py -q
  8 passed, 3 skipped

Host full suite:
  py -m pytest tests -q
  38 passed, 12 skipped

Host local API help:
  $env:PYTHONPATH='src'; py -m video_editing_toolkit.local_api --help
  help rendered successfully

Host local chain demo:
  $env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
  probe failed gracefully on host without ffprobe; delivery_manifest succeeded; no public path/private-field leakage

Default Docker toolkit:
  docker compose build toolkit
  docker compose run --rm toolkit pytest tests/test_ffmpeg_render_outputs.py -q
  6 passed

Default Docker toolkit full suite:
  docker compose run --rm toolkit pytest tests -q
  41 passed, 5 skipped

Default Docker toolkit entrypoint:
  docker compose run --rm toolkit video-toolkit-local-api --help
  help rendered successfully

Default Docker toolkit demo:
  docker compose run --rm toolkit video-toolkit-demo
  probe and delivery_manifest succeeded; no workspace/tmp/private-field leakage
```

P0.7 result:

- `video.asset_ingest.normalize_asset` now materializes a real `normalized_video` MP4 artifact when FFmpeg/FFprobe are available.
- `video.render.render_preview` now materializes a real `preview_video` MP4 artifact with bounded preview height and duration options.
- `video.render.render_final` now materializes a real `final_render` MP4 artifact.
- FFmpeg/render outputs return caller-safe artifact refs and do not expose raw commands, local paths, stdout/stderr, `storage_uri`, or `local-artifact://`.
- Added the optional FastAPI local HTTP surface in `video_editing_toolkit.local_api` with the section 9 endpoints from the development plan.
- Default Docker remains lightweight and does not install FastAPI/uvicorn; local API tests run when `[api]` dependencies are available.

Required implementation coordination:

- P0.7 render is still a controlled single-input MP4 transcode, not a full timeline compositor.
- Keep FastAPI and uvicorn in the `api` optional dependency group unless the default worker contract changes.
- `GET /local/artifacts/{artifact_id}` must remain metadata-only until artifact download/authz policy is explicit.
- Preserve caller-safe output scanning for FFmpeg/render and HTTP API responses.

## Current P0.8 Release Candidate QA Snapshot

Date: 2026-05-07

```text
Host P0.8 targeted:
  py -m pytest tests/test_project_edit_artifact_contract.py tests/test_artifact_manifest_schema_contract.py tests/test_manifest_schema_contract.py tests/test_agentctl_cli_contract.py tests/test_local_api_contract.py -q
  17 passed

Host runtime/timeline targeted:
  py -m pytest tests/test_runtime_adapter_integration.py tests/test_timeline_patch_fixtures.py -q
  8 passed, 1 skipped

Host full suite:
  py -m pytest tests -q
  41 passed, 12 skipped

Host local chain demo:
  $env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
  probe failed gracefully on host without ffprobe; timeline/render_config/delivery artifacts succeeded; no public path/private-field leakage

Default Docker toolkit:
  docker compose build toolkit
  docker compose run --rm toolkit pytest tests/test_project_edit_artifact_contract.py tests/test_manifest_schema_contract.py -q
  6 passed

Default Docker toolkit full suite:
  docker compose run --rm toolkit pytest tests -q
  43 passed, 5 skipped

Default Docker toolkit demo:
  docker compose run --rm toolkit video-toolkit-demo
  probe, timeline/render_config artifacts, and delivery_manifest succeeded; no workspace/tmp/private-field leakage
```

P0.8 result:

- `video.project_edit.apply_timeline_patch` now materializes `timeline_json` and, when preview is requested, `render_config_json` artifacts.
- `video.project_edit.render_preview` now materializes a `render_config_json` artifact for the requested project version.
- `schemas/artifact-manifests.schema.json` now validates project timeline and render config artifact files in addition to asset/delivery/package manifests.
- Manifest schema reference checks now resolve `$ref` fragments such as `#/$defs/...`, not just schema filenames.
- Enabled manifest capabilities, `CAPABILITY_ROUTES`, and local runtime handler registration are checked as one release-candidate gate.
- Agentctl and local HTTP API structured no-upload requests are checked for caller-safe behavioral consistency.

P0.8 RC judgment:

- **Local P0 release-candidate gate is passing** for the independent toolkit surface.
- Remaining non-blockers for P0 RC are documented in `docs/release-gate.md`: full timeline compositor, formal Platform Core authz, persistent queue, external upload, object storage downloads, production tracing/retries, and multi-process scheduling.

Required implementation coordination:

- Keep `timeline_json` and `render_config_json` artifact schemas stable for P0 consumers.
- `ProjectEditAdapter` now requires runtime `_artifact_store` injection for patch/preview artifact materialization; LocalRunService provides it.
- Do not promote P0.8 to P1 until Platform Core/agentctl replacement points and P0 RC acceptance are reviewed.

## Current P0.9 Agentctl Docker Pre-Integration QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_agentctl_remote_probe_contract.py -q
  6 passed, 1 skipped

Host compile:
  py -m compileall src
  passed

Local Docker agentctl read probe:
  $env:PYTHONPATH='src'; $env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'; py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765
  ok: true

Local Docker agentctl RunSpec validation:
  py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --validate-runspec
  valid: true

Local Docker agentctl worker smoke:
  py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --worker-smoke
  heartbeat_ok: true, lease_ok: true

Local Docker agentctl tool-catalog registration:
  py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --register
  draft tool catalog entry accepted
```

P0.9 result:

- Added `video_editing_toolkit.agentctl_remote` and `video-toolkit-agentctl-remote` for optional remote agentctl probing.
- The probe confirms local Docker agentctl API `0.2.0b2`, route discovery, runtime worker protocol `0.1.0`, tool catalog access, and runtime job/worker endpoints.
- The manifest-backed draft tool catalog payload exposes 23 P0 capabilities, `toolkit.video_editing.p0`, artifact/trace side effects, and `external_video_toolkit_worker` metadata.
- The no-upload `RunSpecDraft` for `video.project_edit.create_project` is accepted by `/runspecs/validate`.
- A short worker heartbeat and idle lease probe succeed without executing video work.
- Current local agentctl reports `local` as ready and Docker runtime backend as disabled; this is a P0.9 non-blocker because heavy media work remains in the standalone video toolkit worker.

P0.9 judgment:

- **Agentctl Docker pre-integration is passing for control-plane shape.**
- **Do not promote to P1 execution yet**: an external video worker still needs heartbeat/lease/execute/complete wiring, artifact service integration, authz, quotas, tracing, retries, and isolated Docker/remote runtime enablement.

Required implementation coordination:

- Keep the default remote probe read-oriented. `--register`, `--validate-runspec`, and `--worker-smoke` remain explicit operator actions.
- Do not use `/runs`, in-process `/runspecs/run`, or `/runtime/backends/workers/local/run-once` for media workloads.
- Continue treating Product Adapter onboarding, learning/audit ingestion, and release-center publication as later platformization work, not P0.9 worker execution.

## Current P0.10 Agentctl Runtime Worker QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_agentctl_worker_contract.py tests/test_agentctl_remote_probe_contract.py -q
  13 passed, 2 skipped

Host compile:
  py -m compileall src
  passed

Local Docker agentctl enqueue/worker/complete smoke:
  $env:PYTHONPATH='src'; $env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'; py -m video_editing_toolkit.agentctl_worker --base-url http://127.0.0.1:8765 --worker-id video-toolkit-live-p010 --backend-id local --lease-seconds 30 --ttl-seconds 60 --enqueue-probe
  status: completed
```

P0.10 result:

- Added `video_editing_toolkit.agentctl_worker` and `video-toolkit-agentctl-worker`.
- The worker registers heartbeat, leases one runtime job, executes a local toolkit envelope, and completes the job back to agentctl.
- The worker accepts `job.payload.input_payload` from RunSpec dispatch and rejects non-`video-editing-toolkit` payloads.
- A no-upload probe job enqueued through `/runspecs/run` with `dispatch_mode=enqueue` completed successfully through the external worker path.
- The worker maps runtime `job_id` to local toolkit `run_id` and runtime `lease_id` to local `tool_call_id` when callers did not provide them.
- `--enqueue-probe` is targeted to the just-created runtime `job_id`; if the worker leases a different existing backend job, it returns `unexpected_job_leased` and does not complete that job.

P0.10 judgment:

- **External agentctl runtime worker loop is passing for no-upload structured capabilities.**
- Heavy media execution is still blocked until artifact service integration and isolated Docker/remote worker backend are explicit.

Required implementation coordination:

- Keep `--enqueue-probe` limited to no-upload structured capabilities.
- Do not route artifact-dependent FFmpeg/OpenCV/Whisper/render jobs through the worker until artifact refs resolve through Platform Core or compatible object storage.
- Next platformization slice should add worker-side artifact fetch/materialize policy and resource-limited media job execution behind an isolated backend.

## Current P0.11 Artifact Materialization QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_artifact_materialization_contract.py tests/test_agentctl_worker_contract.py -q
  15 passed, 1 skipped

Host compile:
  py -m compileall src
  passed

Host full:
  py -m pytest tests -q
  62 passed, 14 skipped

Docker full:
  docker compose run --rm toolkit pytest tests -q
  64 passed, 7 skipped
```

P0.11 result:

- Added worker-side materialization before `run_agentctl()` execution.
- `LocalArtifactStore` can now preserve a validated Platform artifact id when the worker intentionally materializes an input artifact.
- Unsafe artifact ids are rejected before they can become local directories.
- Materialization accepts relative artifact `download_url` values or same-origin absolute URLs only; `storage_uri`, `file://`, non-http schemes, and off-origin URLs are not download sources.
- Materialization verifies `size_bytes` and `sha256` before storing bytes.
- Worker materialization failures complete the runtime job as failed with stable `video_toolkit_worker.artifact_materialization_failed` and a reason code, without leaking URLs, local paths, `storage_uri`, or tokens.

P0.11 judgment:

- **Artifact-service-backed worker materialization contract is passing locally with a fake byte endpoint.**
- Live byte-service smoke remains blocked until Platform Core or an equivalent artifact service exposes a compatible bytes endpoint; the current local API artifact endpoint is metadata-only by design.

Required implementation coordination:

- Keep heavy media execution outside agentctl and behind an isolated worker/runtime backend.
- Require Platform Core artifact service authz, expiry, retention, and tenant policy before production media jobs.
- Keep `GET /local/artifacts/{artifact_id}` metadata-only unless a separate byte endpoint contract is approved.

## Current P0.12 Worker Resource Policy QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_agentctl_worker_contract.py -q
  15 passed, 1 skipped

Host compile:
  py -m compileall src
  passed

Host full:
  py -m pytest tests -q
  68 passed, 14 skipped

Docker full:
  docker compose run --rm toolkit pytest tests -q
  70 passed, 7 skipped
```

P0.12 result:

- Added `video_editing_toolkit.agentctl_worker_policy`.
- Worker execution now validates `capability` against `CAPABILITY_ROUTES` before artifact materialization.
- Default worker resource policy accepts only `cpu_light`.
- `--allowed-resource-classes` can explicitly enable `cpu_heavy` or other route classes.
- `--allowed-capabilities` can narrow a worker to a capability allowlist.
- `--max-job-input-bytes` rejects declared artifact input sizes before downloading bytes.
- `--max-run-timeout-seconds` rejects routes whose declared timeout exceeds the worker policy.
- Worker heartbeat advertises allowed resource classes, allowed capabilities, input limit, and timeout limit.

P0.12 judgment:

- **Route-aware worker policy preflight is passing locally.**
- This is a preflight guard only; hard cancellation/kill for synchronous adapter execution still requires isolated process or remote worker backend work.

Required implementation coordination:

- Keep CPU-heavy/GPU media capabilities disabled by default in the generic worker.
- Run heavy media capabilities only on explicitly configured workers with matching resource class and timeout policy.
- Add hard cancellation, retries, and trace propagation before production-scale media jobs.

## Current P0.13 Subprocess Execution QA Snapshot

Date: 2026-05-07

```text
Host targeted:
  py -m pytest tests/test_agentctl_worker_runner_contract.py tests/test_agentctl_worker_contract.py -q
  20 passed, 1 skipped

Host compile:
  py -m compileall src
  passed

Host full:
  py -m pytest tests -q
  73 passed, 14 skipped

Docker full:
  docker compose run --rm toolkit pytest tests -q
  75 passed, 7 skipped
```

P0.13 result:

- Added `video_editing_toolkit.agentctl_worker_runner`.
- Worker supports `execution_mode=in_process` and `execution_mode=subprocess`.
- Subprocess mode runs `sys.executable -m video_editing_toolkit.agentctl` with `shell=False`.
- Toolkit envelope is sent over stdin rather than argv.
- Subprocess argv only contains the module invocation and `--artifact-root`.
- Subprocess timeout normalizes to `video_toolkit_worker.execution_timeout` with `resource.timeout_exceeded`.
- Subprocess startup/JSON failures normalize to stable local-execution errors without returning stderr, argv, environment, tokens, or local paths.

P0.13 judgment:

- **Optional subprocess execution is passing locally for no-upload structured jobs.**
- This creates a local process boundary and timeout kill point; production media isolation still needs Docker/remote worker backend and resource enforcement.

Required implementation coordination:

- Use subprocess mode for heavier local worker experiments before moving to remote/Docker execution pools.
- Do not treat subprocess mode as a full sandbox for CPU/GPU/memory isolation.
- Keep error payloads stable and caller-safe; do not surface raw subprocess stderr or argv.

## Current P0.14 Worker Lifecycle Control QA Snapshot

Date: 2026-05-08

```text
Host targeted:
  py -m pytest tests/test_agentctl_worker_runner_contract.py tests/test_agentctl_worker_contract.py tests/test_local_api_contract.py -q
  32 passed, 1 skipped

Host compile:
  py -m compileall src
  passed

Host full:
  py -m pytest tests -q
  79 passed, 14 skipped

Docker full:
  docker compose run --rm toolkit pytest tests -q
  80 passed, 7 skipped
```

P0.14 result:

- Worker heartbeat now advertises `execution_backend`, supported backend values, `max_attempts`, retry policy, cancel contract, and the lifecycle contract id.
- `in_process` and `subprocess` remain executable; `docker` and `remote` are registered placeholders that fail as `video_toolkit_worker.execution_backend_unavailable`.
- Runtime job `trace_id` is propagated into the local toolkit as `trace_ref` and returned in worker completion metadata.
- Worker completion metadata includes trace, usage, execution backend, attempt, max attempts, and retry policy.
- Jobs with `attempts > max_attempts` are rejected before materialization or local execution.
- Jobs marked `cancel_requested`, `cancelled`, or `cancelling` are skipped before materialization or local execution.
- Local API now supports `POST /local/toolkit-runs/{run_id}/cancel` for queued local development runs.
- Generic worker failures are redacted before completion so local paths, URLs, tokens, argv, stderr, env, and storage internals are not caller-visible.

P0.14 judgment:

- **Worker lifecycle control scaffolding is passing locally and in Docker.**
- This is still not production retry scheduling, in-flight cancellation, or CPU/GPU/memory isolation.

Required implementation coordination:

- Keep `docker` and `remote` backends unavailable until real execution-pool adapters and resource enforcement exist.
- Do not treat queued-run local API cancellation as an in-flight media kill path.
- Preserve worker completion metadata shape for Platform Core / agentctl indexing.

## Current P0.15 Platform Core Handoff QA Snapshot

Date: 2026-05-08

```text
Host targeted:
  py -m pytest tests/test_platform_core_handoff_contract.py -q
  4 passed

Host compile:
  py -m compileall src
  passed

Host full:
  py -m pytest tests -q
  83 passed, 14 skipped

Docker full:
  docker compose run --rm toolkit pytest tests -q
  84 passed, 7 skipped
```

P0.15 result:

- Added `video_editing_toolkit.platform_core` and `video-toolkit-platform-core`.
- Platform Core toolkit descriptor is generated from the P0 manifest.
- Future Platform Core run requests normalize into the local agentctl envelope without requiring a live Platform Core service.
- Local agentctl/worker results normalize into a Platform Core completion payload with run id, tool call id, status, output, artifact refs, usage metrics, trace ref, and stable errors.
- Handoff payloads keep `artifact_ref_only` as the artifact contract and do not expose `storage_uri`, local paths, raw commands, argv, stderr, env, or credential-like fields.

P0.15 judgment:

- **Platform Core handoff interfaces are reserved and contract-tested.**
- This is not a live Platform Core client, byte upload flow, Product Adapter onboarding, or production authz implementation.

Required implementation coordination:

- Keep real Platform Core network calls outside the independent toolkit until authz, token, artifact bytes, and retention contracts are approved.
- Keep `platform_run_id`, `platform_tool_call_id`, and `platform_trace_id` mappings stable for future agentctl/Platform Core indexing.
