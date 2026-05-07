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
