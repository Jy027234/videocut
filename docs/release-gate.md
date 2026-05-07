# P0.15 Platform Core Handoff Interface Gate

Date: 2026-05-07

Status: P0.8 local release-candidate gate plus P0.9-P0.15 local Docker
agentctl pre-integration, runtime worker, artifact materialization,
resource-policy, subprocess execution, worker lifecycle control, and Platform
Core handoff interface checks.

## Blocking Gates

A P0.9 release candidate is `no_go` when any of these checks fail:

- Manifest JSON cannot be parsed, misses required P0 fields, or leaks local runtime details.
- Any manifest `input_schema` or `output_schema` `$ref` points to a missing schema file or an unresolvable JSON Pointer fragment such as `#/$defs/...`.
- The manifest enabled capability set differs from `CAPABILITY_ROUTES` or from the local runtime handler registration used by agentctl and the local API.
- A structured no-upload request behaves differently between agentctl and the local HTTP API for status, output, selected capability, run id, or tool call id.
- Project-edit `apply_timeline_patch` does not produce a schema-valid `timeline.json` artifact, or preview planning does not produce a schema-valid `render_config.json` artifact.
- The remote agentctl probe cannot authenticate to configured local Docker agentctl or required paths are missing: `/healthz`, `/openapi.json`, `/tool-catalog`, `/tool-catalog/register`, `/runspecs/validate`, `/runspecs/run`, `/runtime/backends`, `/runtime/backends/workers/protocol`, `/runtime/backends/workers/heartbeat`, `/runtime/backends/jobs`, `/runtime/backends/jobs/lease`, or `/runtime/backends/jobs/{job_id}/complete`.
- The P0 manifest cannot be converted into a caller-safe `/tool-catalog/register` draft payload.
- The no-upload `RunSpecDraft` for `video.project_edit.create_project` is rejected by `/runspecs/validate`.
- The P0.9 performance decision says to run heavy media work inside agentctl instead of an external video toolkit worker.
- The P0.10 worker cannot lease and complete a no-upload `video.project_edit.create_project` runtime job created through `/runspecs/run` with `dispatch_mode=enqueue` in the configured local dev agentctl.
- The P0.11 worker cannot materialize a caller-safe artifact ref with a controlled relative `download_url`, preserve its safe `artifact_id`, verify `size_bytes` and `sha256`, and execute an artifact-dependent local adapter path.
- The P0.11 materialization layer accepts path traversal artifact ids, `storage_uri` as a download source, `file://`, non-http schemes, or off-origin absolute download URLs.
- The P0.12 worker does not reject unknown capabilities before materialization/execution.
- The P0.12 default worker accepts CPU-heavy, GPU-optional, or GPU-required capabilities without explicit `allowed_resource_classes`.
- The P0.12 worker ignores configured capability allowlists, declared input-size limits, or route timeout limits.
- The P0.13 subprocess execution mode cannot run a no-upload structured capability through `sys.executable -m video_editing_toolkit.agentctl` with the same run id and tool call id traceability.
- The P0.13 subprocess runner returns raw argv, stderr, environment, local artifact root, or token-like values in caller-visible payloads.
- The P0.13 subprocess timeout path does not return stable `video_toolkit_worker.execution_timeout` / `resource.timeout_exceeded`.
- The P0.14 worker heartbeat does not advertise execution_backend, supported_execution_backends, max_attempts, retry_policy, and the worker lifecycle contract.
- The P0.14 worker accepts a runtime job whose attempts value exceeds max_attempts, or performs artifact materialization/local execution before rejecting it.
- The P0.14 worker materializes artifacts or runs local execution for jobs marked cancel_requested/cancelled/cancelling.
- The P0.14 registered `docker` or `remote` execution backend fails with an unstable or leaky error instead of `video_toolkit_worker.execution_backend_unavailable`.
- The P0.14 worker completion metadata omits trace_ref, usage_metrics, execution_backend, attempt, or max_attempts for executed jobs.
- The local API cannot cancel a queued run through `/local/toolkit-runs/{run_id}/cancel`.
- The P0.15 Platform Core descriptor cannot be built from the P0 manifest or omits required Tool Catalog handoff metadata.
- The P0.15 Platform Core request normalizer fails to preserve platform_run_id, platform_tool_call_id, trace id, tenant/user policy context, capability, input, or caller-safe artifact refs.
- The P0.15 Platform Core completion normalizer omits run_id, tool_call_id, status, output, artifact_refs, usage_metrics, trace_ref, error_code/error_message, or artifact_contract.
- Any P0.15 Platform Core handoff payload exposes `storage_uri`, local filesystem paths, worker paths, raw commands, argv, stderr, environment, or credential-like fields.
- Materialization failure payloads expose download URLs, local filesystem paths, `storage_uri`, `local-artifact://`, worker-only paths, or plaintext credential-like fields.
- Execution-policy failure payloads expose download URLs, local filesystem paths, `storage_uri`, `local-artifact://`, worker-only paths, or plaintext credential-like fields.
- Local-execution failure payloads expose local filesystem paths, raw command arrays, stderr, environment, or plaintext credential-like fields.
- Caller-visible output exposes `storage_uri`, local filesystem paths, raw shell or FFmpeg commands, worker-only paths, internal worker URLs, or plaintext credential-like fields.
- FastAPI-local API tests fail in environments where the optional `api` extra is installed. In default environments without FastAPI, API tests must skip cleanly.

