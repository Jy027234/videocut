# Sub-Agent Development Run

Date: 2026-05-07

Status: P0 scaffold integrated.

## Active Ownership

```text
Hume
manifests/, schemas/, docs/manifest-contract.md

McClintock
src/video_editing_toolkit/runtime/, src/video_editing_toolkit/storage/, docs/runtime-api.md

Peirce
src/video_editing_toolkit/adapters/, src/video_editing_toolkit/resource_guard/, docs/adapters.md

Erdos
tests/, fixtures/, docs/qa-release.md
```

## Integration Rule

Each sub-agent returns changed files, affected capabilities, tests or validation performed, known risks, and next dependencies. The orchestrator performs final integration and release gate checks.

## Integration Result

```text
manifest/schema: landed
runtime/artifact: landed
adapter/resource: landed
QA/release gates: landed
runtime-to-adapter bridge: landed
P0 placeholder demo: landed
```

Validation:

```text
py -m compileall src
py -m pytest tests
$env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
```

The P0 demo registers all enabled manifest capabilities with adapter routes. Real worker execution remains intentionally unimplemented and returns `adapter.not_implemented` until the next development slice adds controlled FFmpeg/Whisper/OpenCV implementations.

## Next Stage Run

Status: completed.

Environment probe:

```text
ffmpeg: not found on current PATH
ffprobe: not found on current PATH
cv2: not installed
scenedetect: not installed
whisper: not installed
```

Active ownership:

```text
Archimedes
src/video_editing_toolkit/adapters/ffmpeg.py, docs/adapters.md

Confucius
src/video_editing_toolkit/project_edit/, src/video_editing_toolkit/adapters/project_edit.py, docs/project-edit.md

Kuhn
src/video_editing_toolkit/storage/artifacts.py, src/video_editing_toolkit/runtime/models.py, src/video_editing_toolkit/runtime/service.py, docs/runtime-api.md

Noether
tests/, fixtures/, docs/qa-release.md
```

Target:

```text
1. Controlled FFmpeg adapter boundary with stable unavailable errors when binaries are missing.
2. Real in-process project_edit timeline patch validation and version model.
3. Caller-safe public serialization for artifact/run responses.
4. Tests for missing binaries, project_edit patch safety, and public-output leakage.
```

Result:

```text
FFmpeg adapter:
  Controlled dependency detection landed.
  probe_media returns adapter.unavailable when ffprobe is missing.
  probe JSON path is structured and strips filename from public output.

Project Edit:
  In-process project store, version model, timeline patch validation, compare, rollback landed.
  valid apply_timeline_patch succeeds.
  script/command injection and missing base_version_id fail with request.invalid plus stable_error_code.

Public serialization:
  ArtifactRef.to_public_dict landed.
  RunResponse.to_public_dict landed.
  public service methods landed.

QA:
  runtime adapter integration tests updated.
  artifact public-output tests updated.
  project_edit safety tests updated.
```

Validation:

```text
py -m compileall src
py -m pytest tests
15 passed
$env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
```

## P0.1 Docker Worker Run

Status: completed.

Environment:

```text
Docker: available
Docker Compose: available
Host ffmpeg/ffprobe: not available
```

Active ownership:

```text
Lagrange
Dockerfile, docker-compose.yml, .dockerignore, docs/docker.md

Aquinas
src/video_editing_toolkit/adapters/ffmpeg.py, src/video_editing_toolkit/runtime/adapter_handler.py, docs/adapters.md

Plato
tests/, fixtures/media/, docs/qa-release.md
```

Target:

```text
1. Build a local Docker worker environment with ffmpeg/ffprobe.
2. Resolve artifact_ref to internal worker paths without exposing paths publicly.
3. Run probe_media against a tiny fixture in Docker.
4. Keep host development graceful when ffmpeg/ffprobe are missing.
```

Result:

```text
Docker Worker:
  Dockerfile, docker-compose.yml, .dockerignore, and docs/docker.md landed.
  Container image uses Python 3.13 with ffmpeg and ffprobe installed.
  The worker can run tests, demo, ffmpeg -version, and ffprobe -version.

Artifact Boundary:
  adapter_handler resolves artifact_refs through LocalArtifactStore.
  Caller-provided internal worker paths are stripped before adapter invocation.
  Public responses do not expose local paths, filenames, or generated commands.

FFmpeg Adapter:
  probe_media runs real ffprobe JSON when ffprobe and one resolved media artifact are available.
  Host without ffprobe returns adapter.unavailable with a stable public payload.
  Probe output strips filename fields before returning to callers.

QA:
  Tiny WAV fixture is generated dynamically with Python stdlib.
  Host tests skip the real ffprobe path when ffprobe is unavailable.
  Docker tests exercise the real ffprobe path.
```

Validation:

```text
py -m compileall src
py -m pytest tests
15 passed, 1 skipped
$env:PYTHONPATH='src'; py -m video_editing_toolkit.demo

docker compose run --rm toolkit
16 passed
docker compose run --rm toolkit ffprobe -version
ffprobe version 7.1.3-0+deb13u1
docker compose run --rm toolkit ffmpeg -version
ffmpeg version 7.1.3-0+deb13u1
docker compose run --rm toolkit video-toolkit-demo
probe_media succeeded with WAV stream and format metadata
```

Next dependencies:

