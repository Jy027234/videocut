# Adapter Contract

P0 adapter layer is an internal worker boundary for video-editing-toolkit. It
maps agent-visible capabilities to structured worker adapters without exposing
raw shell, raw ffmpeg command strings, internal worker addresses, or local file
paths.

## Base Contract

Core classes live in `src/video_editing_toolkit/adapters/base.py`.

- `AdapterContext`: identity, policy, and trace envelope with `tenant_id`,
  `project_id`, `run_id`, `tool_call_id`, `capability`, and `version`.
- `ArtifactRef`: stable cross-boundary artifact handle. Large media outputs
  must be returned as artifact refs, not local paths.
- `AdapterRequest`: structured input, input artifact refs, and optional
  resource limits.
- `AdapterResult`: structured status, output metadata, artifact refs, usage
  metrics, trace ref, and stable error fields.
- `BaseAdapter`: common `supports()`, `describe()`, and `handle()` contract.
- `PlaceholderAdapter`: fallback P0 implementation that advertises capability
  ownership and returns `adapter.not_implemented` until real worker execution
  lands.

Adapter implementations expose capability methods such as `probe_media()` or
`transcribe()`. They do not accept arbitrary command arguments.

## P0 Adapters

| Adapter | Class | P0 capabilities |
| --- | --- | --- |
| FFmpeg | `FFmpegAdapter` | `video.asset_ingest.probe_media`, `video.asset_ingest.normalize_asset`, `video.asset_ingest.extract_audio`, `video.asset_ingest.extract_frames`, `video.render.render_preview`, `video.render.render_final` |
| Asset index | `AssetIndexAdapter` | `video.asset_ingest.build_asset_index` |
| PySceneDetect | `PySceneDetectAdapter` | `video.analysis.detect_scenes` |
| OpenCV | `OpenCVAdapter` | `video.analysis.analyze_frames`, `video.analysis.check_visual_quality` |
| Whisper | `WhisperAdapter` | `audio.speech.transcribe`, `audio.speech.align_subtitles` |
| Audio quality | `AudioQualityAdapter` | `audio.speech.check_audio_quality` |
| Delivery | `DeliveryAdapter` | `video.delivery.generate_variants`, `video.delivery.package_artifacts`, `video.delivery.create_delivery_manifest` |
| Project edit | `ProjectEditAdapter` | `video.project_edit.create_project`, `video.project_edit.inspect_assets`, `video.project_edit.generate_edit_plan`, `video.project_edit.apply_timeline_patch`, `video.project_edit.render_preview`, `video.project_edit.compare_versions`, `video.project_edit.rollback_version` |

### FFmpeg Adapter

`FFmpegAdapter` is a controlled implementation instead of a raw command
wrapper.

- Capabilities map to private structured operations with declared binary
  requirements.
- `describe()` reports dependency status as `available` or `missing` for
  `ffmpeg` and `ffprobe`, plus the registered operation descriptors.
- Dependency detection uses `shutil.which()`. Missing required binaries return
  `AdapterResult(status=failed, error_code=ErrorCode.ADAPTER_UNAVAILABLE)`.
- The adapter never returns raw command strings, resolved executable paths,
  local media paths, stderr, stdout, or worker addresses.
- `probe_media()` is the first real execution capability. Runtime resolves an
  authorized input `artifact_ref` to a private worker-only path and the adapter
  calls a controlled `ffprobe` JSON probe internally when `ffprobe` is
  available.
- Probe output is sanitized before it crosses the adapter boundary. Local path
  fields such as `filename` are removed.
- `extract_audio()` runs a controlled `ffmpeg` audio extraction for `wav` and
  `m4a`, writes the worker output into `LocalArtifactStore`, and returns an
  `extracted_audio` artifact ref.
- `extract_frames()` runs a controlled `ffmpeg` frame extraction for `jpg`,
  `jpeg`, or `png`, limits P0 output to 1-10 frames, writes each frame into
  `LocalArtifactStore`, and returns `extracted_frames` artifact refs.
- `normalize_asset()` runs a controlled MP4 transcode and returns a
  `normalized_video` artifact ref.
- `render_preview()` runs a controlled preview MP4 transcode with bounded
  duration and height options, then returns a `preview_video` artifact ref.
