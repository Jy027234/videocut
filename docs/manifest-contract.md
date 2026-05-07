# Video Editing Toolkit Manifest Contract

Status: P0 draft

Owner: toolkit-manifest-agent

## Scope

This contract defines the P0 Tool Catalog shape for `video-editing-toolkit`. It covers manifest fields, capability I/O schema references, data sensitivity labels, approval policy, artifact policy, and stable error code conventions.

The toolkit must not expose local disk paths to agents or upstream callers. Large files and structured evidence are exchanged through `artifact_ref`.

## Required Manifest Fields

`toolkit_id`: Stable toolkit identifier. P0 value is `video-editing-toolkit`.

`capability`: Dot-delimited capability identifier, for example `video.render.render_preview`.

`version`: Semver-compatible toolkit or capability version. P0 uses `0.1.0-p0`.

`input_schema`: JSON Schema reference for the toolkit run envelope or capability-specific input.

`output_schema`: JSON Schema reference for the toolkit run envelope or capability-specific output.

`data_sensitivity`: One of `low`, `medium`, `high`, or `restricted`. P0 enables only `low` and `medium`.

`approval_policy`: One of `none`, `confirm`, `approval_required`, or `disabled`.

`artifact_policy`: One of `metadata_only`, `artifact_ref_required`, `preview_short_retention`, or `final_retention`.

`error_codes`: Capability-level string codes plus top-level code definitions with retry guidance.

## P0 Capabilities

Low sensitivity:

- `video.asset_ingest.probe_media`
- `video.asset_ingest.normalize_asset`
- `video.asset_ingest.extract_audio`
- `video.asset_ingest.extract_frames`
- `video.asset_ingest.build_asset_index`
- `video.analysis.detect_scenes`
- `video.analysis.analyze_frames`
- `video.analysis.check_visual_quality`
- `audio.speech.check_audio_quality`
- `video.project_edit.render_preview`
- `video.render.render_preview`

Medium sensitivity:

- `audio.speech.transcribe`
- `audio.speech.align_subtitles`
- `video.project_edit.create_project`
- `video.project_edit.inspect_assets`
- `video.project_edit.generate_edit_plan`
- `video.project_edit.apply_timeline_patch`
- `video.project_edit.compare_versions`
- `video.project_edit.rollback_version`
- `video.render.render_final`
- `video.delivery.generate_variants`
- `video.delivery.package_artifacts`
- `video.delivery.create_delivery_manifest`

P0 does not enable high or restricted capabilities such as face detection, speaker diarization, voiceover generation, voice cloning, template rendering, or professional project export.

## Artifact Contract

Returned file-like outputs must use `artifact_ref`. The P0 schema reserves these fields:

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

`storage_uri` is internal-only. External callers receive `artifact_id` and controlled access URLs from the artifact service, not raw local paths.

## Approval Rules

P0 defaults to `none`.

The following P0 capabilities require explicit confirmation because they can increase cost, retention, or delivery blast radius:

- `video.render.render_final`
- `video.delivery.package_artifacts`
- `video.delivery.create_delivery_manifest`

High and restricted capabilities are disabled until a security review defines approval fields, consent policy, retention, and audit requirements.

## Error Code Rules

Top-level error definitions are stable cross-capability codes:

- `VALIDATION_FAILED`
- `ARTIFACT_NOT_FOUND`
- `ARTIFACT_ACCESS_DENIED`
- `APPROVAL_REQUIRED`
- `RESOURCE_LIMIT_EXCEEDED`
- `WORKER_UNAVAILABLE`
- `WORKER_FAILED`
- `POLICY_VIOLATION`

Capability-level codes may add adapter-specific detail, but must remain uppercase snake case and should map back to one of the top-level categories for platform reporting.

## Example Run Envelope

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.asset_ingest.probe_media",
  "version": "0.1.0-p0",
  "input": {
    "artifact_ref": {
      "artifact_id": "art_123",
      "artifact_type": "source_video",
      "owner_tenant_id": "tenant_abc",
      "created_by_run_id": "run_001",
      "mime_type": "video/mp4",
      "size_bytes": 1048576,
      "checksum": {
        "algorithm": "sha256",
        "value": "example"
      },
      "data_class": "medium",
      "retention_policy": "default_7d",
      "access_policy": "tenant_and_explicit_grants"
    }
  },
  "context": {
    "tenant_id": "tenant_abc",
    "run_id": "run_002",
    "tool_call_id": "call_001"
  }
}
```

```json
{
  "toolkit_id": "video-editing-toolkit",
  "capability": "video.asset_ingest.probe_media",
  "version": "0.1.0-p0",
  "trace_id": "trace_001",
  "usage_metrics": {
    "input_bytes": 1048576,
    "media_duration_seconds": 12.5,
    "worker_cpu_seconds": 0.42
  },
  "artifact_refs": []
}
```