```text
1. Implement FFmpeg extract_audio and extract_frames with output artifact_refs.
2. Add first real PySceneDetect/OpenCV media-analysis adapter behind Docker.
3. Keep Whisper and diarization as optional heavy workers with separate deployment profiles.
```

## P0.2 FFmpeg Extract Output Run

Status: completed.

Active ownership:

```text
Lorentz
src/video_editing_toolkit/adapters/ffmpeg.py, src/video_editing_toolkit/runtime/adapter_handler.py

Halley
docker-compose.yml, docs/docker.md, README.md

Copernicus
tests/, fixtures/, docs/qa-release.md, docs/subagent-run-2026-05-07.md
```

Target:

```text
1. Add extract_audio and extract_frames tests that adapt to host environments without ffmpeg.
2. In Docker, generate a tiny AV input with real ffmpeg and assert real output artifact_refs once implemented.
3. Keep public payload checks focused on caller-visible data: no local paths, raw shell commands, raw FFmpeg/FFprobe command lines, or storage internals.
```

Result:

```text
QA:
  Added tests/test_ffmpeg_extract_outputs.py.
  Missing ffmpeg/ffprobe path now verifies stable adapter.unavailable for both capabilities.
  Real-output cases skip on host without ffmpeg.
  Real-output cases enforce caller-safe artifact refs in Docker.
  Refined public leakage helper so dependency names like "ffmpeg adapter" are allowed while command lines like "ffmpeg -i ..." remain blocked.

FFmpeg:
  extract_audio now runs controlled ffmpeg for wav and m4a outputs.
  extract_audio writes extracted_audio artifacts through LocalArtifactStore.
  extract_frames now runs controlled ffmpeg for jpg/jpeg/png frame outputs.
  extract_frames limits P0 output to 1-10 frame artifact_refs.
  Adapter output does not expose worker paths, temp paths, raw commands, stderr, stdout, or storage_uri.

Docker:
  Default toolkit worker remains light with ffmpeg/ffprobe.
  Optional analysis profile boundary added for future PySceneDetect/OpenCV/Whisper workers.
```

Validation:

```text
py -m compileall src
py -m pytest tests
17 passed, 3 skipped

docker compose config
docker compose --profile analysis config
docker compose run --rm toolkit pytest tests
20 passed

docker compose run --rm toolkit video-toolkit-demo
probe_media and project_edit demo succeeded

docker compose --profile analysis run --rm analysis
analysis profile boundary command succeeded
```

Next dependencies:

```text
1. Add PySceneDetect/OpenCV real analysis adapters behind the analysis profile.
2. Add richer FFmpeg extract options only after schema and policy constraints are explicit.
3. Split no-audio/no-video failures into more specific stable error codes.
```

## P0.3 Analysis Adapter Run

Status: completed.

Active ownership:

```text
Arendt
src/video_editing_toolkit/adapters/scenedetect.py, src/video_editing_toolkit/adapters/opencv.py, src/video_editing_toolkit/runtime/adapter_handler.py, docs/adapters.md

Ramanujan
pyproject.toml, Dockerfile, docker-compose.yml, docs/docker.md, README.md

Mill
tests/, fixtures/, docs/qa-release.md, docs/subagent-run-2026-05-07.md
```

Target:

```text
1. Add analysis capability tests for detect_scenes, check_visual_quality, and analyze_frames.
2. Keep host environments graceful when PySceneDetect/OpenCV dependencies are missing.
3. In the analysis Docker profile, generate tiny video/frame artifacts and require real caller-safe outputs.
4. Preserve the public boundary: no local paths, worker commands, storage_uri, or worker-only internals in public payloads.
```

Result:

```text
Adapters:
  PySceneDetectAdapter now lazily loads scenedetect and runs content scene detection.
  OpenCVAdapter now lazily loads cv2 and runs visual quality/frame metrics.
  Missing scenedetect/cv2 dependencies return stable adapter.unavailable.
  Runtime artifact resolution now supports artifact_ref, artifact_refs, artifact_id, and artifact_ids.
  Runtime injects private _worker_media_path and _worker_media_paths while stripping caller-provided private keys.

Docker:
  Default toolkit image remains light and does not install analysis dependencies.
  Analysis profile now builds the dedicated analysis Dockerfile target.
  Analysis image installs opencv-python-headless and scenedetect without pulling opencv-python.
  Whisper, GPU runtimes, and model weights remain outside the analysis image.

QA:
  Added tests/test_analysis_adapter_outputs.py.
  Host missing-dependency tests now use resolved dummy artifact refs and require stable adapter.unavailable.
  Analysis profile tests generate a hard-cut MP4 and PNG frame with ffmpeg.
  detect_scenes asserts structured scene output from PySceneDetect.
  check_visual_quality asserts OpenCV quality summary/sample metrics.
  analyze_frames asserts OpenCV frame analysis output.
  All analysis outputs are checked with the existing public path/command leak helper.

Compatibility:
  Existing FFmpeg missing-binary tests were updated to use real dummy artifact refs because runtime artifact resolution now runs before adapter execution.
```

Validation:

```text
py -m compileall src

py -m pytest tests/test_analysis_adapter_outputs.py -q
3 passed, 3 skipped

py -m pytest tests -q
20 passed, 6 skipped

docker compose config
docker compose --profile analysis config

docker compose run --rm toolkit pytest tests -q
23 passed, 3 skipped

docker compose --profile analysis run --rm analysis pytest tests/test_analysis_adapter_outputs.py -q
3 passed, 3 skipped
```

