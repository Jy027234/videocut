# Platform Core Platformization Metadata Contracts

Date: 2026-05-08

Status: implemented local metadata contracts for the next Platform Core
platformization slice. These contracts are metadata-only, review-only, and do
not perform network mutation.

## Scope

This document defines the metadata handoff contracts for moving the video
editing toolkit from local P0/P1 contract rehearsal toward Platform Core review.
They are implemented in `video_editing_toolkit.platform_core` and exposed by the
`video-toolkit-platform-core` CLI. It covers three payload families:

- onboarding bundle
- learning audit event
- release dossier

The contracts describe what a future Platform Core review flow may ingest. They
do not register tools, publish releases, execute capabilities, upload bytes,
modify Platform Core state, or change the Platform Core repository.

## Non-Goals

This slice must not:

- enable any P1 capability whose manifest status is `disabled`
- call Platform Core, agentctl, Studio, release-center, learning, audit, or
  artifact network APIs
- mutate Tool Catalog, RunSpec, release-center, approval, learning, audit, or
  artifact records
- write to the Platform Core repository
- bypass Platform Core authorization, review, approval, retention, or rollout
  controls
- include local filesystem paths, worker-only paths, raw commands, argv,
  stderr, environment values, `storage_uri`, signed URLs, provider tokens, or
  secret-like fields in review payloads

## Shared Metadata Rules

All three payload families must be safe to persist in docs, review artifacts,
or CI logs:

- `schema` identifies the shared handoff schema and `contract` identifies the
  payload family and version.
- `toolkit_id` must remain `video-editing-toolkit`.
- Timestamps, if required by Platform Core, should be added by the ingesting
  review process instead of inferred from media or local worker state.
- `source_manifest` should identify the manifest file and manifest version used
  to build the metadata.
- Capability entries must preserve manifest status. Disabled capabilities stay
  disabled in review metadata.
- Artifact references are metadata only. They may include caller-safe
  `artifact_id`, type, checksum, size, retention class, and controlled public
  handles, but never internal storage locations.
- Network posture must be explicit: `network_mutation` is `false` and
  `network_access` is `not_required` or `disabled_by_contract`.
- Review posture must be explicit: `review_only` is `true`.

## Onboarding Bundle

Contract name: `platform_core_toolkit_onboarding_bundle.v0`

Purpose: describe the toolkit to Product Adapter and Platform Core reviewers
without registering or activating it.

The onboarding bundle should contain:

- toolkit identity: id, display name, owner, version, and source manifest
- descriptor summary derived from the P0.15 Platform Core descriptor contract
- capability inventory with status, sensitivity, approval policy, artifact
  policy, resource class, and network posture
- disabled capability inventory for P1 draft routes and deferred
  high-sensitivity capabilities
- artifact contract summary, including `artifact_ref` expectations and
  `storage_uri` exclusion
- safety summary for caller-visible output redaction
- local verification references, not live Platform Core check results
- rollout notes explaining that activation requires separate Platform Core
  approval

Example shape:

```json
{
  "schema": "video_editing_toolkit.platform_core.handoff.v0",
  "contract": "platform_core_toolkit_onboarding_bundle.v0",
  "status": "review_only",
  "toolkit_id": "video-editing-toolkit",
  "source_manifest": {
    "path": "manifests/video-editing-toolkit.p1.manifest.json",
    "status": "draft"
  },
  "capability_sets": {
    "enabled": ["p0_manifest_enabled_routes"],
    "disabled": ["p1_manifest_disabled_routes"],
    "deferred_high_sensitivity": [
      "audio.tts.clone_voice",
      "audio.speech.diarize_speakers",
      "video.analysis.recognize_faces",
      "video.analysis.recognize_people"
    ]
  },
  "activation_policy": {
    "default_execution_enabled": false,
    "requires_platform_core_review": true,
    "preserve_disabled_status": true
  }
}
```

## Learning Audit Event

