"""P0.6 local agentctl bridge contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from conftest import REPO_ROOT, assert_no_public_path_or_command_leak, walk_json


def test_agentctl_input_json_outputs_caller_safe_create_project(tmp_path: Path) -> None:
    artifact_root = tmp_path / "agentctl-artifacts"
    secret_value = "agentctl-test-private-key"
    payload = {
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.project_edit.create_project",
        "artifact_store_root": str(tmp_path / "input-root-should-not-leak"),
        "private_key": secret_value,
        "artifact_refs": [
            {
                "artifact_id": "artifact_optional_agentctl_ref",
                "artifact_type": "input_video",
                "mime_type": "video/mp4",
                "size_bytes": 123,
                "checksum": "sha256:optional",
                "storage_uri": f"local-artifact://artifact_optional_agentctl_ref/{secret_value}",
            }
        ],
        "input": {
            "project_id": "proj_agentctl_create",
            "_worker_media_path": str(tmp_path / "private-input.mp4"),
        },
    }

    result = _run_agentctl(
        "--input-json",
        json.dumps(payload),
        "--artifact-root",
        str(artifact_root),
    )

    assert result.returncode == 0, result.stderr
    body = _json_stdout(result)
    assert body["schema"] == "video_editing_toolkit.agentctl.local_run.v0"
    assert body["transport"] == "agentctl.local"
    assert body["ok"] is True
    assert body["queued"]["status"] == "queued"
    assert body["processed"]["status"] == "succeeded"
    assert body["processed"]["output"]["project_id"] == "proj_agentctl_create"
    assert body["processed"]["output"]["adapter_name"] == "project_edit"
    _assert_agentctl_public_safe(body, artifact_root, secret_value)


def test_agentctl_stdin_runs_generate_variants(tmp_path: Path) -> None:
    artifact_root = tmp_path / "agentctl-artifacts"
    payload = {
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.delivery.generate_variants",
        "input": {
            "project_id": "proj_agentctl_delivery",
            "version": "ver_agentctl_0001",
            "variants": [
                {
                    "name": "web",
                    "delivery_target": "web",
                    "format": "mp4",
                    "resolution": "1080p",
                }
            ],
        },
    }

    result = _run_agentctl(
        "--artifact-root",
        str(artifact_root),
        stdin=json.dumps(payload),
    )

    assert result.returncode == 0, result.stderr
    body = _json_stdout(result)
    output = body["processed"]["output"]
    assert body["ok"] is True
    assert body["processed"]["status"] == "succeeded"
    assert output["project_id"] == "proj_agentctl_delivery"
    assert output["version"] == "ver_agentctl_0001"
    assert output["variant_count"] == 1
    assert output["variants"][0]["variant_id"] == "web"
    _assert_agentctl_public_safe(body, artifact_root)


def test_agentctl_unknown_capability_returns_stable_failure(tmp_path: Path) -> None:
    artifact_root = tmp_path / "agentctl-artifacts"
    payload = {
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.unknown.noop",
        "input": {"project_id": "proj_agentctl_unknown"},
    }

    result = _run_agentctl(
        "--input-json",
        json.dumps(payload),
        "--artifact-root",
        str(artifact_root),
    )

    assert result.returncode == 0, result.stderr
    body = _json_stdout(result)
    assert body["ok"] is False
    assert body["queued"]["status"] == "queued"
    assert body["processed"]["status"] == "failed"
    assert body["processed"]["error_code"] == "handler_not_registered"
    assert "No local handler registered" in body["processed"]["error_message"]
    _assert_agentctl_public_safe(body, artifact_root)


def _run_agentctl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "video_editing_toolkit.agentctl", *args],
        input=stdin,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


def _assert_agentctl_public_safe(
    body: dict[str, Any],
    artifact_root: Path,
    secret_value: str | None = None,
) -> None:
    assert_no_public_path_or_command_leak(body)
    rendered = json.dumps(body, sort_keys=True)
    assert str(artifact_root) not in rendered
    if secret_value is not None:
        assert secret_value not in rendered
    for path, node in walk_json(body):
        if isinstance(node, dict):
            leaked = {"private_key", "api_key", "client_secret", "token", "password"}.intersection(node)
            assert not leaked, f"{path} exposes private keys: {sorted(leaked)}"