Next dependencies:

```text
1. Add Whisper/transcription as a separate optional worker image/profile, not in default toolkit or analysis.
2. Add scene/visual-analysis artifact outputs only after schema and retention policy are explicit.
3. Preserve equivalent scene list/count and quality/frame metric structures if output field names evolve.
```

## P0.4 Speech / Whisper QA Run

Status: completed.

Active ownership:

```text
Cicero
src/video_editing_toolkit/adapters/whisper.py, src/video_editing_toolkit/adapters/audio_quality.py, docs/adapters.md

Feynman
pyproject.toml, Dockerfile, docker-compose.yml, docs/docker.md

Descartes
tests/, fixtures/, docs/qa-release.md, docs/subagent-run-2026-05-07.md
```

Target:

```text
1. Add speech/Whisper QA skeleton without requiring Whisper or model weights on host/default Docker.
2. Verify stable caller-safe unavailable behavior for transcribe when model execution is not explicitly allowed.
3. Verify the speech profile boundary does not leak storage_uri, local paths, model/cache hints, or raw commands.
4. Add a positive pure-structured align_subtitles test that does not depend on a model.
5. Leave explicit-model transcribe positive coverage skipped until a local model is intentionally configured.
```

Result:

```text
Adapters:
  WhisperAdapter now has a guarded real transcribe path using optional openai-whisper.
  Whisper model execution is disabled unless allow_model_run or VET_ALLOW_WHISPER is set.
  Whisper model downloads are disabled unless allow_model_download or VET_ALLOW_WHISPER_DOWNLOAD is set.
  align_subtitles succeeds as a pure local SRT formatter for supplied transcript text or segments.
  AudioQualityAdapter now computes WAV/PCM quality metrics via stdlib wave and can fall back to ffprobe metadata for non-WAV media.

Docker:
  Added a dedicated speech Dockerfile target and speech Compose profile.
  Speech image does not install openai-whisper, Torch, CUDA runtime, or model weights by default.
  Speech profile mounts video-toolkit-whisper-cache and exposes it as VET_WHISPER_MODEL_DIR plus WHISPER_CACHE_DIR compatibility alias.

QA:
  Added tests/test_speech_whisper_adapter_outputs.py.
  Added fixtures/speech/align_subtitles/basic_alignment_request.json.
  transcribe without model execution returns stable adapter.unavailable and caller-safe public output.
  align_subtitles succeeds as a pure structured operation using transcript segments.
  speech profile tests validate gpu_optional routing and public leak safety.
  explicit-model transcribe remains skipped unless a model hint is present.

Coordination:
  Whisper/Torch/model weights remain out of default toolkit and analysis images.
  Docker speech profile exists as an explicit boundary for future dependency/model wiring.
  Canonical speech env vars are VET_WHISPER_MODEL, VET_WHISPER_MODEL_DIR, VET_ALLOW_WHISPER, and VET_ALLOW_WHISPER_DOWNLOAD.
```

Validation:

```text
py -m pytest tests/test_speech_whisper_adapter_outputs.py -q
2 passed, 3 skipped

py -m pytest tests -q
22 passed, 9 skipped

docker compose run --rm toolkit pytest tests -q
25 passed, 6 skipped

docker compose --profile speech config
docker compose --profile speech run --rm speech

docker compose --profile speech run --rm speech pytest tests/test_speech_whisper_adapter_outputs.py -q
4 passed, 1 skipped
```

Next dependencies:

```text
1. Add a derived speech image with openai-whisper/Torch only after CPU/GPU runtime and Python-version constraints are explicit.
2. Add a CI-safe tiny explicit-model path only after the model artifact policy and cache volume contract are approved.
3. Keep transcribe unavailable errors stable and caller-safe when dependencies, model files, or model execution flags are absent.
```

## P0.5 AssetIndex / Delivery QA Run

Status: completed.

Active ownership:

```text
QA/documentation
tests/, fixtures/, docs/qa-release.md, docs/subagent-run-2026-05-07.md

Parallel implementation
src/video_editing_toolkit/adapters/asset_index.py
src/video_editing_toolkit/adapters/delivery.py
```

Target:

```text
1. Add build_asset_index tests using real dummy artifact refs from LocalArtifactStore.
2. Require asset_index output to be a caller-safe artifact ref.
3. Require delivery manifest and package manifest outputs to be caller-safe artifact refs.
4. Cover a local chain from upload artifact through probe, asset_index, project_create/apply_patch, preview marker, and delivery_manifest.
5. Gracefully xfail only while AssetIndex/Delivery remain registered placeholders.
```

Result:

```text
QA:
  Added tests/test_asset_index_delivery_contract.py.
  Extended public leakage scanning to reject local-artifact:// values.
  build_asset_index now verifies one unique public asset_index artifact ref.
  create_delivery_manifest now verifies one unique public delivery_manifest artifact ref.
  package_artifacts now verifies one unique public package_manifest artifact ref.
  Local chain covers upload artifact -> probe -> asset_index -> project_create -> apply_timeline_patch -> preview marker -> delivery_manifest.

Implementation coordination observed:
  AssetIndex/Delivery implementations were present during QA validation, so P0.5 tests passed instead of xfail.
  Output and top-level artifact_refs may both include the same produced artifact; QA dedupes by artifact_id and still requires one unique produced artifact.
```

Validation:

```text
py -m pytest tests/test_asset_index_delivery_contract.py -q
3 passed

py -m pytest tests -q
25 passed, 9 skipped

$env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
probe failed gracefully on host without ffprobe; asset_index, project_edit, preview marker, and delivery_manifest succeeded

docker compose run --rm toolkit pytest tests -q
28 passed, 6 skipped

docker compose run --rm toolkit video-toolkit-demo
probe, asset_index, project_edit, preview marker, and delivery_manifest succeeded
```

Next dependencies:

```text
1. Preserve caller-safe AssetIndex/Delivery public payloads: no storage_uri, local paths, raw commands, or local-artifact:// values.
2. Keep produced artifact types stable: asset_index/asset_index_json, delivery_manifest/delivery_manifest_json, package_manifest/package_manifest_json.
3. Add schema-level assertions for asset_index and delivery/package manifests after output schemas are finalized.
```

## P0.6 Artifact Manifest Schema Run

Status: completed.

Active ownership:

```text
P0.6 Schema Worker
schemas/, tests/, docs/qa-release.md, docs/subagent-run-2026-05-07.md

Parallel worker
agentctl CLI, pyproject.toml
```

Target:

```text
1. Add verifiable JSON Schema contracts for generated asset_index, delivery_manifest, and package_manifest artifact files.
2. Validate schema contracts against artifacts generated through LocalRunService and LocalArtifactStore, not hand-authored fixtures.
3. Continue enforcing the public boundary: no local paths, raw commands, storage_uri, or local-artifact:// values in caller-facing responses.
4. Avoid CLI and pyproject changes while a parallel worker owns agentctl CLI work.
```

Result:

```text
Schema:
  Added schemas/artifact-manifests.schema.json.
  Top-level schema accepts asset_index_manifest, delivery_manifest, or package_manifest.
  Defs cover public_artifact_ref, asset_index_manifest, delivery_manifest, package_manifest, public_artifact_refs, variant_plan, and variant.
  public_artifact_ref rejects storage internals by using additionalProperties=false and only allowing caller-safe ref fields.

QA:
  Added tests/test_artifact_manifest_schema_contract.py.
  Tests create real dummy media/audio/json artifacts through LocalArtifactStore.
  Tests run AssetIndexAdapter and DeliveryAdapter through LocalRunService registered P0 handlers.
  Tests read the generated internal artifact JSON files back from LocalArtifactStore and validate them with jsonschema.
  Tests also scan public RunResponse payloads for storage/path/command/local-artifact leakage.

Coordination:
  No CLI files were changed.
  pyproject.toml was read to confirm jsonschema is already a dev dependency, but was not modified.
```

Validation:

```text
py -m pytest tests/test_artifact_manifest_schema_contract.py -q
2 passed

py -m pytest tests/test_manifest_schema_contract.py -q
4 passed

py -m pytest tests -q
30 passed, 9 skipped

docker compose run --rm toolkit pytest tests -q
35 passed, 4 skipped
```

Next dependencies:

```text
1. Keep generated manifest schema identifiers stable for P0 consumers.
2. Update schema and generated-artifact tests together if Delivery variants gain new non-scalar fields.
3. Wire these artifact-manifest schema checks into any future agentctl/CI gate owned by the CLI worker.
```

## P0.6 Agentctl Bridge Run

Status: completed.

Active ownership:

```text
P0.6 Agentctl Bridge Worker
src/video_editing_toolkit/agentctl.py, pyproject.toml, tests/, docs/runtime-api.md, README.md, docs/agentctl-platform-core.md

Parallel worker
schemas/, artifact manifest schema tests
```

Target:

```text
1. Add a lightweight local command surface that mirrors the future agentctl run envelope.
2. Support JSON input via --input-json and stdin.
3. Create LocalArtifactStore, LocalRunService, and registered P0 handlers in-process.
4. Return caller-safe queued/processed public runtime payloads.
5. Keep P0.6 local-only with no Platform Core client, network call, or external upload path.
```

Result:

```text
CLI:
  Added video_editing_toolkit.agentctl.
  Added video-toolkit-agentctl console script.
  Supports optional --artifact-root.
  Supports top-level artifact_ids/artifact_refs as local handoff metadata.

Runtime bridge:
  Builds a RunRequest from the JSON envelope.
  Uses submit_public and process_next_public.
  Structured no-upload capabilities such as create_project and generate_variants succeed locally.
  Unknown capabilities return stable handler_not_registered failure.

Public boundary:
  Output does not echo the raw request.
  storage_uri, local paths, worker-only fields, raw commands, and credential-like keys are stripped or redacted.
```

Validation:

```text
py -m pytest tests/test_agentctl_cli_contract.py -q
3 passed

py -m pytest tests/test_artifact_manifest_schema_contract.py tests/test_agentctl_cli_contract.py -q
5 passed

py -m pytest tests -q
30 passed, 9 skipped

$env:PYTHONPATH='src'; py -m video_editing_toolkit.agentctl --input-json <generate_variants request>
succeeded with caller-safe JSON and no local path/private-field leakage

docker compose build toolkit
image rebuilt with video-toolkit-agentctl console script

docker compose run --rm toolkit pytest tests -q
35 passed, 4 skipped

docker compose run --rm toolkit video-toolkit-agentctl --input-json <generate_variants request>
succeeded with caller-safe JSON and no workspace/tmp/private-field leakage
```

Next dependencies:

```text
1. Keep P0.6 bridge local-only until Platform Core authz, queue, artifact service, and trace mapping are explicit.
2. Add real file-upload or artifact materialization only with a matching artifact policy and leakage tests.
3. Use docs/agentctl-platform-core.md as the handoff map when replacing local service pieces with Platform Core clients.
```

## P0.7 FFmpeg Render / Local HTTP API Run

Status: completed.

Active ownership:

```text
P0.7 FFmpeg/Render Worker
src/video_editing_toolkit/adapters/ffmpeg.py, tests/test_ffmpeg_render_outputs.py, docs/adapters.md, docs/docker.md

P0.7 Local HTTP API Worker
src/video_editing_toolkit/local_api.py, pyproject.toml, tests/test_local_api_contract.py, docs/runtime-api.md, README.md, docs/local-api.md
```

Target:

```text
1. Move normalize_asset, video.render.render_preview, and video.render.render_final from adapter.not_implemented to real P0 output artifacts.
2. Preserve stable adapter.unavailable behavior on hosts without ffmpeg/ffprobe.
3. Add the development-plan section 9 local HTTP endpoints.
4. Keep FastAPI/uvicorn optional through the api extra.
5. Preserve public output safety for FFmpeg/render and HTTP API responses.
```

Result:

```text
FFmpeg/render:
  normalize_asset outputs normalized_video MP4 artifacts.
  video.render.render_preview outputs preview_video MP4 artifacts with bounded preview options.
  video.render.render_final outputs final_render MP4 artifacts.
  Docker default worker validates real MP4 outputs with ffprobe.

Local HTTP API:
  Added video_editing_toolkit.local_api and video-toolkit-local-api.
  POST /local/toolkit-runs accepts the agentctl-like envelope and synchronously processes one run by default.
  GET /local/toolkit-runs/{run_id} returns public run status.
  GET /local/artifacts/{artifact_id} returns public metadata already seen by the API process.
  GET /local/manifests returns manifest payloads with file names only, not filesystem paths.

Public boundary:
  No raw commands, local paths, stdout/stderr, storage_uri, local-artifact:// values, or credential-like keys in public responses.
```

Validation:

```text
py -m compileall src
passed

py -m pytest tests/test_ffmpeg_render_outputs.py tests/test_local_api_contract.py -q
8 passed, 3 skipped

py -m pytest tests -q
38 passed, 12 skipped

$env:PYTHONPATH='src'; py -m video_editing_toolkit.local_api --help
help rendered successfully

$env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
probe failed gracefully on host without ffprobe; delivery_manifest succeeded; no public path/private-field leakage

docker compose build toolkit
image rebuilt with video-toolkit-local-api console script

docker compose run --rm toolkit pytest tests/test_ffmpeg_render_outputs.py -q
6 passed

docker compose run --rm toolkit pytest tests -q
41 passed, 5 skipped

docker compose run --rm toolkit video-toolkit-local-api --help
help rendered successfully

docker compose run --rm toolkit video-toolkit-demo
probe and delivery_manifest succeeded; no workspace/tmp/private-field leakage
```

Next dependencies:

```text
1. Replace P0.7 single-input render with timeline/project compositor only after render_config and timeline artifact contracts are explicit.
2. Add optional API Docker/profile validation if the local HTTP API becomes an operator-facing service.
3. Keep artifact download, persistent run store, background queue, and authz out of the local API until Platform Core mapping is approved.
```

## P0.8 Release Candidate Contract Run

Status: completed.

Active ownership:

```text
P0.8 Project Artifact Worker
src/video_editing_toolkit/adapters/project_edit.py, src/video_editing_toolkit/project_edit/, src/video_editing_toolkit/runtime/adapter_handler.py, schemas/artifact-manifests.schema.json, tests/test_project_edit_artifact_contract.py, docs/project-edit.md, docs/adapters.md

P0.8 Manifest/Envelope QA Worker
tests/test_manifest_schema_contract.py, tests/test_local_api_contract.py, docs/release-gate.md, README.md
```

Target:

```text
1. Materialize timeline.json and render_config.json artifact contracts from project_edit.
2. Validate those artifacts through the generated artifact manifest schema.
3. Upgrade manifest refs from file-exists checks to JSON Pointer fragment checks.
4. Gate enabled manifest capabilities against runtime routes and handler registration.
5. Check agentctl and local HTTP API consistency for structured no-upload requests.
```

Result:

```text
Project artifacts:
  apply_timeline_patch writes timeline_json for the new version.
  apply_timeline_patch writes render_config_json when requested_preview is true.
  render_preview writes render_config_json for the requested version.
  timeline/render_config artifacts validate against schemas/artifact-manifests.schema.json.

Release gate:
  Manifest input/output schema refs resolve to schema files and #/$defs fragments.
  Enabled manifest capabilities match CAPABILITY_ROUTES and register_p0_adapter_handlers.
  agentctl and local API no-upload requests stay behaviorally aligned after normalization.
  docs/release-gate.md records P0.8 blockers and explicit non-blockers.
```

Validation:

