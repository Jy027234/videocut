# Project Edit P0 Core

The P0 project edit implementation is dependency-free and runs in memory. It
validates declarative `timeline_patch` payloads, applies registered timeline
operations, keeps project versions for the current process, compares versions,
and creates rollback versions.

## Allowed Operations

- `add_clip`
- `remove_clip`
- `split_clip`
- `move_clip`
- `set_in_out`
- `add_text`
- `add_audio`
- `set_transition`
- `set_effect`

Patch operations reject command-like keys at any nesting level:
`script`, `command`, `shell`, `expression`, `eval`, `exec`, `raw_command`,
and `ffmpeg_command`.

## Core API

- `validate_timeline_patch(request)` returns copied operations or raises a
  stable validation error.
- `apply_timeline_patch(request)` creates a new project version from
  `base_version_id`.
- `compare_versions(request)` returns added, removed, and changed clip summary.
- `rollback_version(request)` creates a new latest version from a previous
  `target_version_id`.

`ProjectEditAdapter` maps all `video.project_edit.*` capabilities to these core
functions. Successful calls return `succeeded`; stable project-edit failures
return `request.invalid` with `output.stable_error_code` such as
`invalid_schema`, `conflict`, or `unregistered_effect`.

## P0.8 Project Artifacts

`ProjectEditAdapter` now materializes project-edit JSON artifacts through
`LocalArtifactStore`:

- Successful `video.project_edit.apply_timeline_patch` writes `timeline.json`
  for the new version and returns `timeline_artifact_ref`.
- When the patch includes `requested_preview: true`, the same call also writes
  `render_config.json` and returns `render_config_artifact_ref`.
- `video.project_edit.render_preview` writes `render_config.json` for the
  requested project version and returns `render_config_artifact_ref`.

The persisted contracts are validated by
`schemas/artifact-manifests.schema.json`:

- `video_editing_toolkit.project_timeline.v0` stores `project_id`,
  `version_id`, `parent_version_id`, `change_reason`, `created_by_run_id`,
  `timeline_summary`, and the structured `timeline` object.
- `video_editing_toolkit.render_config.v0` stores `project_id`, `version_id`,
  `render_target: preview`, `timeline_summary`, optional
  `source_timeline_artifact_ref`, and a structured preview `render_config`.

Caller-facing outputs expose only artifact refs. They do not expose local file
paths, `storage_uri`, raw commands, stdout/stderr, or worker URLs. The internal
artifact filenames remain `timeline.json` and `render_config.json`.

## Chain Demo Role

In the local chain, project edit is the first fully dependency-free stage
after media ingest:

```text
create_project -> apply_timeline_patch -> render_preview
```

`create_project` returns the base `version_id` used by
`apply_timeline_patch`. The demo patch adds one clip using only an artifact ref
from the upload step; callers never need a local path. `requested_preview` on
the patch keeps returning the lightweight `preview_artifact_ref` marker for
compatibility and now also returns a real `render_config_artifact_ref`. The
explicit `video.project_edit.render_preview` step returns the same caller-safe
preview marker plus a fresh `render_config_artifact_ref` for the version.

This preview is a Platform Core placeholder contract, not a final media render.
When the render worker behind `video.render.render_preview` is implemented,
agentctl can map the same project id and version id into that worker capability
without changing the project-edit patch or artifact format.