- `render_final()` runs a controlled MP4 render path and returns a
  `final_render` artifact ref.
- The normalize/render paths prefer H.264 video plus AAC audio and fall back to
  a minimal MP4 video encode when the worker FFmpeg build lacks the preferred
  encoder. Unsupported or unreadable inputs return stable request failures
  without exposing command output.

The temporary private worker input key remains `_worker_media_path`. It is an
internal runtime-to-adapter field only. Agent-visible callers provide
`artifact_ref` handles; the local runtime resolves authorized refs through the
artifact store and does not return worker paths.

The local runtime also injects a private `_artifact_store` handle for FFmpeg
output materialization. This is stripped from caller input before invocation
and never appears in public responses.

### Asset Index And Delivery Adapters

`AssetIndexAdapter.build_asset_index()` provides the P0.5 asset handoff surface.
It builds an `asset_index` JSON artifact through `LocalArtifactStore` from the
caller `artifact_refs` plus runtime-resolved private worker inputs. The public
output includes `asset_count`, `asset_index_artifact_ref`, and public input
artifact metadata only.

`DeliveryAdapter` provides minimal structured delivery planning:

- `generate_variants()` returns a structured variant plan from requested
  variants, target, or preset. It does not materialize a file.
- `create_delivery_manifest()` materializes a `delivery_manifest` JSON artifact
  containing project id, version, variants, and public input artifact refs.
- `package_artifacts()` materializes a `package_manifest` JSON artifact in
  `manifest-only` mode. P0.5 does not create a zip archive; the manifest
  clearly declares that it only lists package inputs.

The local runtime injects a private `_artifact_store` handle for `asset_index`,
`delivery`, and FFmpeg materialization. Caller-supplied private keys are stripped
before invocation. Public outputs do not include local paths, raw commands,
storage URIs, stdout, stderr, or worker addresses.

### Project Edit Adapter

`ProjectEditAdapter` owns the dependency-free project editing surface. It
validates declarative `timeline_patch` operations, updates the in-memory
project version store, and returns stable `request.invalid` failures with
`output.stable_error_code` for invalid schemas, version conflicts, or
unregistered effects.

P0.8 adds project artifact materialization:

- `apply_timeline_patch()` writes `timeline.json` as a `timeline_json` artifact
  for the new version and returns `timeline_artifact_ref`.
- If the patch asks for `requested_preview`, it also writes
  `render_config.json` as a `render_config_json` artifact and returns
  `render_config_artifact_ref`.
- `render_preview()` writes `render_config.json` without invoking FFmpeg. It is
  a preview planning artifact, not a rendered MP4.

The local runtime injects the private `_artifact_store` handle for project edit
materialization. Public output includes caller-safe artifact refs only and never
includes local paths, `storage_uri`, raw command strings, stdout, stderr, or
worker URLs.

### Analysis Adapters

`PySceneDetectAdapter` and `OpenCVAdapter` now provide P0 real analysis when
their optional Python dependencies are installed.

- `PySceneDetectAdapter.detect_scenes()` requires the optional `scenedetect`
  package. Missing dependency returns `ErrorCode.ADAPTER_UNAVAILABLE`. With a
  resolved input artifact, it runs content-based scene detection and returns
  scene count plus per-scene start/end time, frame, duration, and timecode
  metadata.
- `OpenCVAdapter.check_visual_quality()` requires the optional `cv2` package.
  Missing dependency returns `ErrorCode.ADAPTER_UNAVAILABLE`. With a resolved
  image or video artifact, it samples visual frames and returns brightness,
  contrast, sharpness, dark pixel ratio, and bright pixel ratio metrics.
- `OpenCVAdapter.analyze_frames()` accepts one or more resolved frame artifact
  refs and returns the same per-frame metrics with a summary.

The local runtime resolves caller-supplied `artifact_ref`, `artifact_refs`,
`artifact_id`, or `artifact_ids` against the request artifact set and injects
private worker-only paths as `_worker_media_path` and `_worker_media_paths`.
Caller-supplied private keys are stripped before adapter invocation. Public
outputs do not include local paths, raw commands, storage URIs, stdout, stderr,
or worker addresses.

### Speech Adapters

`WhisperAdapter` now provides a minimal safe speech surface.