Contract name: `platform_core_learning_audit_event.v0`

Purpose: provide a metadata-only run event that a future learning/audit
ingestion path could use to review contract coverage, safety posture, usage
metrics, and artifact metadata without storing raw input or output content.

This is not a telemetry emitter. It must not send events to Platform Core or a
learning service from this repository.

The learning audit event should contain:

- run identity: run id, tool call id, trace ref, toolkit id, capability, and
  status
- usage metrics copied from the caller-safe completion object
- artifact references reduced to id, type, MIME, size, checksum, retention, and
  expiry metadata
- policy and approval summaries that list safe field names only
- data-minimization assertions proving raw input, raw output, raw media,
  artifact locators, storage locators, and worker locators are not logged

Example shape:

```json
{
  "schema": "video_editing_toolkit.platform_core.handoff.v0",
  "contract": "platform_core_learning_audit_event.v0",
  "event_type": "toolkit_run_metadata",
  "toolkit_id": "video-editing-toolkit",
  "capability": "audio.speech.transcribe",
  "status": "succeeded",
  "data_minimization": {
    "raw_input_logged": false,
    "raw_output_logged": false,
    "raw_media_logged": false,
    "artifact_locator_logged": false,
    "storage_locator_logged": false,
    "worker_locator_logged": false
  }
}
```

## Release Dossier

Contract name: `platform_core_release_dossier.v0`

Purpose: summarize the review evidence needed before a future Platform Core
release or rollout decision.

The release dossier is a review packet, not a publication command. It must not
publish to release-center, alter Tool Catalog records, or mark any capability
available in production.

The release dossier should contain:

- release candidate identity: toolkit id, manifest path, manifest digest if
  available, and dossier version
- included contract references: onboarding bundle, learning audit event,
  descriptor, request normalization, completion normalization, and artifact
  contract docs
- capability rollout table preserving each manifest status
- remaining gates for Platform Core authorization, quotas, tracing, artifact
  byte service, retention, approval policy, and isolated execution
- explicit P1 disabled capability statement
- explicit high-sensitivity deferral statement
- local verification command references and expected status
- reviewer checklist with approval owner placeholders

Example shape:

```json
{
  "schema": "video_editing_toolkit.platform_core.handoff.v0",
  "contract": "platform_core_release_dossier.v0",
  "status": "review_only",
  "publishable": false,
  "toolkit_id": "video-editing-toolkit",
  "release_posture": "review_packet_only",
  "capability_rollout": {
    "preserve_manifest_status": true,
    "enable_p1_disabled_capabilities": false
  },
  "platform_core_mutation": {
    "tool_catalog": false,
    "runspecs": false,
    "release_center": false,
    "learning_audit_ingestion": false,
    "artifact_records": false
  }
}
```

## Implemented Commands

The local CLI emits JSON only and does not call Platform Core:

```powershell
video-toolkit-platform-core --onboarding-bundle
video-toolkit-platform-core --audit-event-json '<json request/completion payload>'
video-toolkit-platform-core --release-dossier --git-revision <revision>
```

These commands are intended for future Product Adapter, learning/audit, and
Release Center ingestion. Real ingestion and publication remain Platform
Core-side actions.

## Review Checklist

Before any implementation produces these payloads, reviewers should confirm:

1. Payload generation reads local manifests and docs only.
2. Generated payloads are metadata-only and review-only.
3. No network clients are imported or invoked by default.
4. No Platform Core repository path is required or modified.
5. P1 disabled capabilities remain disabled in every payload.
6. High-sensitivity capabilities remain deferred unless a separate Platform
   Core approval contract exists.
7. Caller-visible payloads exclude local paths, `storage_uri`, raw commands,
   environment values, stderr, signed URLs, and secret-like fields.

## Related Docs

- `docs/agentctl-platform-core.md`
- `docs/p1-roadmap-2026-05-08.md`
- `docs/release-gate.md`
- `docs/manifest-contract.md`