## Explicit Non-Blockers For P0 RC

These items remain required for later platformization, but they are not P0.9 RC blockers while the local contract tests above pass:

- Full timeline compositor semantics beyond the controlled P0 render/preview paths.
- Formal Platform Core authorization and policy enforcement beyond the local caller-safety and tenant-bound artifact checks.
- Persistent or distributed queueing beyond the in-memory local queue.
- External file upload through agentctl or the local HTTP API.
- Production object storage, signed URL rotation, resumable byte streaming, and byte streaming from `GET /local/artifacts/{artifact_id}`. P0.11 only requires the worker-side materialization contract against a compatible byte endpoint.
- Production resource sandboxing, automatic retries, in-flight cancellation workers, and multi-process scheduling. P0.14 only adds execution-backend registration, attempt preflight, pre-execution cancel handling, trace/usage completion metadata, and a local subprocess timeout boundary.
- agentctl Docker runtime backend being disabled in the local control-plane container. P0.9 only requires protocol discovery, catalog registration shape, RunSpec validation, and optional heartbeat/idle lease smoke.
- Live Platform Core client calls, Product Adapter onboarding, learning/audit ingestion, release-center publishing, and production `/runspecs/run` execution. Those are P1/P2 platformization concerns.

## Local Verification

Recommended RC gate commands:

```powershell
py -m pytest tests/test_manifest_schema_contract.py tests/test_agentctl_cli_contract.py tests/test_local_api_contract.py -q
py -m pytest tests/test_project_edit_artifact_contract.py tests/test_artifact_manifest_schema_contract.py -q
py -m pytest tests/test_agentctl_remote_probe_contract.py -q
py -m pytest tests/test_agentctl_worker_contract.py -q
py -m pytest tests/test_agentctl_worker_runner_contract.py -q
py -m pytest tests/test_agentctl_worker_runner_contract.py tests/test_agentctl_worker_contract.py tests/test_local_api_contract.py -q
py -m pytest tests/test_platform_core_handoff_contract.py -q
py -m pytest tests/test_artifact_materialization_contract.py -q
py -m pytest tests -q
```

The final pytest command is the full local suite. Hosts without optional media or API
dependencies may report skips, but those skips must be intentional and stable.

Optional live local Docker agentctl checks:

```powershell
$env:PYTHONPATH='src'
$env:VIDEO_TOOLKIT_AGENTCTL_TOKEN='<local-agentctl-token>'
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --validate-runspec
py -m video_editing_toolkit.agentctl_remote --base-url http://127.0.0.1:8765 --worker-smoke
py -m video_editing_toolkit.agentctl_worker --base-url http://127.0.0.1:8765 --enqueue-probe
```

`--register` is allowed in a local dev control plane when the operator wants to
refresh the draft tool-catalog entry. It must not trigger media execution.