```text
py -m compileall src
passed

py -m pytest tests/test_project_edit_artifact_contract.py tests/test_artifact_manifest_schema_contract.py tests/test_manifest_schema_contract.py tests/test_agentctl_cli_contract.py tests/test_local_api_contract.py -q
17 passed

py -m pytest tests/test_runtime_adapter_integration.py tests/test_timeline_patch_fixtures.py -q
8 passed, 1 skipped

py -m pytest tests -q
41 passed, 12 skipped

$env:PYTHONPATH='src'; py -m video_editing_toolkit.demo
probe failed gracefully on host without ffprobe; timeline/render_config/delivery artifacts succeeded; no public path/private-field leakage

docker compose build toolkit
image rebuilt

docker compose run --rm toolkit pytest tests/test_project_edit_artifact_contract.py tests/test_manifest_schema_contract.py -q
6 passed

docker compose run --rm toolkit pytest tests -q
43 passed, 5 skipped

docker compose run --rm toolkit video-toolkit-demo
probe, timeline/render_config artifacts, and delivery_manifest succeeded; no workspace/tmp/private-field leakage
```

Next dependencies:

```text
1. Review P0.8 as the local P0 release-candidate baseline before starting P1 capability work.
2. Keep full timeline compositor, persistent queue, Platform Core authz, object storage downloads, and production tracing as post-P0 platformization work.
3. Start P1 only after deciding which first enhanced capability to pursue: MOSS-TTS-Nano, QC, Remotion, diarization, or clone_voice approval flow.
```

## P0.9 Agentctl Docker Pre-Integration Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/agentctl_remote.py, pyproject.toml, tests/test_agentctl_remote_probe_contract.py, docs/

Schrodinger
Read-only exploration of local Docker agentctl API candidates and risk boundaries
```

Target:

```text
1. Decide whether local Docker agentctl should be pre-connected before P1.
2. Verify agentctl health, OpenAPI, tool catalog, RunSpec validation, and runtime worker protocol.
3. Register the video toolkit manifest as a draft tool-catalog entry only as an explicit operator action.
4. Confirm performance posture: heavy video workloads stay in a standalone toolkit worker, not inside agentctl.
```

Result:

```text
Remote probe:
  Added video_editing_toolkit.agentctl_remote.
  Added video-toolkit-agentctl-remote console script.
  Default probe checks health, openapi, tool catalog, runtime backends, worker protocol, and jobs without mutation.

Tool catalog:
  Manifest-backed draft payload exposes 23 P0 capabilities.
  Explicit --register posts the draft tool catalog entry to local Docker agentctl.

RunSpec:
  Explicit --validate-runspec posts a no-upload RunSpecDraft for video.project_edit.create_project.
  Local Docker agentctl accepts the draft with valid=true.

Worker protocol:
  Explicit --worker-smoke posts a short heartbeat and idle lease probe.
  No video job is executed.

Performance decision:
  connect_now=true for control-plane shape.
  promote_to_p1=false.
  run_heavy_media_inside_agentctl=false.
  deployment_model=standalone_video_toolkit_worker.
```

Validation:

```text
py -m compileall src
passed

py -m pytest tests/test_agentctl_remote_probe_contract.py -q
6 passed, 1 skipped

$env:PYTHONPATH='src'; $env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'; py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765
ok=true

py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --validate-runspec
valid=true

py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --worker-smoke
heartbeat_ok=true, lease_ok=true

py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --register
draft tool catalog entry accepted
```

Next dependencies:

```text
1. Implement an external video worker loop for agentctl heartbeat, lease, execute, and complete before using queued media runs.
2. Keep Docker/runtime backend enablement and resource isolation separate from agentctl control-plane deployment.
3. Do not use /runs, in-process /runspecs/run, or Product Adapter learning endpoints for P0.9 media execution.
```

## P0.10 Agentctl Runtime Worker Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/agentctl_worker.py, pyproject.toml, tests/test_agentctl_worker_contract.py, docs/

Rawls
Read-only exploration of runtime dispatch job and completion protocol
```

Target:

```text
1. Implement a standalone video toolkit worker loop for agentctl heartbeat, lease, execute, and complete.
2. Use the existing local agentctl-compatible toolkit envelope for no-upload capability execution.
3. Add an explicit enqueue probe that creates one RunSpec dispatch job and consumes it through the external worker.
4. Preserve the performance boundary: no heavy media execution inside agentctl.
```

Result:

```text
Worker:
  Added video_editing_toolkit.agentctl_worker.
  Added video-toolkit-agentctl-worker console script.
  Supports --once, --max-jobs, and --enqueue-probe.

Protocol:
  POST heartbeat registers worker metadata.
  POST lease obtains one queued runtime job.
  Local run_agentctl executes the toolkit envelope.
  POST complete sends completed/failed result back to agentctl.

Traceability:
  Runtime job_id becomes local toolkit run_id when absent.
  Runtime lease_id becomes local toolkit tool_call_id when absent.

Live smoke:
  /runspecs/run with dispatch_mode=enqueue queued a no-upload project-create job.
  The external worker leased and completed the job successfully.
```

Validation:

```text
py -m compileall src
passed

py -m pytest tests/test_agentctl_worker_contract.py tests/test_agentctl_remote_probe_contract.py -q
13 passed, 2 skipped

$env:PYTHONPATH='src'; $env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'; py -m video_editing_toolkit.agentctl_worker --base-url http://127.0.0.1:8765 --worker-id video-toolkit-live-p010 --backend-id local --lease-seconds 30 --ttl-seconds 60 --enqueue-probe
status=completed
```

Next dependencies:

```text
1. Add artifact-service-backed worker materialization before running FFmpeg/OpenCV/Whisper/render jobs from queued agentctl jobs.
2. Enable isolated Docker or remote backend for heavy media execution.
3. Add cancellation, retry, quota, timeout, and trace propagation for non-trivial media jobs.
```

## P0.11 Artifact Materialization Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/storage/, src/video_editing_toolkit/agentctl_worker.py, tests/, docs/

Erdos
Read-only exploration of artifact_ref, LocalArtifactStore, and worker materialization boundaries
```

Target:

```text
1. Materialize queued job artifact_refs before local worker execution.
2. Preserve Platform artifact_id safely so runtime adapter resolution continues to work.
3. Reject unsafe download sources and path traversal ids.
4. Verify size_bytes and sha256 before local adapter execution.
5. Keep failure diagnostics caller-safe.
```

Result:

```text
Storage:
  LocalArtifactStore now validates artifact_id before directory access.
  put_bytes and put_file can preserve an explicitly supplied safe artifact_id.
  open_local_path and delete return safe misses for invalid ids.

Materialization:
  Added video_editing_toolkit.storage.materialize.
  The materializer selects top-level artifact_refs needed by the input.
  Relative download_url values resolve against artifact_base_url.
  Absolute download_url values must be same-origin.
  storage_uri is ignored as a download source.
  Content is bounded by max_artifact_bytes and verified against size_bytes and sha256.

Worker:
  agentctl_worker now materializes artifacts between lease envelope coercion and run_agentctl.
  CLI supports --artifact-base-url and --max-artifact-bytes.
  Failures complete as video_toolkit_worker.artifact_materialization_failed with a stable reason_code.
```

Validation:

```text
py -m pytest tests/test_artifact_materialization_contract.py -q
6 passed

py -m pytest tests/test_agentctl_worker_contract.py -q
9 passed, 1 skipped

py -m compileall src
passed

py -m pytest tests -q
62 passed, 14 skipped

docker compose run --rm toolkit pytest tests -q
64 passed, 7 skipped
```

Next dependencies:

```text
1. Add a live byte-service smoke only after Platform Core or compatible artifact service exposes a bytes endpoint.
2. Add resource-limited Docker/remote media execution for heavier artifact-dependent jobs.
3. Add cancellation, retry, quota, timeout, and trace propagation for non-trivial media jobs.
```

## P0.12 Worker Resource Policy Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/agentctl_worker.py, src/video_editing_toolkit/agentctl_worker_policy.py, tests/, docs/

Poincare
Read-only exploration of resource_guard, CAPABILITY_ROUTES, and worker execution preflight
```

Target:

```text
1. Reuse existing CAPABILITY_ROUTES resource limits at the external worker boundary.
2. Keep generic worker default safe by accepting only cpu_light routes.
3. Add explicit allowed_resource_classes and allowed_capabilities configuration.
4. Reject unknown capability, disallowed resource class, oversized declared inputs, and route timeout mismatch before downloading bytes.
5. Keep failures caller-safe and stable.
```

Result:

```text
Worker policy:
  Added video_editing_toolkit.agentctl_worker_policy.
  Unknown capabilities fail before materialization/execution.
  allowed_capabilities narrows the worker when configured.
  allowed_resource_classes defaults to cpu_light.
  max_job_input_bytes checks declared artifact size_bytes.
  max_run_timeout_seconds checks route timeout_seconds.

Worker:
  agentctl_worker validates execution policy before materialize_artifact_refs.
  CLI supports --allowed-resource-classes, --allowed-capabilities, --max-job-input-bytes, and --max-run-timeout-seconds.
  Heartbeat metadata advertises the worker policy.
  Policy failures complete as video_toolkit_worker.execution_policy_rejected with a stable reason_code.
```

Validation:

```text
py -m pytest tests/test_agentctl_worker_contract.py -q
15 passed, 1 skipped

py -m compileall src
passed

py -m pytest tests -q
68 passed, 14 skipped

docker compose run --rm toolkit pytest tests -q
70 passed, 7 skipped
```

Next dependencies:

```text
1. Add hard cancellation/kill only with process isolation or remote worker backend.
2. Add a live byte-service smoke once Platform Core artifact bytes endpoint exists.
3. Add retry, quota, and trace propagation for non-trivial media jobs.
```

## P0.13 Subprocess Execution Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/agentctl_worker.py, src/video_editing_toolkit/agentctl_worker_runner.py, tests/, docs/

Ohm
Read-only exploration of agentctl CLI subprocess boundaries and Windows/Docker risks
```

Target:

```text
1. Add optional subprocess execution without changing the local agentctl envelope contract.
2. Preserve default in-process execution for compatibility.
3. Send envelope over stdin, not argv.
4. Normalize timeout and subprocess failures into stable caller-safe worker errors.
5. Preserve run_id/tool_call_id traceability across subprocess execution.
```

Result:

```text
Runner:
  Added video_editing_toolkit.agentctl_worker_runner.
  Supports in_process and subprocess execution modes.
  subprocess mode invokes sys.executable -m video_editing_toolkit.agentctl with shell=False.
  subprocess mode passes only --artifact-root through argv and sends the envelope over stdin.
  timeout, no-output, invalid-JSON, and startup failures map to stable WorkerLocalExecutionError classes.

Worker:
  VideoToolkitWorkerConfig now has execution_mode.
  CLI supports --execution-mode in_process|subprocess.
  heartbeat metadata advertises execution_mode.
  execute_job uses the local runner after policy preflight and artifact materialization.
  timeout failures complete as video_toolkit_worker.execution_timeout.
