"""P0.15 Platform Core handoff contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.agentctl import run_agentctl
from video_editing_toolkit.platform_core import (
    build_platform_core_completion,
    build_platform_core_learning_audit_event,
    build_platform_core_local_loop_rehearsal_package,
    build_platform_core_manifest_registration_dry_run,
    build_platform_core_onboarding_bundle,
    build_platform_core_release_dossier,
    build_platform_core_toolkit_descriptor,
    platform_core_envelope_to_agentctl,
)


def test_platform_core_descriptor_is_manifest_backed_and_caller_safe() -> None:
    descriptor = build_platform_core_toolkit_descriptor()

    assert descriptor["schema"] == "video_editing_toolkit.platform_core.handoff.v0"
    assert descriptor["contract"] == "platform_core_toolkit_descriptor.v0"
    assert descriptor["toolkit_id"] == "video-editing-toolkit"
    assert descriptor["handoff"]["execution_model"] == "external_video_toolkit_worker"
    assert descriptor["handoff"]["artifact_contract"] == "artifact_ref_only"
    assert "cancel(run_id)" in descriptor["handoff"]["adapter_entrypoints"]
    assert "toolkit.video_editing.p0" in descriptor["required_scopes"]
    assert len(descriptor["capabilities"]) >= 20
    assert "video.render.render_final" in {
        capability["capability"] for capability in descriptor["capabilities"]
    }
    assert_no_public_path_or_command_leak(descriptor)


def test_platform_core_onboarding_bundle_is_review_only_and_p1_manifest_backed() -> None:
    bundle = build_platform_core_onboarding_bundle(tenant_id="tenant_product_review")

    assert bundle["schema"] == "video_editing_toolkit.platform_core.handoff.v0"
    assert bundle["contract"] == "platform_core_toolkit_onboarding_bundle.v0"
    assert bundle["status"] == "review_only"
    assert bundle["tenant_id"] == "tenant_product_review"
    assert bundle["release_center"]["publishable"] is False
    assert bundle["release_center"]["enablement_requires_platform_core_change"] is True
    assert bundle["learning_audit"]["ingest_mode"] == "metadata_only"
    assert bundle["learning_audit"]["raw_media_ingestion"] is False
    assert bundle["catalog_draft"]["credential_refs"] == []
    assert bundle["catalog_draft"]["default_route_table"] == "p0_only"
    assert bundle["catalog_draft"]["experimental_route_table"] == "explicit_resolver_only"

    invokable = {
        item["capability"] for item in bundle["catalog_draft"]["invokable_capabilities"]
    }
    review = {item["capability"] for item in bundle["catalog_draft"]["review_capabilities"]}
    assert "video.project_edit.create_project" in invokable
    assert "audio.tts.generate_voiceover" not in invokable
    assert {
        "audio.tts.generate_voiceover",
        "video.qc.build_evidence_packet",
        "video.render.export_project_format",
    }.issubset(review)
    assert bundle["capability_summary"]["p1_review_count"] >= 6
    assert {
        item["capability"] for item in bundle["deferred_high_sensitivity_capabilities"]
    } == {
        "audio.tts.clone_voice",
        "audio.speech.diarize_speakers",
        "video.analysis.recognize_faces",
        "video.analysis.recognize_people",
    }
    assert_no_public_path_or_command_leak(bundle)


def test_platform_core_learning_audit_event_is_metadata_only_and_caller_safe(tmp_path: Path) -> None:
    private_path = str(tmp_path / "private" / "source.mov")
    token = "artifact-secret-token"
    payload = {
        "request": {
            "platform_run_id": "platform_run_audit",
            "platform_tool_call_id": "platform_tool_call_audit",
            "platform_trace_id": "trace_platform_audit",
            "toolkit_id": "video-editing-toolkit",
            "capability": "audio.speech.transcribe",
            "input": {
                "prompt": "Summarize private customer launch footage.",
                "_worker_media_path": private_path,
            },
            "policy_context": {
                "tenant_id": "tenant_audit",
                "user_id": "user_audit",
                "share_id": "share_audit",
                "data_policy": {"retain_raw_input": False},
                "quota_policy": {"profile": "review"},
            },
            "approval_context": {
                "platform_approval_id": "approval_audit",
                "provider_token": token,
            },
            "artifact_refs": [
                {
                    "artifact_id": "artifact_audit_source",
                    "artifact_type": "source_video",
                    "mime_type": "video/mp4",
                    "size_bytes": 123,
                    "checksum": "sha256:" + "a" * 64,
                    "storage_uri": "s3://internal/private/source.mov",
                    "download_url": f"/toolkit-artifacts/artifact_audit_source/bytes?sat={token}",
                }
            ],
        },
        "completion": {
            "toolkit_id": "video-editing-toolkit",
            "capability": "audio.speech.transcribe",
            "processed": {
                "run_id": "platform_run_audit",
                "tool_call_id": "platform_tool_call_audit",
                "trace_ref": "trace_platform_audit",
                "status": "succeeded",
                "output": {"text": "Private transcript text should never enter the audit event."},
                "usage_metrics": {"duration_ms": 12},
                "artifact_refs": [
                    {
                        "artifact_id": "artifact_transcript",
                        "artifact_type": "transcript_json",
                        "mime_type": "application/json",
                        "size_bytes": 321,
                        "checksum": "sha256:" + "b" * 64,
                        "download_url": f"/toolkit-artifacts/artifact_transcript/bytes?sat={token}",
                    }
                ],
            },
        },
    }

    event = build_platform_core_learning_audit_event(payload)
    rendered = json.dumps(event, sort_keys=True)

    assert event["contract"] == "platform_core_learning_audit_event.v0"
    assert event["event_type"] == "toolkit_run_metadata"
    assert event["run_id"] == "platform_run_audit"
    assert event["tool_call_id"] == "platform_tool_call_audit"
    assert event["trace_ref"] == "trace_platform_audit"
    assert event["usage_metrics"] == {"duration_ms": 12}
    assert event["artifact_refs"] == [
        {
            "artifact_id": "artifact_transcript",
            "artifact_type": "transcript_json",
            "mime_type": "application/json",
            "size_bytes": 321,
            "checksum": "sha256:" + "b" * 64,
        }
    ]
    assert event["policy_summary"]["tenant_id"] == "tenant_audit"
    assert event["approval_summary"]["field_names"] == ["platform_approval_id"]
    assert event["data_minimization"]["raw_input_logged"] is False
    assert event["data_minimization"]["raw_output_logged"] is False
    assert "Private transcript" not in rendered
    assert "Summarize private" not in rendered
    assert private_path not in rendered
    assert token not in rendered
    assert "download_url" not in rendered
    assert "storage_uri" not in rendered
    assert_no_public_path_or_command_leak(event)


def test_platform_core_release_dossier_is_review_only_and_hash_bound() -> None:
    dossier = build_platform_core_release_dossier(
        git_revision="rev_test_release",
        qa_report_refs=["qa/manifest-validation/0.1.0/rev_test_release.json"],
    )

    assert dossier["contract"] == "platform_core_release_dossier.v0"
    assert dossier["status"] == "review_only"
    assert dossier["publishable"] is False
    assert dossier["git_revision"] == "rev_test_release"
    assert dossier["source_manifest"]["path"] == "manifests/video-editing-toolkit.p1.manifest.json"
    assert len(dossier["source_manifest"]["sha256"]) == 64
    assert {item["path"] for item in dossier["schema_digests"]} == {
        "schemas/toolkit-manifest.schema.json",
        "schemas/capability-io.schema.json",
        "schemas/artifact-manifests.schema.json",
    }
    assert dossier["capability_matrix"]["enabled_count"] >= 20
    assert dossier["capability_matrix"]["p1_review_count"] >= 6
    assert dossier["release_decision"]["decision"] == "no_go"
    assert "publish_to_release_center" in dossier["blocked_actions"]
    assert "modify_platform_core_repository" in dossier["blocked_actions"]
    assert_no_public_path_or_command_leak(dossier)


def test_platform_core_manifest_registration_dry_run_preserves_disabled_p1() -> None:
    dry_run = build_platform_core_manifest_registration_dry_run(
        tenant_id="tenant_platform_review",
    )

    assert dry_run["contract"] == "platform_core_manifest_registration_dry_run.v0"
    assert dry_run["status"] == "review_only"
    assert dry_run["tenant_id"] == "tenant_platform_review"
    assert dry_run["dry_run"] is True
    assert dry_run["network_mutation"] is False
    assert dry_run["publishable"] is False
    assert dry_run["platform_core_boundaries"]["write_platform_core_repository"] is False
    assert dry_run["platform_core_boundaries"]["register_tool_catalog"] is False
    assert "modify_platform_core_repository" in dry_run["blocked_actions"]

    invokable = set(dry_run["registration_preview"]["invokable_capabilities"])
    review_only = {
        item["capability"]
        for item in dry_run["capability_matrix"]["p1_review_only_capabilities"]
    }
    assert "video.project_edit.create_project" in invokable
    assert "audio.tts.generate_voiceover" in review_only
    assert not invokable.intersection(review_only)
    assert dry_run["activation_policy"]["default_route_table"] == "p0_only"
    assert dry_run["activation_policy"]["enable_p1_disabled_capabilities"] is False
    assert_no_public_path_or_command_leak(dry_run)


def test_platform_core_local_loop_rehearsal_package_is_no_mutation_and_caller_safe() -> None:
    package = build_platform_core_local_loop_rehearsal_package(
        tenant_id="tenant_loop",
        artifact_refs=[
            {
                "artifact_id": "artifact_loop_source",
                "artifact_type": "source_video",
                "mime_type": "video/mp4",
                "size_bytes": 123,
                "checksum": "sha256:" + "c" * 64,
                "download_url": "/toolkit-artifacts/artifact_loop_source/bytes?sat=secret-token",
                "storage_uri": "s3://internal/private/source.mp4",
            }
        ],
    )
    rendered = json.dumps(package, sort_keys=True)

    assert package["contract"] == "platform_core_local_loop_rehearsal_package.v0"
    assert package["status"] == "rehearsal_only"
    assert package["dry_run"] is True
    assert package["network_mutation"] is False
    assert package["execution_performed"] is False
    assert package["platform_core_repository_mutation"] is False
    assert package["manifest_registration_dry_run"]["network_mutation"] is False
    assert package["agentctl_envelope"]["run_id"] == "platform_run_p1_7_rehearsal"
    assert package["runspec_enqueue_preview"]["dispatch_mode"] == "enqueue"
    assert package["completion_template"]["error_code"] == "platform_core.local_loop_rehearsal_not_executed"
    assert package["audit_event_template"]["data_minimization"]["raw_input_logged"] is False
    assert "artifact_lifecycle_summary" in package["worker_contract"]["expected_worker_metadata"]
    assert "secret-token" not in rendered
    assert "storage_uri" not in rendered
    assert_no_public_path_or_command_leak(package)


def test_platform_core_request_normalizes_to_agentctl_envelope_without_storage_internals(
    tmp_path: Path,
) -> None:
    payload = {
        "platform_run_id": "platform_run_001",
        "platform_tool_call_id": "platform_tool_call_001",
        "platform_trace_id": "trace_platform_001",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.project_edit.create_project",
        "version": "0.1.0-p0",
        "tenant_id": "tenant_platform",
        "user_id": "user_platform",
        "private_key": "platform-secret-value",
        "input": {
            "project_id": "proj_platform",
            "_worker_media_path": str(tmp_path / "private.mp4"),
        },
        "artifact_refs": [
            {
                "artifact_id": "artifact_platform_source",
                "artifact_type": "source_video",
                "owner_tenant_id": "tenant_platform",
                "mime_type": "video/mp4",
                "size_bytes": 123,
                "checksum": "sha256:abc",
                "storage_uri": "s3://internal-bucket/private.mp4",
                "download_url": "/artifacts/download/artifact_platform_source",
            }
        ],
        "approval_context": {
            "approval_id": "approval_001",
            "token": "approval-secret-token",
        },
    }

    envelope = platform_core_envelope_to_agentctl(payload)
    rendered = json.dumps(envelope, sort_keys=True)

    assert envelope["run_id"] == "platform_run_001"
    assert envelope["tool_call_id"] == "platform_tool_call_001"
    assert envelope["trace_ref"] == "trace_platform_001"
    assert envelope["policy_context"]["tenant_id"] == "tenant_platform"
    assert envelope["artifact_refs"][0]["download_url"] == "/artifacts/download/artifact_platform_source"
    assert "storage_uri" not in rendered
    assert "platform-secret-value" not in rendered
    assert "approval-secret-token" not in rendered
    assert str(tmp_path) not in rendered
    assert_no_public_path_or_command_leak(envelope)


def test_platform_core_completion_wraps_local_agentctl_result(tmp_path: Path) -> None:
    request = {
        "platform_run_id": "platform_run_completion",
        "platform_tool_call_id": "platform_tool_call_completion",
        "trace_id": "trace_platform_completion",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.project_edit.create_project",
        "input": {"project_id": "proj_platform_completion"},
        "policy_context": {
            "tenant_id": "tenant_platform",
            "user_id": "user_platform",
        },
    }
    local_result = run_agentctl(
        platform_core_envelope_to_agentctl(request),
        artifact_root=tmp_path / "agentctl-artifacts",
    )

    completion = build_platform_core_completion(local_result, request=request)

    assert completion["contract"] == "platform_core_toolkit_run_completion.v0"
    assert completion["status"] == "succeeded"
    assert completion["run_id"] == "platform_run_completion"
    assert completion["tool_call_id"] == "platform_tool_call_completion"
    assert completion["trace_ref"] == "trace_platform_completion"
    assert completion["output"]["project_id"] == "proj_platform_completion"
    assert completion["artifact_contract"] == "artifact_ref_only"
    assert_no_public_path_or_command_leak(completion)


def test_platform_core_completion_extracts_worker_artifact_lifecycle_metadata() -> None:
    request = {
        "platform_run_id": "platform_run_worker_completion",
        "platform_tool_call_id": "platform_tool_call_worker_completion",
        "trace_id": "trace_platform_worker_completion",
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.asset_ingest.build_asset_index",
    }
    worker_completion_body = {
        "worker_id": "video-worker-test",
        "lease_id": "lease_worker_test",
        "status": "completed",
        "result": {
            "schema": "video_editing_toolkit.agentctl.local_run.v0",
            "ok": True,
            "processed": {
                "run_id": "platform_run_worker_completion",
                "tool_call_id": "platform_tool_call_worker_completion",
                "trace_ref": "trace_platform_worker_completion",
                "status": "succeeded",
                "output": {"asset_count": 1},
                "artifact_refs": [
                    {
                        "artifact_id": "artifact_index",
                        "artifact_type": "asset_index",
                        "mime_type": "application/json",
                        "size_bytes": 12,
                        "checksum": "sha256:" + "d" * 64,
                    }
                ],
            },
        },
        "metadata": {
            "trace_ref": "trace_platform_worker_completion",
            "usage_metrics": {"worker_runtime_ms": 3.5},
            "artifact_lifecycle_summary": {
                "contract": "video_editing_toolkit.worker_artifact_lifecycle_summary.v0",
                "stage": "input_materialization",
                "status": "completed",
                "requested_count": 1,
                "materialized_count": 1,
                "cached_count": 0,
                "artifact_ids": ["artifact_source"],
                "local_paths_returned": False,
                "storage_uri_returned": False,
            },
        },
    }

    completion = build_platform_core_completion(worker_completion_body, request=request)

    assert completion["status"] == "succeeded"
    assert completion["output"] == {"asset_count": 1}
    assert completion["usage_metrics"] == {"worker_runtime_ms": 3.5}
    assert completion["artifact_refs"][0]["artifact_id"] == "artifact_index"
    assert completion["artifact_lifecycle_summary"]["status"] == "completed"
    assert completion["artifact_lifecycle_summary"]["artifact_ids"] == ["artifact_source"]
    assert_no_public_path_or_command_leak(completion)


def test_platform_core_cli_descriptor_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "video_editing_toolkit.platform_core", "--descriptor"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_toolkit_descriptor.v0"
    assert payload["toolkit_id"] == "video-editing-toolkit"
    assert_no_public_path_or_command_leak(payload)


def test_platform_core_cli_onboarding_bundle_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "video_editing_toolkit.platform_core", "--onboarding-bundle"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_toolkit_onboarding_bundle.v0"
    assert payload["release_center"]["publishable"] is False
    assert_no_public_path_or_command_leak(payload)


def test_platform_core_cli_audit_event_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_editing_toolkit.platform_core",
            "--audit-event-json",
            json.dumps(
                {
                    "request": {
                        "platform_run_id": "platform_run_cli_audit",
                        "platform_tool_call_id": "tool_call_cli_audit",
                        "toolkit_id": "video-editing-toolkit",
                        "capability": "video.project_edit.create_project",
                    },
                    "completion": {
                        "processed": {
                            "status": "succeeded",
                            "usage_metrics": {"duration_ms": 1},
                        }
                    },
                }
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_learning_audit_event.v0"
    assert payload["run_id"] == "platform_run_cli_audit"
    assert payload["data_minimization"]["raw_input_logged"] is False
    assert_no_public_path_or_command_leak(payload)


def test_platform_core_cli_release_dossier_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_editing_toolkit.platform_core",
            "--release-dossier",
            "--git-revision",
            "rev_cli_release",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_release_dossier.v0"
    assert payload["git_revision"] == "rev_cli_release"
    assert payload["publishable"] is False
    assert_no_public_path_or_command_leak(payload)


def test_platform_core_cli_manifest_registration_dry_run_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_editing_toolkit.platform_core",
            "--manifest-registration-dry-run",
            "--registration-tenant-id",
            "tenant_cli_registration",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_manifest_registration_dry_run.v0"
    assert payload["tenant_id"] == "tenant_cli_registration"
    assert payload["network_mutation"] is False
    assert_no_public_path_or_command_leak(payload)


def test_platform_core_cli_local_loop_package_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_editing_toolkit.platform_core",
            "--local-loop-package",
            "--loop-tenant-id",
            "tenant_cli_loop",
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract"] == "platform_core_local_loop_rehearsal_package.v0"
    assert payload["tenant_id"] == "tenant_cli_loop"
    assert payload["execution_performed"] is False
    assert_no_public_path_or_command_leak(payload)