- `transcribe()` requires the optional `openai-whisper` package, imported as
  `whisper`, plus the `ffmpeg` binary used by Whisper to read media. Missing
  dependencies return `ErrorCode.ADAPTER_UNAVAILABLE`.
- Whisper model execution is disabled by default. Callers must pass
  `allow_model_run: true` or set `VET_ALLOW_WHISPER=1`.
- Runtime model downloads are disabled by default. If the requested model is
  not already present in the local Whisper cache, the adapter returns
  `ErrorCode.ADAPTER_UNAVAILABLE` unless callers pass
  `allow_model_download: true` or set `VET_ALLOW_WHISPER_DOWNLOAD=1`.
- `model`/`model_name`, `language`, `task`, and `temperature` are structured
  options. `VET_WHISPER_MODEL` selects the default model name or local model
  file, and `VET_WHISPER_MODEL_DIR` selects the cache root for worker
  deployments. `VIDEO_TOOLKIT_WHISPER_MODEL`, `WHISPER_MODEL`, local model path
  aliases, and `WHISPER_CACHE_DIR` are accepted for compatibility, but the
  `VET_*` names are the canonical adapter contract.
- Successful transcription returns sanitized `text`, `language`, `segments`,
  `segment_count`, and `model`. It never returns local paths, raw command
  details, storage URIs, stdout, or stderr.
- `align_subtitles()` is a pure local SRT formatter for supplied transcript
  `segments` or plain `text`/`transcript`. Plain text receives a local duration
  hint; it is not audio-forced alignment.

`AudioQualityAdapter.check_audio_quality()` provides lightweight P0 audio
quality checks.

- WAV/PCM inputs use Python's stdlib `wave` module and return duration,
  sample rate, channel count, peak/RMS amplitude, dBFS, clipping ratio, and
  silence ratio.
- Non-WAV audio or video inputs require `ffprobe` and return sanitized audio
  stream metadata plus a metadata-level summary.
- Non-WAV/video inputs without `ffprobe` return
  `ErrorCode.ADAPTER_UNAVAILABLE`.
- Public output is sanitized and does not include local paths, raw commands,
  storage URIs, stdout, or stderr.

## Capability Routing

Routing lives in `src/video_editing_toolkit/adapters/routing.py`.

| Capability | Adapter | Queue topic | Resource class |
| --- | --- | --- | --- |
| `video.asset_ingest.probe_media` | `ffmpeg` | `video.asset.probe` | `cpu_heavy` |
| `video.asset_ingest.normalize_asset` | `ffmpeg` | `video.asset.normalize` | `cpu_heavy` |
| `video.asset_ingest.extract_audio` | `ffmpeg` | `video.asset.normalize` | `cpu_heavy` |
| `video.asset_ingest.extract_frames` | `ffmpeg` | `video.asset.normalize` | `cpu_heavy` |
| `video.asset_ingest.build_asset_index` | `asset_index` | `video.asset.index` | `cpu_light` |
| `video.analysis.detect_scenes` | `pyscenedetect` | `video.analysis.scenedetect` | `cpu_heavy` |
| `video.analysis.analyze_frames` | `opencv` | `video.analysis.opencv` | `cpu_light` |
| `video.analysis.check_visual_quality` | `opencv` | `video.analysis.opencv` | `cpu_light` |
| `audio.speech.transcribe` | `whisper` | `audio.speech.whisper` | `gpu_optional` |
| `audio.speech.align_subtitles` | `whisper` | `audio.speech.whisper` | `gpu_optional` |
| `audio.speech.check_audio_quality` | `audio_quality` | `audio.speech.quality` | `cpu_light` |
| `video.project_edit.create_project` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.project_edit.inspect_assets` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.project_edit.generate_edit_plan` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.project_edit.apply_timeline_patch` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.project_edit.render_preview` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.project_edit.compare_versions` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.project_edit.rollback_version` | `project_edit` | `video.project_edit` | `cpu_light` |
| `video.render.render_preview` | `ffmpeg` | `video.render.preview` | `cpu_heavy` |
| `video.render.render_final` | `ffmpeg` | `video.render.final` | `cpu_heavy` |
| `video.delivery.generate_variants` | `delivery` | `video.delivery.package` | `cpu_light` |
| `video.delivery.package_artifacts` | `delivery` | `video.delivery.package` | `cpu_light` |
| `video.delivery.create_delivery_manifest` | `delivery` | `video.delivery.package` | `cpu_light` |