```

Validation:

```text
py -m pytest tests/test_agentctl_worker_runner_contract.py tests/test_agentctl_worker_contract.py -q
20 passed, 1 skipped

py -m compileall src
passed

py -m pytest tests -q
73 passed, 14 skipped

docker compose run --rm toolkit pytest tests -q
75 passed, 7 skipped
```

Next dependencies:

```text
1. Run full host and Docker suites as the P0.13 release gate.
2. Add remote/Docker execution pools for real CPU-heavy and GPU-optional workloads.
3. Add cancellation, retry, quota, and trace propagation for non-trivial media jobs.
```

## P0.14 Worker Lifecycle Control Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/agentctl_worker.py, src/video_editing_toolkit/agentctl_worker_runner.py,
src/video_editing_toolkit/runtime/, src/video_editing_toolkit/agentctl.py,
src/video_editing_toolkit/local_api.py, tests/, docs/

Locke
Read-only exploration of runtime trace, usage, status, and cancel contracts

Archimedes
Read-only exploration of worker failure payload, QA, and release-gate coverage
```

Target:

```text
1. Register the next execution backend shape without enabling heavy Docker/remote pools.
2. Propagate agentctl trace_id into local toolkit trace_ref.
3. Add worker completion metadata for trace, usage, execution backend, attempts, and retry policy.
4. Reject jobs above max_attempts before materialization or local execution.
5. Skip cancel-requested jobs before materialization or local execution.
6. Expose queued-run cancellation in the local development API.
7. Harden generic worker failure payloads against local path, URL, argv, stderr, env, and token leakage.
```

Result:

```text
Execution backend:
  Registered in_process, subprocess, docker, and remote.
  in_process and subprocess remain executable.
  docker and remote fail with video_toolkit_worker.execution_backend_unavailable until real pools exist.

Worker lifecycle:
  Heartbeat advertises execution_backend, supported backends, max_attempts, retry_policy, cancel_contract, and lifecycle contract.
  Completion metadata includes trace_ref, usage_metrics, execution_backend, attempt, max_attempts, and retry_policy.
  attempts > max_attempts fails before materialization/local execution.
  cancel_requested/cancelled/cancelling jobs fail with video_toolkit_worker.execution_cancelled before materialization/local execution.

Runtime/API:
  RunRequest accepts trace_ref.
  agentctl trace_id/trace_ref is preserved through local runtime responses.
  Local API exposes POST /local/toolkit-runs/{run_id}/cancel for queued local runs.

Safety:
  Subprocess tests assert envelope stays on stdin, not argv.
  Generic worker exception details are redacted before completion.
  Shared public leakage scanner now rejects credential-like public keys.
```

Validation:

```text
py -m pytest tests/test_agentctl_worker_runner_contract.py tests/test_agentctl_worker_contract.py tests/test_local_api_contract.py -q
32 passed, 1 skipped

py -m compileall src
passed

py -m pytest tests -q
79 passed, 14 skipped

docker compose run --rm toolkit pytest tests -q
80 passed, 7 skipped
```

Next dependencies:

```text
1. Implement real Docker/remote execution-pool adapters before enabling CPU-heavy/GPU-optional production workloads.
2. Add live byte-service smoke once Platform Core or a compatible artifact service exposes an authorized bytes endpoint.
3. Add production retry scheduling, in-flight cancellation, quota accounting, and resource isolation outside the P0.14 skeleton.
```

## P0.15 Platform Core Handoff Interface Run

Status: completed.

Active ownership:

```text
Main orchestrator
src/video_editing_toolkit/platform_core.py, pyproject.toml, tests/, docs/
```

Target:

```text
1. Reserve Platform Core handoff interfaces without calling a live Platform Core service.
2. Generate a Tool Catalog / Platform Core descriptor from the P0 manifest.
3. Normalize future Platform Core run requests into the existing local agentctl envelope.
4. Normalize local agentctl/worker results into Platform Core completion payloads.
5. Preserve artifact_ref_only, trace, usage, run id, and tool call id contracts.
6. Keep storage_uri, local paths, raw commands, argv, stderr, env, and credentials out of handoff payloads.
```

Result:

```text
Platform Core module:
  Added video_editing_toolkit.platform_core.
  Added video-toolkit-platform-core console script.
  build_platform_core_toolkit_descriptor() reads the P0 manifest and emits handoff metadata.
  platform_core_envelope_to_agentctl() maps platform_run_id/tool_call_id/trace_id/policy/artifacts to local agentctl.
  build_platform_core_completion() maps local results back to Platform Core completion shape.

Docs:
  README and docs/agentctl-platform-core.md document P0.15 handoff usage.
  release gate and QA snapshot now include P0.15 blockers and verification.
```

Validation:

```text
py -m pytest tests/test_platform_core_handoff_contract.py -q
4 passed

py -m compileall src
passed

py -m pytest tests -q
83 passed, 14 skipped

docker compose run --rm toolkit pytest tests -q
84 passed, 7 skipped
```

Next dependencies:

```text
1. Add a live Platform Core artifact byte-service smoke only after an authorized byte endpoint exists.
2. Keep Product Adapter onboarding, learning/audit ingestion, and release-center publishing as P1/P2.
3. Implement real Docker/remote execution-pool adapters before enabling production CPU-heavy/GPU-optional media workloads.
```