`resolve_route(capability)` returns the registered `CapabilityRoute`.
`build_adapter(capability)` returns a fresh adapter instance for the route.

P1 draft capabilities live behind explicit experimental routing helpers. They
must stay disabled in the manifest until Platform Core rollout policy, approval
gates, and resource limits are wired. The current P1 adapter surface is
preflight-only:

| Capability | Adapter | Contract status |
| --- | --- | --- |
| `audio.tts.generate_voiceover` | `moss_tts_nano` | `plan_only` and `preflight_only`; no download, no ONNX synthesis, no voice cloning. |
| `video.qc.generate_report` | `qc` | Deterministic report from caller-safe timeline, probe, quality, and brand evidence. |
| `video.qc.build_evidence_packet` | `qc` | Evidence packet descriptor and optional JSON artifact from caller-safe evidence only; no media inspection execution. |
| `video.qc.plan_media_inspection` | `qc` | Plan-only media inspection contract; no media fetch, binary probe, frame sampling, audio analysis, or visual analysis execution. |
| `video.template.validate_remotion_template` | `remotion` | Template metadata and prop validation only; no Node or Chromium execution. |
| `video.template.create_remotion_render_job` | `remotion` | Dispatcher job descriptor, typed dispatcher preflight attestation, and readiness checks only; no Remotion render execution. |
| `video.render.export_project_format` | `project_export` | FCPXML interchange descriptor or artifact only; no DaVinci Resolve, Final Cut Pro, shell, or local app automation. |

The MOSS-TTS-Nano preflight expects a local ONNX bundle root containing
`MOSS-TTS-Nano-100M-ONNX` and `MOSS-Audio-Tokenizer-Nano-ONNX`, or explicit TTS
and codec bundle paths. Public output reports only aggregate readiness and
missing file names, never the local bundle paths.

## Resource Limits

Resource primitives live in `src/video_editing_toolkit/resource_guard`.

- `ResourceClass`: `cpu_light`, `cpu_heavy`, `gpu_optional`, `gpu_required`.
- `ResourceLimits`: timeout, concurrency, input size, output size, media
  duration, memory, and GPU requirements.
- `validate_declared_usage()`: preflight helper for known request sizes.

Default P0 limit profiles:

| Profile | Timeout | Concurrency | Max input | Max output |
| --- | ---: | ---: | ---: | ---: |
| `CPU_LIGHT_LIMITS` | 120s | 8 | 512 MiB | 256 MiB |
| `CPU_HEAVY_LIMITS` | 900s | 2 | 4 GiB | 4 GiB |
| `GPU_OPTIONAL_LIMITS` | 1800s | 1 | 2 GiB | 512 MiB |

## Error Codes

Stable error codes live in `resource_guard/errors.py`.

| Code | Meaning |
| --- | --- |
| `adapter.not_implemented` | P0 placeholder registered but real worker logic is not implemented. |
| `adapter.unavailable` | Worker dependency or execution pool is unavailable. |
| `capability.unsupported` | Adapter received a capability it does not own. |
| `request.invalid` | Request envelope or structured input is invalid. |
| `artifact_ref.invalid` | Artifact handle cannot be parsed or resolved. |
| `artifact_ref.access_denied` | Artifact does not belong to the caller context or is not authorized. |
| `resource.limit_exceeded` | Generic resource guard failure. |
| `resource.timeout_exceeded` | Worker exceeded its timeout. |
| `resource.input_too_large` | Declared input exceeds the route limit. |
| `resource.output_too_large` | Expected output exceeds the route limit. |
| `resource.media_duration_too_long` | Declared media duration exceeds the route limit. |
| `resource.concurrency_limit_exceeded` | Route or pool concurrency limit is exhausted. |
| `internal.error` | Unexpected adapter failure. |

## Boundary Rules

- Agent-visible tools call capabilities, never adapters directly.
- Adapters receive structured inputs and artifact refs only.
- Adapters return artifact refs for large files and evidence artifacts.
- Raw shell strings, raw ffmpeg command strings, local paths, and internal
  worker addresses are not part of the public adapter contract.
- Runtime, storage, manifests, schemas, and tests own their own contracts and
  should integrate with this adapter layer through the classes above.
